"""
Enhanced Gemini-to-Claude API Proxy v2.2.0

Implements comprehensive improvements:
- Pydantic BaseSettings for robust configuration
- String constants for maintainability
- Refactored large functions into focused helpers
- Enhanced error formatting for better client experience
- Improved tool result parsing with dispatch pattern
"""

from fastapi import FastAPI, Request, HTTPException
import uvicorn
import logging
import json
import re
from pydantic import BaseModel, Field, field_validator, ValidationError
from typing import List, Dict, Any, Optional, Union, Literal, Set, Callable
import os
from fastapi.responses import JSONResponse, StreamingResponse
import litellm
try:
    from litellm.exceptions import APIConnectionError
except ImportError:
    APIConnectionError = Exception
import uuid
import time
from dotenv import load_dotenv
from datetime import datetime
import sys

# Load environment variables early
load_dotenv()

# Centralized Default Configuration Values
class DefaultConfigValues:
    """Centralized default configuration values to ensure consistency"""
    
    # Model defaults
    BIG_MODEL = "gemini-1.5-pro-latest"
    SMALL_MODEL = "gemini-1.5-flash-latest"
    
    # Server defaults
    HOST = "0.0.0.0"
    PORT = 8082
    LOG_LEVEL = "WARNING"
    
    # Performance defaults
    MAX_TOKENS_LIMIT = 8192
    REQUEST_TIMEOUT = 60
    NUM_RETRIES = 2
    
    # Health check defaults
    HEALTH_CHECK_API_TIMEOUT = 5.0
    
    # Tool schema defaults
    ALLOWED_STRING_FORMATS = {"enum", "date-time"}

# Try to import pydantic-settings, fall back to manual config if not available
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    HAS_PYDANTIC_SETTINGS = True
except ImportError:
    HAS_PYDANTIC_SETTINGS = False
    BaseSettings = BaseModel

# Constants for better maintainability
class Constants:
    """String constants used throughout the application"""
    
    # Roles
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_SYSTEM = "system"
    ROLE_TOOL = "tool"
    
    # Content Types
    CONTENT_TEXT = "text"
    CONTENT_IMAGE = "image"
    CONTENT_TOOL_USE = "tool_use"
    CONTENT_TOOL_RESULT = "tool_result"
    
    # Tool Types
    TOOL_FUNCTION = "function"
    
    # Stop Reasons
    STOP_END_TURN = "end_turn"
    STOP_MAX_TOKENS = "max_tokens"
    STOP_TOOL_USE = "tool_use"
    STOP_ERROR = "error"
    
    # SSE Event Types
    EVENT_MESSAGE_START = "message_start"
    EVENT_MESSAGE_STOP = "message_stop"
    EVENT_MESSAGE_DELTA = "message_delta"
    EVENT_CONTENT_BLOCK_START = "content_block_start"
    EVENT_CONTENT_BLOCK_STOP = "content_block_stop"
    EVENT_CONTENT_BLOCK_DELTA = "content_block_delta"
    EVENT_PING = "ping"
    
    # Delta Types
    DELTA_TEXT = "text_delta"
    DELTA_INPUT_JSON = "input_json_delta"
    
    # Tool Choice Types
    TOOL_CHOICE_AUTO = "auto"
    TOOL_CHOICE_ANY = "any"
    TOOL_CHOICE_TOOL = "tool"
    
    # Finish Reasons (LiteLLM)
    FINISH_LENGTH = "length"
    FINISH_TOOL_CALLS = "tool_calls"
    FINISH_STOP = "stop"
    
    # Model Aliases
    MODEL_HAIKU = "haiku"
    MODEL_SONNET = "sonnet"
    MODEL_OPUS = "opus"

# Enhanced Configuration Management
if HAS_PYDANTIC_SETTINGS:
    class ServerConfig(BaseSettings):
        """Enhanced configuration using Pydantic Settings"""
        model_config = SettingsConfigDict(
            env_file=".env", 
            env_file_encoding="utf-8",
            case_sensitive=False
        )
        
        # API Configuration
        gemini_api_key: str = Field(..., alias="GEMINI_API_KEY")
        
        # Model Configuration - keeping your naming convention
        big_model: str = Field(default=DefaultConfigValues.BIG_MODEL, alias="BIG_MODEL")
        small_model: str = Field(default=DefaultConfigValues.SMALL_MODEL, alias="SMALL_MODEL")
        
        # Server Configuration
        host: str = Field(default=DefaultConfigValues.HOST, alias="HOST")
        port: int = Field(default=DefaultConfigValues.PORT, alias="PORT")
        log_level: str = Field(default=DefaultConfigValues.LOG_LEVEL, alias="LOG_LEVEL")
        
        # Limits
        max_tokens_limit: int = Field(default=DefaultConfigValues.MAX_TOKENS_LIMIT, alias="MAX_TOKENS_LIMIT")
        request_timeout: int = Field(default=DefaultConfigValues.REQUEST_TIMEOUT, alias="REQUEST_TIMEOUT")
        num_retries: int = Field(default=DefaultConfigValues.NUM_RETRIES, alias="NUM_RETRIES")
        
        # Health check configuration
        health_check_api_timeout: float = Field(default=DefaultConfigValues.HEALTH_CHECK_API_TIMEOUT, alias="HEALTH_CHECK_API_TIMEOUT")
        
        # Tool Schema Configuration
        allowed_string_formats: Set[str] = Field(default=DefaultConfigValues.ALLOWED_STRING_FORMATS)
else:
    # Fallback configuration class
    class ServerConfig:
        """Fallback configuration without pydantic-settings"""
        def __init__(self):
            self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
            if not self.gemini_api_key:
                raise ValueError("GEMINI_API_KEY not found in environment variables")
            
            self.big_model = os.environ.get("BIG_MODEL", DefaultConfigValues.BIG_MODEL)
            self.small_model = os.environ.get("SMALL_MODEL", DefaultConfigValues.SMALL_MODEL)
            self.host = os.environ.get("HOST", DefaultConfigValues.HOST)
            self.port = int(os.environ.get("PORT", str(DefaultConfigValues.PORT)))
            self.log_level = os.environ.get("LOG_LEVEL", DefaultConfigValues.LOG_LEVEL)
            self.max_tokens_limit = int(os.environ.get("MAX_TOKENS_LIMIT", str(DefaultConfigValues.MAX_TOKENS_LIMIT)))
            self.request_timeout = int(os.environ.get("REQUEST_TIMEOUT", str(DefaultConfigValues.REQUEST_TIMEOUT)))
            self.num_retries = int(os.environ.get("NUM_RETRIES", str(DefaultConfigValues.NUM_RETRIES)))
            self.health_check_api_timeout = float(os.environ.get("HEALTH_CHECK_API_TIMEOUT", str(DefaultConfigValues.HEALTH_CHECK_API_TIMEOUT)))
            self.allowed_string_formats = DefaultConfigValues.ALLOWED_STRING_FORMATS

# Initialize configuration with proper error handling
try:
    config = ServerConfig()
    print(f"✅ Configuration loaded: BIG_MODEL='{config.big_model}', SMALL_MODEL='{config.small_model}'")
except (ValidationError, ValueError) as e:
    print(f"🔴 Configuration Error: {e}")
    print("Please ensure GEMINI_API_KEY is set and other configuration is valid")
    sys.exit(1)

# LiteLLM Configuration
litellm.set_verbose = False
litellm.drop_params = True
litellm.request_timeout = config.request_timeout
litellm.num_retries = config.num_retries

# Enhanced LiteLLM configuration for better streaming resilience
try:
    # Try to configure LiteLLM for more robust streaming
    import litellm.integrations
    
    # Set additional timeout and retry configurations
    litellm.completion_cost_timeout = 10.0
    
    # Configure more resilient streaming behavior if possible
    if hasattr(litellm, 'stream_timeout'):
        litellm.stream_timeout = config.request_timeout
        
except Exception as config_error:
    logger.debug(f"Could not set advanced LiteLLM configuration: {config_error}")

# Additional safety configuration
try:
    # Attempt to set streaming chunk size limits if supported
    if hasattr(litellm, 'max_chunk_size'):
        litellm.max_chunk_size = 8192  # Prevent oversized malformed chunks
except Exception:
    pass

# Enhanced Model Management
class ModelManager:
    """Centralized model management and validation"""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.base_gemini_models = [
            "gemini-1.5-pro-latest",
            "gemini-1.5-pro-preview-0514",
            "gemini-1.5-flash-latest", 
            "gemini-1.5-flash-preview-0514",
            "gemini-pro",
            "gemini-2.5-pro-preview-05-06",
            "gemini-2.5-flash-preview-04-17",
            "gemini-2.0-flash-exp",
            "gemini-exp-1206"
        ]
        self._gemini_models = set(self.base_gemini_models)
        self._add_env_models()
    
    def _add_env_models(self):
        """Add environment-configured models ensuring no duplicates"""
        for model in [self.config.big_model, self.config.small_model]:
            if model.startswith("gemini") and model not in self._gemini_models:
                self._gemini_models.add(model)
    
    @property
    def gemini_models(self) -> List[str]:
        """Get list of valid Gemini models"""
        return sorted(list(self._gemini_models))
    
    def is_valid_gemini_model(self, model: str) -> bool:
        """Check if model is a valid Gemini model"""
        clean_model = model.replace("gemini/", "")
        return clean_model in self._gemini_models
    
    def validate_and_map_model(self, original_model: str) -> tuple[str, bool]:
        """
        Validate and map model name to Gemini format
        Returns: (mapped_model, was_mapped)
        """
        clean_model = self._clean_model_name(original_model)
        mapped_model = self._map_model_alias(clean_model)
        
        if mapped_model != clean_model:
            return f"gemini/{mapped_model}", True
        elif clean_model in self._gemini_models:
            return f"gemini/{clean_model}", True
        elif not original_model.startswith('gemini/'):
            return f"gemini/{original_model}", False
        else:
            return original_model, False
    
    def _clean_model_name(self, model: str) -> str:
        """Remove provider prefixes from model names"""
        if model.startswith('gemini/'):
            return model[7:]
        elif model.startswith('anthropic/'):
            return model[10:]
        elif model.startswith('openai/'):
            return model[7:]
        return model
    
    def _map_model_alias(self, clean_model: str) -> str:
        """Map model aliases to actual model names"""
        model_lower = clean_model.lower()
        
        if Constants.MODEL_HAIKU in model_lower:
            return self.config.small_model
        elif Constants.MODEL_SONNET in model_lower or Constants.MODEL_OPUS in model_lower:
            return self.config.big_model
        
        return clean_model

# Initialize model manager
model_manager = ModelManager(config)

# Enhanced Logging Configuration
class OptimizedMessageFilter(logging.Filter):
    """Optimized message filter using pre-compiled regex patterns"""
    
    def __init__(self):
        super().__init__()
        blocked_patterns = [
            r"LiteLLM completion\(\)",
            r"HTTP Request:",
            r"selected model name for cost calculation",
            r"utils\.py",
            r"cost_calculator"
        ]
        self.blocked_regex = re.compile('|'.join(blocked_patterns))
    
    def filter(self, record):
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            return not self.blocked_regex.search(record.msg)
        return True

class RobustColorizedFormatter(logging.Formatter):
    """Enhanced formatter with graceful TTY degradation"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_colors = (
            hasattr(sys.stdout, 'isatty') and 
            sys.stdout.isatty() and 
            os.getenv('NO_COLOR') is None
        )
        
        if self.use_colors:
            self.BLUE = "\033[94m"
            self.GREEN = "\033[92m" 
            self.YELLOW = "\033[93m"
            self.RED = "\033[91m"
            self.RESET = "\033[0m"
            self.BOLD = "\033[1m"
        else:
            self.BLUE = self.GREEN = self.YELLOW = ""
            self.RED = self.RESET = self.BOLD = ""

    def format(self, record):
        if record.levelno == logging.DEBUG and "MODEL MAPPING" in record.msg:
            return f"{self.BOLD}{self.GREEN}{record.msg}{self.RESET}"
        return super().format(record)

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level.upper()),
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Configure uvicorn to be quieter
for uvicorn_logger in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
    logging.getLogger(uvicorn_logger).setLevel(logging.WARNING)

# Apply enhanced filters and formatters
root_logger = logging.getLogger()
root_logger.addFilter(OptimizedMessageFilter())

for handler in logger.handlers:
    if isinstance(handler, logging.StreamHandler):
        handler.setFormatter(RobustColorizedFormatter('%(asctime)s - %(levelname)s - %(message)s'))

# Initialize FastAPI app
app = FastAPI(title="Gemini-to-Claude API Proxy", version="2.2.0")

# Enhanced Schema Utilities
class SchemaUtilities:
    """Utilities for handling and cleaning schemas"""
    
    @staticmethod
    def clean_gemini_schema(schema: Any, allowed_formats: Set[str] = None) -> Any:
        """Recursively removes unsupported fields from a JSON schema for Gemini."""
        if allowed_formats is None:
            allowed_formats = config.allowed_string_formats
            
        if isinstance(schema, dict):
            schema.pop("additionalProperties", None)
            schema.pop("default", None)

            # CRITICAL FIX: Check for unsupported 'format' in string types  
            if schema.get("type") == "string" and "format" in schema:
                if schema["format"] not in allowed_formats:
                    logger.debug(f"Removing unsupported format '{schema['format']}' for string type in Gemini schema")
                    schema.pop("format")

            for key, value in list(schema.items()):
                schema[key] = SchemaUtilities.clean_gemini_schema(value, allowed_formats)
                
        elif isinstance(schema, list):
            return [SchemaUtilities.clean_gemini_schema(item, allowed_formats) for item in schema]
            
        return schema

# Enhanced Pydantic Models
class ContentBlockText(BaseModel):
    type: Literal["text"]
    text: str

class ContentBlockImage(BaseModel):
    type: Literal["image"]
    source: Dict[str, Any]

class ContentBlockToolUse(BaseModel):
    type: Literal["tool_use"]
    id: str
    name: str
    input: Dict[str, Any]

class ContentBlockToolResult(BaseModel):
    type: Literal["tool_result"]
    tool_use_id: str
    content: Union[str, List[Dict[str, Any]], Dict[str, Any]]

class SystemContent(BaseModel):
    type: Literal["text"]
    text: str

class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: Union[str, List[Union[ContentBlockText, ContentBlockImage, ContentBlockToolUse, ContentBlockToolResult]]]

class Tool(BaseModel):
    name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any]

class ThinkingConfig(BaseModel):
    enabled: bool = True

# Enhanced Model Validation
class ModelValidator:
    """Centralized model validation logic"""
    
    @staticmethod
    def validate_and_map_model(v: str, info=None) -> str:
        """Reusable model validation logic"""
        original_model = v
        mapped_model, was_mapped = model_manager.validate_and_map_model(v)
        
        logger.debug(f"📋 MODEL VALIDATION: Original='{original_model}', Big='{config.big_model}', Small='{config.small_model}'")
        
        if was_mapped:
            logger.debug(f"📌 MODEL MAPPING: '{original_model}' ➡️ '{mapped_model}'")
        elif not model_manager.is_valid_gemini_model(mapped_model):
            logger.warning(f"⚠️ Model '{original_model}' may not be valid. Using: '{mapped_model}'")
        
        if info and hasattr(info, 'data') and isinstance(info.data, dict):
            info.data['original_model'] = original_model
            
        return mapped_model

class MessagesRequest(BaseModel):
    model: str
    max_tokens: int
    messages: List[Message]
    system: Optional[Union[str, List[SystemContent]]] = None
    stop_sequences: Optional[List[str]] = None
    stream: Optional[bool] = False
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    tools: Optional[List[Tool]] = None
    tool_choice: Optional[Dict[str, Any]] = None
    thinking: Optional[ThinkingConfig] = None
    original_model: Optional[str] = None

    @field_validator('model')
    @classmethod
    def validate_model_field(cls, v, info):
        return ModelValidator.validate_and_map_model(v, info)

class TokenCountRequest(BaseModel):
    model: str
    messages: List[Message]
    system: Optional[Union[str, List[SystemContent]]] = None
    tools: Optional[List[Tool]] = None
    thinking: Optional[ThinkingConfig] = None
    tool_choice: Optional[Dict[str, Any]] = None
    original_model: Optional[str] = None

    @field_validator('model')
    @classmethod
    def validate_model_token_count(cls, v, info):
        return ModelValidator.validate_and_map_model(v, info)

class TokenCountResponse(BaseModel):
    input_tokens: int

class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

class MessagesResponse(BaseModel):
    id: str
    model: str
    role: Literal["assistant"] = Constants.ROLE_ASSISTANT
    content: List[Union[ContentBlockText, ContentBlockToolUse]]
    type: Literal["message"] = "message"
    stop_reason: Optional[Literal["end_turn", "max_tokens", "stop_sequence", "tool_use", "error"]] = None
    stop_sequence: Optional[str] = None
    usage: Usage

# Enhanced Tool Processing with Dispatch Pattern
class ToolProcessor:
    """
    Enhanced tool processing with dispatch pattern for better extensibility
    
    CRITICAL DESIGN NOTE: 
    This processor deliberately does NOT filter out error messages from tool results.
    Error messages like "Error: No such tool available" are important feedback that 
    the LLM needs to see to avoid repeating invalid tool calls. Filtering these 
    messages causes looping behavior where the LLM retries the same mistakes.
    """
    
    # Tool result content parsers using dispatch pattern
    CONTENT_PARSERS: Dict[type, Callable] = {}
    
    @classmethod
    def register_parser(cls, content_type: type):
        """Decorator to register content parsers"""
        def decorator(func):
            cls.CONTENT_PARSERS[content_type] = func
            return func
        return decorator
    
    @classmethod
    def parse_tool_result_content(cls, content) -> Optional[str]:
        """Enhanced tool result parsing using dispatch pattern"""
        if content is None:
            return "No content provided"
        
        # Use dispatch pattern for type-specific parsing
        content_type = type(content)
        if content_type in cls.CONTENT_PARSERS:
            return cls.CONTENT_PARSERS[content_type](content)
        
        # Fallback for unknown types
        try:
            str_content = str(content)
            return str_content  # CHANGED: No longer filter error content
        except Exception:
            return "Unparseable content"
    @staticmethod
    def validate_tool_call(tool_call: Dict[str, Any]) -> bool:
        """Validate tool call has required fields"""
        return bool(tool_call.get("name", "").strip())
    
    @staticmethod
    def validate_tool_result(tool_use_id: str, active_tool_calls: Set[str]) -> bool:
        """Validate tool result corresponds to an active tool call"""
        # CRITICAL FIX: More lenient validation - allow tool results even if tool_use_id tracking is imperfect
        # This prevents dropping valid error messages that the LLM needs to see
        if not tool_use_id or not tool_use_id.strip():
            logger.warning("Tool result has empty tool_use_id")
            return False
        
        if tool_use_id not in active_tool_calls:
            logger.info(f"Tool result for '{tool_use_id}' not in active tracking - may be valid error response")
            # CHANGED: Don't strictly reject - error messages from tools are important
            return True
        
        return True

# Register content parsers using dispatch pattern - FIXED: No longer filter error messages
@ToolProcessor.register_parser(str)
def parse_string_content(content: str) -> Optional[str]:
    """Parse string content - CRITICAL FIX: Always return content, don't filter errors"""
    # REMOVED: Error filtering that was causing looping behavior
    # The LLM needs to see error messages to avoid repeating invalid tool calls
    return content

@ToolProcessor.register_parser(list)
def parse_list_content(content: list) -> Optional[str]:
    """Parse list content"""
    result_parts = []
    for item in content:
        parsed_item = _parse_list_item(item)
        if parsed_item:
            result_parts.append(parsed_item)
    
    final_result = "\n".join(result_parts).strip()
    return final_result if final_result else None

@ToolProcessor.register_parser(dict)
def parse_dict_content(content: dict) -> Optional[str]:
    """Parse dictionary content - CRITICAL FIX: Always return content, don't filter errors"""
    if content.get("type") == Constants.CONTENT_TEXT:
        text_content = content.get("text", "")
        # REMOVED: Error filtering - return all text content including errors
        return text_content
    try:
        return json.dumps(content)
    except (TypeError, ValueError):
        return str(content)

def _parse_list_item(item) -> Optional[str]:
    """Helper to parse individual list items - CRITICAL FIX: Don't filter error messages"""
    if isinstance(item, dict) and item.get("type") == Constants.CONTENT_TEXT:
        text_content = item.get("text", "")
        # REMOVED: Error filtering - return all text content
        return text_content
    elif isinstance(item, str):
        # REMOVED: Error filtering - return all strings including error messages
        return item
    elif isinstance(item, dict):
        if "text" in item:
            text_content = item.get("text", "")
            # REMOVED: Error filtering - return all text content
            return text_content
        else:
            try:
                return json.dumps(item)
            except (TypeError, ValueError):
                return str(item)
    else:
        try:
            return str(item)
        except Exception:
            return "Unparseable content"
    return None

# Refactored Message Conversion with Smaller Helper Functions
class MessageConverter:
    """Enhanced message conversion with focused helper methods"""
    
    @staticmethod
    def process_system_message(system_content) -> Optional[Dict[str, Any]]:
        """Process system message content into LiteLLM format"""
        if not system_content:
            return None
            
        system_text = MessageConverter._extract_system_text(system_content)
        return {"role": Constants.ROLE_SYSTEM, "content": system_text.strip()} if system_text.strip() else None
    
    @staticmethod
    def _extract_system_text(system_content) -> str:
        """Extract text from system content"""
        if isinstance(system_content, str):
            return system_content
        elif isinstance(system_content, list):
            text_parts = []
            for block in system_content:
                text_part = MessageConverter._extract_block_text(block)
                if text_part:
                    text_parts.append(text_part)
            return "\n\n".join(text_parts)
        return ""
    
    @staticmethod
    def _extract_block_text(block) -> str:
        """Extract text from a content block"""
        if hasattr(block, 'type') and block.type == Constants.CONTENT_TEXT:
            return block.text
        elif isinstance(block, dict) and block.get("type") == Constants.CONTENT_TEXT:
            return block.get("text", "")
        return ""
    
    @staticmethod
    def process_content_blocks(content_blocks, role: str, active_tool_calls: Set[str]) -> List[Dict[str, Any]]:
        """
        Process content blocks with focused helper methods.
        
        AGGREGATION STRATEGY EXPLANATION:
        This method handles the complex conversion between Anthropic's message structure 
        and LiteLLM's expected format, particularly for tool interactions:
        
        1. ACCUMULATION PHASE: We accumulate text_parts, image_parts, tool_calls, and 
           pending_tool_messages as we process each content block in sequence.
        
        2. TOOL_RESULT SPLITTING: When we encounter a tool_result block in a user message,
           any preceding text/image content from the same Anthropic message must be sent 
           as a separate LiteLLM user message BEFORE the tool result message. This is 
           because LiteLLM expects tool results to be separate "tool" role messages.
        
        3. MESSAGE FINALIZATION: After processing all blocks, we finalize any remaining
           accumulated content into properly formatted LiteLLM messages.
        
        Example: Anthropic user message with [text, tool_result] becomes:
        - LiteLLM user message with text content
        - LiteLLM tool message with result content
        """
        messages = []
        text_parts = []
        image_parts = []
        tool_calls = []
        pending_tool_messages = []
        
        for block in content_blocks:
            MessageConverter._process_single_block(
                block, role, active_tool_calls, 
                text_parts, image_parts, tool_calls, 
                pending_tool_messages, messages
            )
        
        # Finalize remaining content
        MessageConverter._finalize_message_content(
            role, text_parts, image_parts, tool_calls, 
            pending_tool_messages, messages
        )
        
        return messages
    
    @staticmethod
    def _process_single_block(block, role: str, active_tool_calls: Set[str], 
                             text_parts: List[str], image_parts: List[Dict[str, Any]], 
                             tool_calls: List[Dict[str, Any]], pending_tool_messages: List[Dict[str, Any]], 
                             messages: List[Dict[str, Any]]):
        """Process a single content block"""
        if block.type == Constants.CONTENT_TEXT:
            text_parts.append(block.text)
        elif block.type == Constants.CONTENT_IMAGE:
            image_part = MessageConverter._process_image_block(block)
            if image_part:
                image_parts.append(image_part)
        elif block.type == Constants.CONTENT_TOOL_USE and role == Constants.ROLE_ASSISTANT:
            MessageConverter._process_tool_use_block(block, active_tool_calls, tool_calls)
        elif block.type == Constants.CONTENT_TOOL_RESULT and role == Constants.ROLE_USER:
            MessageConverter._process_tool_result_block(
                block, text_parts, image_parts, active_tool_calls, 
                pending_tool_messages, messages
            )
    
    @staticmethod
    def _process_tool_use_block(block, active_tool_calls: Set[str], tool_calls: List[Dict[str, Any]]):
        """Process tool use block"""
        if ToolProcessor.validate_tool_call({"name": block.name}):
            tool_calls.append({
                "id": block.id,
                "type": Constants.TOOL_FUNCTION,
                Constants.TOOL_FUNCTION: {
                    "name": block.name,
                    "arguments": json.dumps(block.input)
                }
            })
            active_tool_calls.add(block.id)
    
    @staticmethod
    def _process_tool_result_block(block, text_parts: List[str], image_parts: List[Dict[str, Any]], 
                                  active_tool_calls: Set[str], pending_tool_messages: List[Dict[str, Any]], 
                                  messages: List[Dict[str, Any]]):
        """Process tool result block - CRITICAL FIX: Always process tool results, including errors"""
        parsed_content = ToolProcessor.parse_tool_result_content(block.content)
        
        # CRITICAL FIX: More lenient validation - always process tool results
        # Error messages from tools are crucial feedback for the LLM
        if parsed_content is None:
            logger.warning(f"Tool result content is None for tool_use_id: {block.tool_use_id}")
            parsed_content = "Tool result processing failed"
        
        # CHANGED: Less strict validation - allow tool results even if tracking is imperfect
        if not ToolProcessor.validate_tool_result(block.tool_use_id, active_tool_calls):
            logger.info(f"Tool result validation warning for tool_use_id: {block.tool_use_id} - processing anyway")
            # Continue processing instead of skipping
        
        # Add user message for accumulated content if any
        if text_parts or image_parts:
            user_message = MessageConverter._create_user_message(text_parts, image_parts)
            messages.append(user_message)
            text_parts.clear()
            image_parts.clear()
        
        # Always add tool message - even error responses are important
        pending_tool_messages.append({
            "role": Constants.ROLE_TOOL,
            "tool_call_id": block.tool_use_id,
            "content": parsed_content
        })
        
        # Remove from active tracking if it was there
        active_tool_calls.discard(block.tool_use_id)
    
    @staticmethod
    def _finalize_message_content(role: str, text_parts: List[str], image_parts: List[Dict[str, Any]], 
                                 tool_calls: List[Dict[str, Any]], pending_tool_messages: List[Dict[str, Any]], 
                                 messages: List[Dict[str, Any]]):
        """Finalize remaining message content"""
        if role == Constants.ROLE_USER:
            if text_parts or image_parts:
                messages.append(MessageConverter._create_user_message(text_parts, image_parts))
            messages.extend(pending_tool_messages)
        elif role == Constants.ROLE_ASSISTANT:
            assistant_msg = MessageConverter._create_assistant_message(text_parts, image_parts, tool_calls)
            if assistant_msg:
                messages.append(assistant_msg)
    
    @staticmethod
    def _process_image_block(block) -> Optional[Dict[str, Any]]:
        """Process image block into LiteLLM format"""
        if (isinstance(block.source, dict) and 
            block.source.get("type") == "base64" and
            "media_type" in block.source and "data" in block.source):
            return {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{block.source['media_type']};base64,{block.source['data']}"
                }
            }
        else:
            logger.warning(f"Unsupported image block source format: {block.source}")
            return None
    
    @staticmethod
    def _create_user_message(text_parts: List[str], image_parts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create user message from text and image parts"""
        content_parts = []
        
        text_content = "".join(text_parts).strip()
        if text_content:
            content_parts.append({"type": Constants.CONTENT_TEXT, "text": text_content})
        content_parts.extend(image_parts)
        
        return {
            "role": Constants.ROLE_USER,
            "content": content_parts[0]["text"] if len(content_parts) == 1 and content_parts[0]["type"] == Constants.CONTENT_TEXT else content_parts
        }
    
    @staticmethod 
    def _create_assistant_message(text_parts: List[str], image_parts: List[Dict[str, Any]], 
                                 tool_calls: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Create assistant message from content parts and tool calls"""
        content_parts = []
        text_content = "".join(text_parts).strip()
        
        if text_content:
            content_parts.append({"type": Constants.CONTENT_TEXT, "text": text_content})
        content_parts.extend(image_parts)
        
        message = {"role": Constants.ROLE_ASSISTANT}
        
        if content_parts:
            message["content"] = content_parts[0]["text"] if len(content_parts) == 1 and content_parts[0]["type"] == Constants.CONTENT_TEXT else content_parts
        else:
            message["content"] = None
            
        if tool_calls:
            message["tool_calls"] = tool_calls
            
        return message if message.get("content") or message.get("tool_calls") else None

# Refactored convert_anthropic_to_litellm function
class RequestConverter:
    """Handles conversion from Anthropic to LiteLLM format"""
    
    @staticmethod
    def convert_anthropic_to_litellm(anthropic_request: MessagesRequest) -> Dict[str, Any]:
        """Main conversion method broken into focused helpers"""
        litellm_messages = []
        
        # Process system message
        system_msg = MessageConverter.process_system_message(anthropic_request.system)
        if system_msg:
            litellm_messages.append(system_msg)
        
        # Process regular messages
        active_tool_calls = set()
        RequestConverter._process_regular_messages(anthropic_request.messages, litellm_messages, active_tool_calls)
        
        # Build base request
        litellm_request = RequestConverter._build_base_request(anthropic_request, litellm_messages)
        
        # Add optional parameters
        RequestConverter._add_optional_parameters(anthropic_request, litellm_request)
        
        # Process tools and tool choice
        RequestConverter._process_tools(anthropic_request, litellm_request)
        RequestConverter._process_tool_choice(anthropic_request, litellm_request)
        
        # Process thinking and metadata
        RequestConverter._process_thinking_config(anthropic_request, litellm_request)
        RequestConverter._process_user_metadata(anthropic_request, litellm_request)
        
        return litellm_request
    
    @staticmethod
    def _process_regular_messages(messages: List[Message], litellm_messages: List[Dict[str, Any]], 
                                 active_tool_calls: Set[str]):
        """Process regular messages"""
        for msg in messages:
            if isinstance(msg.content, str):
                litellm_messages.append({"role": msg.role, "content": msg.content})
            else:
                converted_messages = MessageConverter.process_content_blocks(
                    msg.content, msg.role, active_tool_calls
                )
                litellm_messages.extend(converted_messages)
    
    @staticmethod
    def _build_base_request(anthropic_request: MessagesRequest, litellm_messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build base LiteLLM request"""
        return {
            "model": anthropic_request.model,
            "messages": litellm_messages,
            "max_tokens": min(anthropic_request.max_tokens, config.max_tokens_limit),
            "temperature": anthropic_request.temperature,
            "stream": anthropic_request.stream,
        }
    
    @staticmethod
    def _add_optional_parameters(anthropic_request: MessagesRequest, litellm_request: Dict[str, Any]):
        """Add optional parameters to request"""
        if anthropic_request.stop_sequences:
            litellm_request["stop"] = anthropic_request.stop_sequences
        if anthropic_request.top_p is not None:
            litellm_request["top_p"] = anthropic_request.top_p
        if anthropic_request.top_k is not None:
            litellm_request["topK"] = anthropic_request.top_k
    
    @staticmethod
    def _process_tools(anthropic_request: MessagesRequest, litellm_request: Dict[str, Any]):
        """Process tools for the request with enhanced validation"""
        if anthropic_request.tools:
            valid_tools = []
            for tool in anthropic_request.tools:
                if ToolProcessor.validate_tool_call({"name": tool.name}):
                    # Clean the schema (fixed method call)
                    cleaned_schema = SchemaUtilities.clean_gemini_schema(tool.input_schema)
                    valid_tools.append({
                        "type": Constants.TOOL_FUNCTION,
                        Constants.TOOL_FUNCTION: {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": cleaned_schema
                        }
                    })
                else:
                    logger.warning(f"Skipping tool with invalid name: {tool.name}")
            
            if valid_tools:
                litellm_request["tools"] = valid_tools
                logger.debug(f"Added {len(valid_tools)} valid tools to request")
    
    @staticmethod
    def _process_tool_choice(anthropic_request: MessagesRequest, litellm_request: Dict[str, Any]):
        """Process tool choice configuration"""
        if anthropic_request.tool_choice:
            choice_type = anthropic_request.tool_choice.get("type")
            if choice_type == Constants.TOOL_CHOICE_AUTO:
                litellm_request["tool_choice"] = Constants.TOOL_CHOICE_AUTO
            elif choice_type == Constants.TOOL_CHOICE_ANY:
                litellm_request["tool_choice"] = Constants.TOOL_CHOICE_ANY
            elif choice_type == Constants.TOOL_CHOICE_TOOL and "name" in anthropic_request.tool_choice:
                litellm_request["tool_choice"] = {
                    "type": Constants.TOOL_FUNCTION, 
                    Constants.TOOL_FUNCTION: {"name": anthropic_request.tool_choice["name"]}
                }
            else:
                litellm_request["tool_choice"] = Constants.TOOL_CHOICE_AUTO
    
    @staticmethod
    def _process_thinking_config(anthropic_request: MessagesRequest, litellm_request: Dict[str, Any]):
        """Process thinking configuration"""
        if anthropic_request.thinking is not None:
            if anthropic_request.thinking.enabled:
                litellm_request["thinkingConfig"] = {"thinkingBudget": 24576}
            else:
                litellm_request["thinkingConfig"] = {"thinkingBudget": 0}
    
    @staticmethod
    def _process_user_metadata(anthropic_request: MessagesRequest, litellm_request: Dict[str, Any]):
        """Process user metadata"""
        if (anthropic_request.metadata and 
            "user_id" in anthropic_request.metadata and
            isinstance(anthropic_request.metadata["user_id"], str)):
            litellm_request["user"] = anthropic_request.metadata["user_id"]

# Main conversion function (kept for compatibility)
def convert_anthropic_to_litellm(anthropic_request: MessagesRequest) -> Dict[str, Any]:
    """Convert Anthropic request to LiteLLM format"""
    return RequestConverter.convert_anthropic_to_litellm(anthropic_request)

# Enhanced Error Handling with Better Client Formatting
class EnhancedErrorHandler:
    """Enhanced error handling with better client-facing error messages"""
    
    @staticmethod
    def handle_litellm_error(e) -> HTTPException:
        """Enhanced LiteLLM error handling with detailed formatting"""
        error_details = EnhancedErrorHandler._extract_error_details(e)
        client_message = EnhancedErrorHandler._format_client_error_message(error_details)
        
        logger.error(f"LiteLLM Error: {error_details}")
        
        return HTTPException(
            status_code=error_details.get("status_code", 500),
            detail=client_message
        )
    
    @staticmethod
    def _interpret_tool_schema_error(error_msg: str) -> Optional[str]:
        """
        Interprets common tool schema validation errors from Gemini.
        Returns a user-friendly message if a known pattern is matched, otherwise None.
        """
        # Ensure error_msg is a string and convert to lower case for robust matching
        # Original error messages can vary slightly in casing or might not always be strings.
        processed_error_msg = str(error_msg).lower()
        
        if "function_declarations" in processed_error_msg and "format" in processed_error_msg:
            # Check for the specific Gemini error message about supported formats
            if "only 'enum' and 'date-time' are supported" in processed_error_msg:
                return "Tool schema error: Gemini only supports 'enum' and 'date-time' formats for string parameters. Remove or change other format types (like 'url', 'email', 'uri', etc.)."
            else:
                # General tool schema format error
                return "Tool schema validation error. Check your tool parameter definitions for unsupported format types or properties."
        return None

    @staticmethod
    def format_streaming_error_text(original_error_message: str) -> str:
        """
        Enhanced streaming error message formatting with additional Gemini-specific patterns.
        """
        error_msg = str(original_error_message).strip()
        
        # Gemini-specific streaming issues (highest priority)
        if "RuntimeError: Error parsing chunk" in error_msg and "Expecting property name" in error_msg:
            return "Gemini's streaming API sent incomplete data. This is a known temporary issue - please try again."
        elif "Error parsing chunk" in error_msg and "Expecting property name" in error_msg:
            return "Gemini's streaming API sent malformed JSON. This is a temporary server-side issue - please try again."
        elif "Expecting property name enclosed in double quotes" in error_msg:
            return "Gemini's streaming API sent malformed data. This is a temporary server-side issue - please try again."
        elif "Received chunk: {" in error_msg or "Received chunk: }" in error_msg:
            return "Gemini sent incomplete JSON chunks. This is a known API issue that usually resolves on retry."
        
        # Tool schema validation errors
        elif (schema_error_message := EnhancedErrorHandler._interpret_tool_schema_error(error_msg)):
            return schema_error_message
        
        # JSON parsing errors (general)
        elif "json.decoder.JSONDecodeError" in error_msg:
            return "JSON parsing error in stream. This is often a temporary Gemini API issue - please retry your request."
        elif any(keyword in error_msg.lower() for keyword in ["json", "parsing"]):
            return "Data parsing error. This may be a temporary API issue - please try again."
        
        # Connection and API errors
        elif "APIConnectionError" in error_msg and "parsing" in error_msg.lower():
            return "Connection error with malformed response data. Please try again."
        elif "APIConnectionError" in error_msg:
            return "Connection error during streaming. Please check your request and try again."
        elif "RuntimeError" in error_msg and "chunk" in error_msg.lower():
            return "Streaming data processing error. This is likely a temporary API issue - please retry."
        
        # Request validation errors
        elif "BadRequestError" in error_msg:
            return "Request validation error - please check your parameters and tool definitions"
        
        # Connection errors (general)
        elif "connection" in error_msg.lower():
            return "Connection error - please check your request and try again"
        
        # Default fallback
        else:
            return "Streaming error occurred. This may be a temporary API issue - please try again."
    
    @staticmethod
    def _extract_error_details(e) -> Dict[str, Any]:
        """Extract detailed error information from LiteLLM exception"""
        details = {
            "error_type": type(e).__name__,
            "status_code": getattr(e, 'status_code', 500),
            "provider": getattr(e, 'llm_provider', 'unknown'),
            "model": getattr(e, 'model', 'unknown'),
            "raw_message": str(getattr(e, 'message', e))
        }
        
        # Try to parse structured error from response
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            try:
                response_data = json.loads(e.response.text)
                details["structured_error"] = response_data
                
                # Extract specific error information
                if "error" in response_data:
                    error_obj = response_data["error"]
                    details["error_code"] = error_obj.get("code")
                    details["error_message"] = error_obj.get("message", "")
                    details["error_status"] = error_obj.get("status", "")
                    
                    # Extract quota information for rate limit errors
                    if "details" in error_obj:
                        details["quota_info"] = EnhancedErrorHandler._extract_quota_info(error_obj["details"])
                        details["retry_info"] = EnhancedErrorHandler._extract_retry_info(error_obj["details"])
                        details["help_links"] = EnhancedErrorHandler._extract_help_links(error_obj["details"])
                        
            except (json.JSONDecodeError, KeyError) as parse_error:
                details["parse_error"] = str(parse_error)
                details["raw_response"] = e.response.text[:500]  # Truncate for safety
        
        return details
    
    @staticmethod
    def _extract_quota_info(details: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Extract quota information from error details"""
        for detail in details:
            if detail.get("@type") == "type.googleapis.com/google.rpc.QuotaFailure":
                violations = detail.get("violations", [])
                if violations:
                    violation = violations[0]  # Take first violation
                    return {
                        "metric": violation.get("quotaMetric", ""),
                        "quota_id": violation.get("quotaId", ""),
                        "dimensions": violation.get("quotaDimensions", {}),
                        "quota_value": violation.get("quotaValue", "")
                    }
        return None
    
    @staticmethod
    def _extract_retry_info(details: List[Dict[str, Any]]) -> Optional[str]:
        """Extract retry delay information"""
        for detail in details:
            if detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                return detail.get("retryDelay", "")
        return None
    
    @staticmethod
    def _extract_help_links(details: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Extract help links from error details"""
        for detail in details:
            if detail.get("@type") == "type.googleapis.com/google.rpc.Help":
                return detail.get("links", [])
        return []
    
    @staticmethod
    def _format_client_error_message(details: Dict[str, Any]) -> str:
        """Format user-friendly error message for client"""
        status_code = details.get("status_code", 500)
        error_message = details.get("error_message", "")
        provider = details.get("provider", "unknown")
        model = details.get("model", "unknown")
        
        # Handle specific error types with helpful messages
        if status_code == 429:  # Rate limit
            return EnhancedErrorHandler._format_rate_limit_error(details)
        elif status_code == 500:  # Internal server error
            return EnhancedErrorHandler._format_internal_error(details)
        elif status_code == 400:  # Bad request
            return EnhancedErrorHandler._format_bad_request_error(details)
        elif status_code == 401 or status_code == 403:  # Auth errors
            return EnhancedErrorHandler._format_auth_error(details)
        else:
            # Generic error formatting
            return f"API Error ({provider}/{model}): {error_message or 'Unknown error occurred'}"
    
    @staticmethod
    def _format_rate_limit_error(details: Dict[str, Any]) -> str:
        """Format rate limit error with quota details"""
        base_msg = f"Rate limit exceeded for {details.get('model', 'unknown model')}"
        
        quota_info = details.get("quota_info")
        if quota_info:
            quota_id = quota_info.get("quota_id", "")
            quota_value = quota_info.get("quota_value", "")
            
            if "TokensPerMinute" in quota_id:
                base_msg += f". Token limit: {quota_value} tokens/minute"
            elif "RequestsPerMinute" in quota_id:
                base_msg += f". Request limit: {quota_value} requests/minute"
            else:
                base_msg += f". Quota: {quota_value}"
        
        retry_delay = details.get("retry_info")
        if retry_delay:
            base_msg += f". Retry after: {retry_delay}"
        
        help_links = details.get("help_links", [])
        if help_links:
            base_msg += f". More info: {help_links[0].get('url', '')}"
        
        return base_msg
    
    @staticmethod
    def _format_internal_error(details: Dict[str, Any]) -> str:
        """Format internal server error"""
        error_message = details.get("error_message", "")
        
        if "internal error" in error_message.lower():
            return "Gemini API is experiencing internal issues. Please retry in a few moments."
        elif "retry" in error_message.lower():
            return f"Temporary service issue: {error_message}"
        else:
            return f"Internal service error: {error_message or 'Please try again later'}"
    
    @staticmethod
    def _format_bad_request_error(details: Dict[str, Any]) -> str:
        """Format bad request error with specific tool schema guidance"""
        error_message = details.get("error_message", "")
        
        # Enhanced tool schema error handling
        schema_error_message = EnhancedErrorHandler._interpret_tool_schema_error(error_message)
        if schema_error_message:
            return schema_error_message
        elif "function_declarations" in error_message:
            return "Tool definition error. Please verify your tool schemas are valid and supported by Gemini."
        elif "tool call" in error_message.lower():
            return "Tool call validation error. Ensure tool calls match available tools."
        elif "token" in error_message.lower():
            return f"Input validation error: {error_message}"
        else:
            return f"Request validation error: {error_message or 'Please check your request parameters'}"
    
    @staticmethod
    def _format_auth_error(details: Dict[str, Any]) -> str:
        """Format authentication/authorization error"""
        status_code = details.get("status_code")
        
        if status_code == 401:
            return "Authentication failed. Please check your API key."
        elif status_code == 403:
            return "Access denied. Your API key may not have permission for this resource."
        else:
            return "Authentication error. Please verify your credentials."
    
    @staticmethod
    def handle_general_error(e) -> HTTPException:
        """Handle general errors with safe client messages"""
        error_type = type(e).__name__
        status_code = getattr(e, 'status_code', 500)
        
        # Log full details internally
        logger.error(f"General error ({error_type}): {str(e)}")
        
        # Safe client message
        if status_code >= 500:
            client_message = "Internal server error. Please try again later."
        else:
            client_message = "Request processing error. Please check your input and try again."
        
        raise HTTPException(status_code=status_code, detail=client_message)

# Enhanced Streaming Handler with Better Error Recovery

# Enhanced Streaming Handler with Better Error Recovery
class StreamingHandler:
    """Enhanced streaming with better structure and error handling"""
    
    def __init__(self, original_request: MessagesRequest):
        self.original_request = original_request
        self.message_id = f"msg_{uuid.uuid4().hex[:24]}"
        self.accumulated_text = ""
        self.text_block_index = 0
        self.tool_block_counter = 0
        self.current_tool_calls = {}
        self.input_tokens = 0
        self.output_tokens = 0
        self.final_stop_reason = Constants.STOP_END_TURN
    
    async def handle_streaming(self, response_generator):
        """Main streaming handler with comprehensive error handling for LiteLLM issues"""
        try:
            # Send initial events
            yield self._create_message_start_event()
            yield self._create_content_block_start_event()
            yield self._create_ping_event()
            
            stream_completed = False
            chunk_count = 0
            consecutive_errors = 0
            max_consecutive_errors = 5  # Prevent infinite error loops
            
            async for chunk in response_generator:
                try:
                    chunk_count += 1
                    consecutive_errors = 0  # Reset on successful processing
                    
                    processed_events = self._process_chunk(chunk)
                    for event in processed_events:
                        yield event
                        
                    # Check if stream is complete
                    if self._is_stream_complete(chunk):
                        stream_completed = True
                        for event in self._finalize_stream():
                            yield event
                        return
                        
                except Exception as e:
                    consecutive_errors += 1
                    
                    # Different log levels based on error type
                    if self._is_expected_gemini_error(e):
                        logger.debug(f"Expected Gemini streaming issue (chunk {chunk_count}): {e}")
                    else:
                        logger.warning(f"Error processing stream chunk {chunk_count}: {e}")
                    
                    # If too many consecutive errors, abort to prevent infinite loops
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(f"Too many consecutive streaming errors ({consecutive_errors}), aborting stream")
                        break
                    
                    continue
            
            # Fallback finalization if stream didn't complete normally
            if not stream_completed:
                logger.debug("Stream ended without explicit completion, finalizing...")
                for event in self._finalize_stream():
                    yield event
                    
        except Exception as e:
            # Classify error for appropriate logging level
            if self._is_expected_gemini_error(e):
                logger.info(f"Expected Gemini streaming error (will send graceful response): {type(e).__name__}")
                logger.debug(f"Full Gemini error details: {e}")
            else:
                logger.error(f"Unexpected streaming error: {e}")
            
            # Use centralized error message formatting
            safe_error = EnhancedErrorHandler.format_streaming_error_text(str(e))
            
            # Send error response in Anthropic format
            error_event = self._create_error_event(safe_error)
            yield error_event
            
            # Try to finalize cleanly
            try:
                for event in self._finalize_stream():
                    yield event
            except Exception as finalize_error:
                logger.error(f"Error during finalization: {finalize_error}")
                yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
    
    def _is_expected_gemini_error(self, error) -> bool:
        """Check if this is an expected Gemini API streaming issue"""
        error_str = str(error)
        expected_patterns = [
            "Error parsing chunk",
            "Expecting property name enclosed in double quotes",
            "json.decoder.JSONDecodeError",
            "RuntimeError: Error parsing chunk",
            "Received chunk: {",
            "Received chunk: }",
            "APIConnectionError"
        ]
        return any(pattern in error_str for pattern in expected_patterns)
    
    def _create_message_start_event(self) -> str:
        """Create message start event"""
        data = {
            'type': Constants.EVENT_MESSAGE_START,
            'message': {
                'id': self.message_id,
                'type': 'message',
                'role': Constants.ROLE_ASSISTANT,
                'model': self.original_request.original_model or self.original_request.model,
                'content': [],
                'stop_reason': None,
                'stop_sequence': None,
                'usage': {'input_tokens': 0, 'output_tokens': 0}
            }
        }
        return f"event: {Constants.EVENT_MESSAGE_START}\ndata: {json.dumps(data)}\n\n"
    
    def _create_content_block_start_event(self) -> str:
        """Create content block start event"""
        data = {
            'type': Constants.EVENT_CONTENT_BLOCK_START,
            'index': 0,
            'content_block': {'type': Constants.CONTENT_TEXT, 'text': ''}
        }
        return f"event: {Constants.EVENT_CONTENT_BLOCK_START}\ndata: {json.dumps(data)}\n\n"
    
    def _create_ping_event(self) -> str:
        """Create ping event"""
        return f"event: {Constants.EVENT_PING}\ndata: {json.dumps({'type': Constants.EVENT_PING})}\n\n"
    
    def _create_error_event(self, error_message: str) -> str:
        """Create error event for streaming failures"""
        # Use centralized error message formatting
        safe_error = EnhancedErrorHandler.format_streaming_error_text(error_message)
        
        data = {
            'type': Constants.EVENT_CONTENT_BLOCK_DELTA,
            'index': self.text_block_index,
            'delta': {'type': Constants.DELTA_TEXT, 'text': f"\n[{safe_error}]\n"}
        }
        return f"event: {Constants.EVENT_CONTENT_BLOCK_DELTA}\ndata: {json.dumps(data)}\n\n"
    
    def _process_chunk(self, chunk) -> List[str]:
        """Process individual chunk with comprehensive error handling for malformed JSON"""
        events = []
        
        # Handle string chunks with enhanced validation
        if isinstance(chunk, str):
            if chunk.strip() == "[DONE]":
                return events
            
            # Enhanced validation for malformed JSON chunks
            chunk = chunk.strip()
            if not chunk:
                logger.debug("Received empty chunk, skipping")
                return events
            
            # Check for common malformed JSON patterns that cause crashes
            malformed_patterns = ["{", "}", '{"', '"}', "{}", '{"error"', "}}", '""', "null"]
            if chunk in malformed_patterns:
                logger.warning(f"Received malformed JSON chunk: '{chunk}', skipping gracefully")
                return events
            
            # Additional check for incomplete JSON objects
            if chunk.startswith("{") and not chunk.endswith("}"):
                logger.warning(f"Received incomplete JSON chunk: '{chunk[:50]}...', skipping")
                return events
            
            # Try to parse JSON with enhanced error handling
            try:
                # Pre-validate JSON structure
                if not self._is_valid_json_structure(chunk):
                    logger.warning(f"Invalid JSON structure detected, skipping chunk")
                    return events
                    
                chunk = json.loads(chunk)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON decode error for chunk: {chunk[:100]}... Error: {e}")
                # Don't fail the entire stream for one bad chunk - this is key for resilience
                return events
            except Exception as e:
                logger.warning(f"Unexpected error parsing chunk: {e}")
                return events
        
        # Validate chunk structure before processing
        if not self._validate_chunk_structure(chunk):
            logger.warning(f"Invalid chunk structure received, skipping: {type(chunk)}")
            return events
        
        # Extract and process chunk data
        try:
            chunk_data = self._extract_chunk_data(chunk)
            events.extend(self._process_chunk_data(chunk_data))
        except Exception as e:
            logger.warning(f"Error processing chunk data: {e}")
            # Continue stream processing even if this chunk fails
        
        return events
    
    def _is_valid_json_structure(self, json_str: str) -> bool:
        """Pre-validate JSON structure to avoid parser crashes"""
        if not json_str or len(json_str) < 2:
            return False
        
        # Basic structure checks
        if json_str.startswith("{") and not json_str.endswith("}"):
            return False
        if json_str.startswith("[") and not json_str.endswith("]"):
            return False
        
        # Check for obvious malformed patterns
        if json_str.count("{") != json_str.count("}"):
            return False
        if json_str.count("[") != json_str.count("]"):
            return False
            
        return True
    
    def _validate_chunk_structure(self, chunk) -> bool:
        """Validate that chunk has expected structure"""
        if chunk is None:
            return False
        
        # Check if it's a valid chunk object or dict
        if hasattr(chunk, 'choices') or isinstance(chunk, dict):
            return True
        
        # Log unexpected chunk types for debugging
        logger.debug(f"Unexpected chunk type: {type(chunk)}")
        return False
    
    def _extract_chunk_data(self, chunk) -> Dict[str, Any]:
        """Extract data from chunk safely"""
        data = {
            "text_delta": None,
            "tool_calls": None,
            "finish_reason": None,
            "usage": None
        }
        
        try:
            if hasattr(chunk, 'choices') and chunk.choices:
                choice = chunk.choices[0]
                if hasattr(choice, 'delta') and choice.delta:
                    delta = choice.delta
                    data["text_delta"] = getattr(delta, 'content', None)
                    if hasattr(delta, 'tool_calls'):
                        data["tool_calls"] = delta.tool_calls
                data["finish_reason"] = getattr(choice, 'finish_reason', None)
            
            if hasattr(chunk, 'usage'):
                data["usage"] = {
                    "prompt_tokens": getattr(chunk.usage, 'prompt_tokens', 0),
                    "completion_tokens": getattr(chunk.usage, 'completion_tokens', 0)
                }
        except Exception as e:
            logger.warning(f"Error extracting chunk data: {e}")
        
        return data
    
    def _process_chunk_data(self, chunk_data: Dict[str, Any]) -> List[str]:
        """Process extracted chunk data"""
        events = []
        
        # Process text delta
        if chunk_data["text_delta"]:
            events.append(self._create_text_delta_event(chunk_data["text_delta"]))
        
        # Process tool call deltas
        if chunk_data["tool_calls"]:
            tool_events = self._process_tool_call_deltas(chunk_data["tool_calls"])
            events.extend(tool_events)
        
        # Update usage and finish reason
        if chunk_data["usage"]:
            self.input_tokens = chunk_data["usage"].get("prompt_tokens", 0)
            self.output_tokens = chunk_data["usage"].get("completion_tokens", 0)
        
        if chunk_data["finish_reason"]:
            self.final_stop_reason = self._map_finish_reason(chunk_data["finish_reason"])
        
        return events
    
    def _create_text_delta_event(self, text_delta: str) -> str:
        """Create text delta event"""
        self.accumulated_text += text_delta
        data = {
            'type': Constants.EVENT_CONTENT_BLOCK_DELTA,
            'index': self.text_block_index,
            'delta': {'type': Constants.DELTA_TEXT, 'text': text_delta}
        }
        return f"event: {Constants.EVENT_CONTENT_BLOCK_DELTA}\ndata: {json.dumps(data)}\n\n"
    
    def _process_tool_call_deltas(self, tool_calls) -> List[str]:
        """Process tool call deltas with focused helpers"""
        events = []
        
        for tc_chunk in tool_calls:
            if not self._validate_tool_chunk(tc_chunk):
                continue
            
            tool_call_id = tc_chunk.id
            
            # Handle new tool call
            if tool_call_id not in self.current_tool_calls:
                events.extend(self._start_new_tool_call(tc_chunk))
            
            # Handle tool call arguments
            if tc_chunk.function.arguments:
                events.append(self._create_tool_argument_delta(tool_call_id, tc_chunk.function.arguments))
        
        return events
    
    def _validate_tool_chunk(self, tc_chunk) -> bool:
        """Validate tool call chunk"""
        return (hasattr(tc_chunk, 'function') and 
                tc_chunk.function and 
                hasattr(tc_chunk.function, 'name') and 
                tc_chunk.function.name)
    
    def _start_new_tool_call(self, tc_chunk) -> List[str]:
        """Start new tool call and return events"""
        events = []
        tool_call_id = tc_chunk.id
        
        self.tool_block_counter += 1
        tool_index = self.text_block_index + self.tool_block_counter
        
        self.current_tool_calls[tool_call_id] = {
            "index": tool_index,
            "name": tc_chunk.function.name or "",
            "args_buffer": tc_chunk.function.arguments or "",
            "started": True
        }
        
        # Create tool start event
        data = {
            'type': Constants.EVENT_CONTENT_BLOCK_START,
            'index': tool_index,
            'content_block': {
                'type': Constants.CONTENT_TOOL_USE,
                'id': tool_call_id,
                'name': self.current_tool_calls[tool_call_id]["name"],
                'input': {}
            }
        }
        events.append(f"event: {Constants.EVENT_CONTENT_BLOCK_START}\ndata: {json.dumps(data)}\n\n")
        
        return events
    
    def _create_tool_argument_delta(self, tool_call_id: str, arguments: str) -> str:
        """Create tool argument delta event"""
        self.current_tool_calls[tool_call_id]["args_buffer"] += arguments
        
        data = {
            'type': Constants.EVENT_CONTENT_BLOCK_DELTA,
            'index': self.current_tool_calls[tool_call_id]["index"],
            'delta': {'type': Constants.DELTA_INPUT_JSON, 'partial_json': arguments}
        }
        return f"event: {Constants.EVENT_CONTENT_BLOCK_DELTA}\ndata: {json.dumps(data)}\n\n"
    
    def _map_finish_reason(self, finish_reason: str) -> str:
        """Map finish reason to Anthropic format"""
        if finish_reason == Constants.FINISH_LENGTH:
            return Constants.STOP_MAX_TOKENS
        elif finish_reason == Constants.FINISH_TOOL_CALLS:
            return Constants.STOP_TOOL_USE
        elif finish_reason == Constants.FINISH_STOP:
            return Constants.STOP_END_TURN
        else:
            return Constants.STOP_END_TURN
    
    def _is_stream_complete(self, chunk) -> bool:
        """Check if stream is complete"""
        try:
            if hasattr(chunk, 'choices') and chunk.choices:
                return chunk.choices[0].finish_reason is not None
        except Exception:
            pass
        return False
    
    def _finalize_stream(self):
        """Generate final stream events"""
        # Stop text block
        yield f"event: {Constants.EVENT_CONTENT_BLOCK_STOP}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_STOP, 'index': self.text_block_index})}\n\n"
        
        # Stop tool blocks
        for tool_data in self.current_tool_calls.values():
            yield f"event: {Constants.EVENT_CONTENT_BLOCK_STOP}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_STOP, 'index': tool_data['index']})}\n\n"
        
        # Send final events
        usage_data = {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}
        delta_data = {
            'type': Constants.EVENT_MESSAGE_DELTA,
            'delta': {'stop_reason': self.final_stop_reason, 'stop_sequence': None},
            'usage': usage_data
        }
        yield f"event: {Constants.EVENT_MESSAGE_DELTA}\ndata: {json.dumps(delta_data)}\n\n"
        yield f"event: {Constants.EVENT_MESSAGE_STOP}\ndata: {json.dumps({'type': Constants.EVENT_MESSAGE_STOP})}\n\n"

async def handle_streaming(response_generator, original_request: MessagesRequest):
    """Enhanced streaming handler"""
    handler = StreamingHandler(original_request)
    async for event in handler.handle_streaming(response_generator):
        yield event

# Updated wrapper function with better error classification
async def handle_streaming_with_fallback(response_generator, original_request: MessagesRequest):
    """
    Streaming handler with comprehensive fallback for LiteLLM JSON parsing errors
    
    Enhanced with better error classification to reduce log noise for expected Gemini issues.
    """
    try:
        handler = StreamingHandler(original_request)
        chunk_count = 0
        
        async for event in handler.handle_streaming(response_generator):
            chunk_count += 1
            yield event
            
    except Exception as e:
        # Classify error for appropriate logging
        error_msg = str(e)
        
        # Check if this is an expected Gemini streaming issue
        expected_gemini_patterns = [
            "Error parsing chunk",
            "Expecting property name enclosed in double quotes",
            "json.decoder.JSONDecodeError",
            "RuntimeError: Error parsing chunk"
        ]
        
        is_expected_error = any(pattern in error_msg for pattern in expected_gemini_patterns)
        
        if is_expected_error:
            logger.info(f"Expected Gemini streaming issue after {chunk_count} chunks - sending graceful error response")
            logger.debug(f"Gemini error details: {error_msg}")
        else:
            logger.error(f"Unexpected LiteLLM streaming error after {chunk_count} chunks: {error_msg}")
        
        # Send appropriate error response
        async for error_event in handle_streaming_error(error_msg, original_request):
            yield error_event

async def handle_streaming_error(error_message: str, original_request: MessagesRequest):
    """Handle streaming errors by sending proper SSE error response"""
    message_id = f"msg_error_{uuid.uuid4().hex[:24]}"
    
    # Send message start
    yield f"event: {Constants.EVENT_MESSAGE_START}\ndata: {json.dumps({'type': Constants.EVENT_MESSAGE_START, 'message': {'id': message_id, 'type': 'message', 'role': Constants.ROLE_ASSISTANT, 'model': original_request.original_model or original_request.model, 'content': [], 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
    
    # Send content block start
    yield f"event: {Constants.EVENT_CONTENT_BLOCK_START}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_START, 'index': 0, 'content_block': {'type': Constants.CONTENT_TEXT, 'text': ''}})}\n\n"
    
    # Send error message with enhanced tool schema guidance
    schema_error_message = EnhancedErrorHandler._interpret_tool_schema_error(error_message)
    if schema_error_message:
        safe_error = schema_error_message
    elif "parsing" in error_message.lower() or "json" in error_message.lower():
        safe_error = "Data parsing error - please try again"
    elif "connection" in error_message.lower():
        safe_error = "Connection error - please check your request and try again"
    else:
        safe_error = "An error occurred while processing your request"
    
    yield f"event: {Constants.EVENT_CONTENT_BLOCK_DELTA}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_DELTA, 'index': 0, 'delta': {'type': Constants.DELTA_TEXT, 'text': safe_error}})}\n\n"
    
    # End the stream
    yield f"event: {Constants.EVENT_CONTENT_BLOCK_STOP}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_STOP, 'index': 0})}\n\n"
    yield f"event: {Constants.EVENT_MESSAGE_DELTA}\ndata: {json.dumps({'type': Constants.EVENT_MESSAGE_DELTA, 'delta': {'stop_reason': Constants.STOP_ERROR, 'stop_sequence': None}, 'usage': {'input_tokens': 0, 'output_tokens': 0}})}\n\n"
    yield f"event: {Constants.EVENT_MESSAGE_STOP}\ndata: {json.dumps({'type': Constants.EVENT_MESSAGE_STOP})}\n\n"

# Enhanced Response Conversion
class ResponseConverter:
    """Enhanced response conversion with better error handling and safety"""
    
    @staticmethod
    def safe_extract_response_data(litellm_response) -> Dict[str, Any]:
        """Safely extract data from LiteLLM response"""
        default_data = {
            "response_id": f"msg_{uuid.uuid4()}",
            "content_text": "",
            "tool_calls": None,
            "finish_reason": Constants.STOP_END_TURN,
            "prompt_tokens": 0,
            "completion_tokens": 0
        }
        
        try:
            if hasattr(litellm_response, 'choices') and hasattr(litellm_response, 'usage'):
                choices = litellm_response.choices
                message = choices[0].message if choices else None
                
                default_data.update({
                    "content_text": getattr(message, 'content', "") or "",
                    "tool_calls": getattr(message, 'tool_calls', None),
                    "finish_reason": choices[0].finish_reason if choices else Constants.FINISH_STOP,
                    "response_id": getattr(litellm_response, 'id', default_data["response_id"])
                })
                
                if hasattr(litellm_response, 'usage'):
                    usage = litellm_response.usage
                    default_data.update({
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(usage, "completion_tokens", 0)
                    })
                    
            elif isinstance(litellm_response, dict):
                choices = litellm_response.get("choices", [])
                message = choices[0].get("message", {}) if choices else {}
                usage = litellm_response.get("usage", {})
                
                default_data.update({
                    "content_text": message.get("content", "") or "",
                    "tool_calls": message.get("tool_calls"),
                    "finish_reason": choices[0].get("finish_reason", Constants.FINISH_STOP) if choices else Constants.FINISH_STOP,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "response_id": litellm_response.get("id", default_data["response_id"])
                })
                
        except Exception as e:
            logger.warning(f"Error extracting response data: {e}. Using defaults.")
        
        return default_data
    
    @staticmethod
    def convert_tool_calls(tool_calls) -> List[ContentBlockToolUse]:
        """Convert tool calls with enhanced validation"""
        content_blocks = []
        
        if not tool_calls:
            return content_blocks
            
        if not isinstance(tool_calls, list):
            tool_calls = [tool_calls]
        
        for tool_call in tool_calls:
            try:
                tool_data = ResponseConverter._extract_tool_call_data(tool_call)
                if tool_data and ToolProcessor.validate_tool_call({"name": tool_data["name"]}):
                    content_blocks.append(ContentBlockToolUse(
                        type=Constants.CONTENT_TOOL_USE,
                        id=tool_data["id"],
                        name=tool_data["name"],
                        input=tool_data["arguments"]
                    ))
                    
            except Exception as e:
                logger.warning(f"Error processing tool call: {e}")
                continue
        
        return content_blocks
    
    @staticmethod
    def _extract_tool_call_data(tool_call) -> Optional[Dict[str, Any]]:
        """Extract tool call data from various formats"""
        if isinstance(tool_call, dict):
            tool_id = tool_call.get("id", f"tool_{uuid.uuid4()}")
            function_data = tool_call.get(Constants.TOOL_FUNCTION, {})
            name = function_data.get("name", "")
            arguments_str = function_data.get("arguments", "{}")
        elif hasattr(tool_call, "id") and hasattr(tool_call, Constants.TOOL_FUNCTION):
            tool_id = tool_call.id
            name = tool_call.function.name
            arguments_str = tool_call.function.arguments
        else:
            logger.warning(f"Skipping malformed tool call: {tool_call}")
            return None
        
        if not name:
            return None
        
        # Parse arguments safely
        try:
            arguments_dict = json.loads(arguments_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse tool arguments: {e}")
            arguments_dict = {"raw_arguments": arguments_str}
        
        return {
            "id": tool_id,
            "name": name,
            "arguments": arguments_dict
        }
    
    @staticmethod
    def map_finish_reason(finish_reason: str, has_tool_calls: bool) -> Literal["end_turn", "max_tokens", "tool_use"]:
        """Map LiteLLM finish reason to Anthropic stop reason"""
        if finish_reason == Constants.FINISH_LENGTH:
            return Constants.STOP_MAX_TOKENS
        elif finish_reason == Constants.FINISH_TOOL_CALLS:
            return Constants.STOP_TOOL_USE
        elif finish_reason is None and has_tool_calls:
            return Constants.STOP_TOOL_USE
        else:
            if finish_reason and finish_reason not in [Constants.FINISH_STOP, Constants.FINISH_LENGTH, Constants.FINISH_TOOL_CALLS]:
                logger.debug(f"Mapping unhandled finish_reason '{finish_reason}' to 'end_turn'")
            return Constants.STOP_END_TURN

def convert_litellm_to_anthropic(litellm_response, original_request: MessagesRequest) -> MessagesResponse:
    """Enhanced conversion with improved error handling and safety"""
    try:
        # Safely extract response data
        data = ResponseConverter.safe_extract_response_data(litellm_response)
        
        # Build content blocks
        content_blocks = []
        
        # Add text content if present
        if data["content_text"]:
            content_blocks.append(ContentBlockText(type=Constants.CONTENT_TEXT, text=data["content_text"]))
        
        # Add tool calls if present
        tool_content_blocks = ResponseConverter.convert_tool_calls(data["tool_calls"])
        content_blocks.extend(tool_content_blocks)
        
        # Ensure at least one content block
        if not content_blocks:
            content_blocks.append(ContentBlockText(type=Constants.CONTENT_TEXT, text=""))
        
        # Map stop reason
        stop_reason = ResponseConverter.map_finish_reason(
            data["finish_reason"], 
            bool(data["tool_calls"])
        )
        
        return MessagesResponse(
            id=data["response_id"],
            model=original_request.original_model or original_request.model,
            role=Constants.ROLE_ASSISTANT,
            content=content_blocks,
            stop_reason=stop_reason,
            stop_sequence=None,
            usage=Usage(
                input_tokens=data["prompt_tokens"],
                output_tokens=data["completion_tokens"]
            )
        )
        
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        safe_error_msg = "Response conversion error"
        logger.error(f"Error converting response: {str(e)}\n{error_traceback}")
        
        return MessagesResponse(
            id=f"msg_error_{uuid.uuid4()}",
            model=original_request.original_model or original_request.model,
            role=Constants.ROLE_ASSISTANT, 
            content=[ContentBlockText(type=Constants.CONTENT_TEXT, text=safe_error_msg)],
            stop_reason=Constants.STOP_ERROR,
            usage=Usage(input_tokens=0, output_tokens=0)
        )

def is_valid_json(json_str):
    """Simple JSON validation utility"""
    if not isinstance(json_str, str):
        return False
    try:
        json.loads(json_str)
        return True
    except json.JSONDecodeError:
        return False

# Request Middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    method = request.method
    path = request.url.path
    logger.debug(f"Request: {method} {path}")
    response = await call_next(request)
    return response

# API Endpoints
@app.post("/v1/messages")
async def create_message(request: MessagesRequest, raw_request: Request):
    """Enhanced message creation endpoint with improved error handling"""
    try:
        logger.debug(f"📊 Processing request: Original={request.original_model}, Effective={request.model}, Stream={request.stream}")

        # Convert request
        litellm_request = convert_anthropic_to_litellm(request)
        litellm_request["api_key"] = config.gemini_api_key
        
        # Log request details
        num_tools = len(request.tools) if request.tools else 0
        log_request_beautifully(
            "POST", raw_request.url.path,
            request.original_model or request.model,
            litellm_request.get('model'),
            len(litellm_request['messages']),
            num_tools, 200
        )

        # Handle streaming vs non-streaming
        if request.stream:
            try:
                response_generator = await litellm.acompletion(**litellm_request)
                
                # Wrap the generator to catch LiteLLM-level streaming errors
                async def safe_streaming_wrapper():
                    try:
                        async for event in handle_streaming_with_fallback(response_generator, request):
                            yield event
                    except Exception as e:
                        # Catch any LiteLLM-level streaming errors that escape our handlers
                        error_msg = str(e)
                        logger.error(f"High-level streaming error caught: {error_msg}")
                        
                        # Send error message in SSE format
                        message_id = f"msg_error_{uuid.uuid4().hex[:24]}"
                        
                        # Error start
                        yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': message_id, 'type': 'message', 'role': 'assistant', 'model': request.original_model or request.model, 'content': [], 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
                        yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                        
                        # Determine error message based on error type
                        if ("Error parsing chunk" in error_msg and "Expecting property name" in error_msg):
                            safe_error = "Gemini API returned malformed streaming data. This is a temporary server issue - please try again in a moment."
                        elif "APIConnectionError" in error_msg:
                            safe_error = "Connection error during streaming. Please check your request and try again."
                        elif "RuntimeError" in error_msg and "chunk" in error_msg.lower():
                            safe_error = "Streaming data processing error. This is likely a temporary API issue - please retry."
                        else:
                            safe_error = "An unexpected streaming error occurred. Please try again."
                        
                        # Send error content
                        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': safe_error}})}\n\n"
                        
                        # Finish stream
                        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
                        yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'error', 'stop_sequence': None}, 'usage': {'input_tokens': 0, 'output_tokens': 0}})}\n\n"
                        yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
                
                return StreamingResponse(
                    safe_streaming_wrapper(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no"
                    }
                )
            except litellm.exceptions.APIError as e:
                logger.error(f"Streaming API Error: {e}")
                return StreamingResponse(
                    handle_streaming_error(str(e), request),
                    media_type="text/event-stream"
                )
            except Exception as e:
                logger.error(f"Streaming Error: {e}")
                return StreamingResponse(
                    handle_streaming_error(f"Streaming setup error: {str(e)}", request),
                    media_type="text/event-stream"
                )
        else:
            start_time = time.time()
            litellm_response = await litellm.acompletion(**litellm_request)
            logger.debug(f"✅ Response received: Model={litellm_request.get('model')}, Time={time.time() - start_time:.2f}s")
            
            anthropic_response = convert_litellm_to_anthropic(litellm_response, request)
            return anthropic_response

    except litellm.exceptions.APIError as e:
        return EnhancedErrorHandler.handle_litellm_error(e)
    except APIConnectionError as e:
        logger.error(f"LiteLLM Connection Error: {e}")
        safe_message = "Connection or data parsing error occurred"
        if "parsing" in str(e).lower() or "json" in str(e).lower():
            safe_message = "Response parsing error - the model response was malformed"
        raise HTTPException(status_code=503, detail=f"Service Error: {safe_message}")
    except Exception as e:
        return EnhancedErrorHandler.handle_general_error(e)

@app.post("/v1/messages/count_tokens")
async def count_tokens(request: TokenCountRequest, raw_request: Request):
    """Enhanced token counting endpoint"""
    try:
        # Create temporary request for conversion
        temp_request = MessagesRequest(
            model=request.model,
            max_tokens=1,
            messages=request.messages,
            system=request.system,
            tools=request.tools,
        )
        
        litellm_data = convert_anthropic_to_litellm(temp_request)
        
        # Log request
        num_tools = len(request.tools) if request.tools else 0
        log_request_beautifully(
            "POST", raw_request.url.path,
            request.original_model or request.model,
            litellm_data.get('model'),
            len(litellm_data['messages']), num_tools, 200
        )

        # Count tokens
        token_count = litellm.token_counter(
            model=litellm_data["model"],
            messages=litellm_data["messages"],
        )
        
        return TokenCountResponse(input_tokens=token_count)

    except Exception as e:
        logger.error(f"Error counting tokens: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error counting tokens: {str(e)}")

@app.get("/health")
async def health_check():
    """Enhanced health check endpoint with configurable API timeout"""
    try:
        # Basic health check
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "2.2.0",
            "gemini_api_configured": bool(config.gemini_api_key)
        }
        
        # Optional: Advanced health check with configurable timeout
        # Uncomment to enable API connectivity testing
        # try:
        #     import asyncio
        #     models = await asyncio.wait_for(
        #         litellm.amodel_list(api_key=config.gemini_api_key),
        #         timeout=config.health_check_api_timeout
        #     )
        #     health_status["gemini_api_accessible"] = True
        #     health_status["available_models"] = len(models) if models else 0
        # except Exception as api_error:
        #     health_status["gemini_api_accessible"] = False
        #     health_status["api_error"] = str(api_error)[:100]  # Truncate error message
        
        return health_status
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "timestamp": datetime.now().isoformat(),
                "error": "Health check failed"
            }
        )

@app.get("/")
async def root():
    """Root endpoint with enhanced information"""
    return {
        "message": f"Enhanced Anthropic-Compatible Proxy for Google Gemini v2.2.0",
        "config": {
            "big_model": config.big_model,
            "small_model": config.small_model,
            "available_models": model_manager.gemini_models[:5],
            "max_tokens_limit": config.max_tokens_limit,
            "request_timeout": config.request_timeout,
            "health_check_timeout": config.health_check_api_timeout
        }
    }

# Enhanced Logging Utilities
class Colors:
    """ANSI color codes for terminal output"""
    CYAN = "\033[96m"
    BLUE = "\033[94m" 
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    DIM = "\033[2m"

def log_request_beautifully(method: str, path: str, requested_model: str, 
                           gemini_model_used: str, num_messages: int, 
                           num_tools: int, status_code: int):
    """Enhanced request logging with better formatting"""
    if not sys.stdout.isatty():
        print(f"{method} {path} - {requested_model} -> {gemini_model_used} ({num_messages} messages, {num_tools} tools)")
        return
    
    # Colorized logging for TTY
    req_display = f"{Colors.CYAN}{requested_model}{Colors.RESET}"
    gemini_display = f"{Colors.GREEN}{gemini_model_used.replace('gemini/', '')}{Colors.RESET}"
    
    endpoint = path.split("?")[0] if "?" in path else path
    tools_str = f"{Colors.MAGENTA}{num_tools} tools{Colors.RESET}"
    messages_str = f"{Colors.BLUE}{num_messages} messages{Colors.RESET}"
    
    if status_code == 200:
        status_str = f"{Colors.GREEN}✓ {status_code} OK{Colors.RESET}"
    else:
        status_str = f"{Colors.RED}✗ {status_code}{Colors.RESET}"

    log_line = f"{Colors.BOLD}{method} {endpoint}{Colors.RESET} {status_str}"
    model_line = f"Request: {req_display} → Gemini: {gemini_display} ({tools_str}, {messages_str})"

    print(log_line)
    print(model_line)
    sys.stdout.flush()

def main():
    """Enhanced main function with comprehensive configuration info"""
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Enhanced Gemini-to-Claude API Proxy v2.2.0")
        print("")
        print("Usage: uvicorn enhanced_server:app --reload --host 0.0.0.0 --port 8082")
        print("")
        print("Required environment variables:")
        print("  GEMINI_API_KEY - Your Google Gemini API key")
        print("")
        print("Optional environment variables:")
        print(f"  BIG_MODEL - Big model name (default: {DefaultConfigValues.BIG_MODEL})")
        print(f"  SMALL_MODEL - Small model name (default: {DefaultConfigValues.SMALL_MODEL})")
        print(f"  HOST - Server host (default: {DefaultConfigValues.HOST})")
        print(f"  PORT - Server port (default: {DefaultConfigValues.PORT})")
        print(f"  LOG_LEVEL - Logging level (default: {DefaultConfigValues.LOG_LEVEL})")
        print(f"  MAX_TOKENS_LIMIT - Token limit (default: {DefaultConfigValues.MAX_TOKENS_LIMIT})")
        print(f"  REQUEST_TIMEOUT - Request timeout (default: {DefaultConfigValues.REQUEST_TIMEOUT})")
        print(f"  NUM_RETRIES - Number of retries (default: {DefaultConfigValues.NUM_RETRIES})")
        print(f"  HEALTH_CHECK_API_TIMEOUT - Health check timeout (default: {DefaultConfigValues.HEALTH_CHECK_API_TIMEOUT})")
        print("")
        print("Available Gemini models:")
        for model in model_manager.gemini_models:
            print(f"  - {model}")
        sys.exit(0)

    # Configuration summary
    print("🚀 Enhanced Gemini-to-Claude API Proxy v2.2.0")
    print(f"✅ Configuration loaded successfully")
    print(f"   Big Model: {config.big_model}")
    print(f"   Small Model: {config.small_model}")
    print(f"   Available Models: {len(model_manager.gemini_models)}")
    print(f"   Max Tokens Limit: {config.max_tokens_limit}")
    print(f"   Request Timeout: {config.request_timeout}s")
    print(f"   Health Check Timeout: {config.health_check_api_timeout}s")
    print(f"   Retries: {config.num_retries}")
    print(f"   Log Level: {config.log_level}")
    print(f"   Server: {config.host}:{config.port}")
    print("")
    print("📝 Known Issues:")
    print("   - Gemini's streaming API occasionally sends malformed JSON chunks")
    print("   - This causes 'Expecting property name' errors that are handled gracefully")
    print("   - If streaming fails repeatedly, try non-streaming mode or retry later")
    print("")

    # Start server
    uvicorn.run(
        app, 
        host=config.host, 
        port=config.port, 
        log_level=config.log_level.lower()
    )

if __name__ == "__main__":
    main()
