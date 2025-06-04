from fastapi import FastAPI, Request, HTTPException
import uvicorn
import logging
import json
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Optional, Union, Literal
import os
from fastapi.responses import JSONResponse, StreamingResponse
import litellm
import uuid
import time
from dotenv import load_dotenv
from datetime import datetime
import sys

litellm.set_verbose = False
# litellm.telemetry = False # Optional: If you want to disable telemetry

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.WARN,  # Change to INFO level to show more details
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Configure uvicorn to be quieter
# Tell uvicorn's loggers to be quiet
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

# Create a filter to block any log messages containing specific strings
class MessageFilter(logging.Filter):
    def filter(self, record):
        # Block messages containing these strings
        blocked_phrases = [
            "LiteLLM completion()",
            "HTTP Request:",
            "selected model name for cost calculation",
            "utils.py",
            "cost_calculator"
        ]

        if hasattr(record, 'msg') and isinstance(record.msg, str):
            for phrase in blocked_phrases:
                if phrase in record.msg:
                    return False
        return True

# Apply the filter to the root logger to catch all messages
root_logger = logging.getLogger()
root_logger.addFilter(MessageFilter())

# Custom formatter for model mapping logs
class ColorizedFormatter(logging.Formatter):
    """Custom formatter to highlight model mappings"""
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def format(self, record):
        if record.levelno == logging.DEBUG and "MODEL MAPPING" in record.msg:
            # Apply colors and formatting to model mapping logs
            return f"{self.BOLD}{self.GREEN}{record.msg}{self.RESET}"
        return super().format(record)

# Apply custom formatter to console handler
for handler in logger.handlers:
    if isinstance(handler, logging.StreamHandler):
        handler.setFormatter(ColorizedFormatter('%(asctime)s - %(levelname)s - %(message)s'))

app = FastAPI()

# Get API keys from environment
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    logger.error("🔴 GEMINI_API_KEY not found in environment variables. Please set it.")
    # Potentially exit or raise a more severe error if running the server without it is not an option.
    # sys.exit(1)


# Preferred provider is now always Google/Gemini
PREFERRED_PROVIDER = "google"

# Get model mapping configuration from environment
# Default to latest Gemini models if not set
DEFAULT_BIG_GEMINI_MODEL = "gemini-1.5-pro-latest"
DEFAULT_SMALL_GEMINI_MODEL = "gemini-1.5-flash-latest"
BIG_MODEL = os.environ.get("BIG_MODEL", DEFAULT_BIG_GEMINI_MODEL) # Updated default
SMALL_MODEL = os.environ.get("SMALL_MODEL", DEFAULT_SMALL_GEMINI_MODEL) # Updated default

# List of Gemini models - ensure BIG_MODEL and SMALL_MODEL are in this list if not using aliases
GEMINI_MODELS = [
    "gemini-1.5-pro-latest",
    "gemini-1.5-pro-preview-0514", # Example, keep this updated
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash-preview-0514", # Example
    "gemini-pro", # Older model, still useful
    "gemini-2.5-pro-preview-05-06", # From original code
    "gemini-2.5-flash-preview-04-17" # From original code
]
# Ensure BIG_MODEL and SMALL_MODEL from environment are added if they are full Gemini names
if BIG_MODEL not in GEMINI_MODELS and BIG_MODEL.startswith("gemini"):
    GEMINI_MODELS.append(BIG_MODEL)
if SMALL_MODEL not in GEMINI_MODELS and SMALL_MODEL.startswith("gemini"):
    GEMINI_MODELS.append(SMALL_MODEL)


# Helper function to clean schema for Gemini
def clean_gemini_schema(schema: Any) -> Any:
    """Recursively removes unsupported fields from a JSON schema for Gemini."""
    if isinstance(schema, dict):
        # Remove specific keys unsupported by Gemini tool parameters
        schema.pop("additionalProperties", None)
        schema.pop("default", None)

        # Check for unsupported 'format' in string types
        if schema.get("type") == "string" and "format" in schema:
            allowed_formats = {"enum", "date-time"} # Gemini might support more, this is a safe subset
            if schema["format"] not in allowed_formats:
                logger.debug(f"Removing unsupported format '{schema['format']}' for string type in Gemini schema.")
                schema.pop("format")

        # Recursively clean nested schemas (properties, items, etc.)
        for key, value in list(schema.items()): # Use list() to allow modification during iteration
            schema[key] = clean_gemini_schema(value)
    elif isinstance(schema, list):
        # Recursively clean items in a list
        return [clean_gemini_schema(item) for item in schema]
    return schema

# Models for Anthropic API requests (kept for API compatibility)
class ContentBlockText(BaseModel):
    type: Literal["text"]
    text: str

class ContentBlockImage(BaseModel): # Kept for structure, though image handling with Gemini via LiteLLM needs testing
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
    content: Union[str, List[Dict[str, Any]], Dict[str, Any], List[Any], Any]

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

class ThinkingConfig(BaseModel): # This will be ignored for Gemini
    enabled: bool = True

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
    thinking: Optional[ThinkingConfig] = None # Kept for API compatibility, ignored by Gemini
    original_model: Optional[str] = None  # Will store the original model name

    @field_validator('model')
    def validate_model_field(cls, v, info):
        original_model = v
        new_model = v # Default to original value

        logger.debug(f"📋 MODEL VALIDATION (GEMINI-ONLY): Original='{original_model}', BIG='{BIG_MODEL}', SMALL='{SMALL_MODEL}'")

        clean_v = v
        if clean_v.startswith('gemini/'):
            clean_v = clean_v[7:]
        # Remove other prefixes if they somehow sneak in, though they shouldn't
        elif clean_v.startswith('anthropic/'): clean_v = clean_v[10:]
        elif clean_v.startswith('openai/'): clean_v = clean_v[7:]


        mapped = False
        # Map Haiku to SMALL_MODEL (must be a Gemini model)
        if 'haiku' in clean_v.lower():
            if SMALL_MODEL in GEMINI_MODELS:
                new_model = f"gemini/{SMALL_MODEL}"
                mapped = True
            else:
                logger.warning(f"⚠️ SMALL_MODEL ('{SMALL_MODEL}') is not a recognized Gemini model. Using original: '{original_model}'")
                # Fallback to a default known small Gemini or error
                new_model = f"gemini/{DEFAULT_SMALL_GEMINI_MODEL}" # Fallback
                mapped = True


        # Map Sonnet to BIG_MODEL (must be a Gemini model)
        elif 'sonnet' in clean_v.lower():
            if BIG_MODEL in GEMINI_MODELS:
                new_model = f"gemini/{BIG_MODEL}"
                mapped = True
            else:
                logger.warning(f"⚠️ BIG_MODEL ('{BIG_MODEL}') is not a recognized Gemini model. Using original: '{original_model}'")
                # Fallback to a default known big Gemini or error
                new_model = f"gemini/{DEFAULT_BIG_GEMINI_MODEL}" # Fallback
                mapped = True

        # Add 'gemini/' prefix if a known Gemini model is provided without it
        elif not mapped and clean_v in GEMINI_MODELS and not v.startswith('gemini/'):
            new_model = f"gemini/{clean_v}"
            mapped = True

        if mapped:
            logger.debug(f"📌 MODEL MAPPING: '{original_model}' ➡️ '{new_model}'")
        elif not v.startswith('gemini/'):
            logger.warning(f"⚠️ Model '{original_model}' is not a recognized Gemini model or alias, and does not start with 'gemini/'. Attempting to use as 'gemini/{v}'.")
            new_model = f"gemini/{v}" # Attempt to prefix
        else: # Already has gemini/ prefix, or wasn't mapped and we use as is
            new_model = v


        values = info.data
        if isinstance(values, dict):
            values['original_model'] = original_model

        # Final check if new_model is actually a gemini model
        if not new_model.startswith("gemini/"):
             logger.error(f"🚨 CRITICAL: Model '{new_model}' after validation is not a Gemini model. Defaulting to {DEFAULT_SMALL_GEMINI_MODEL}.")
             new_model = f"gemini/{DEFAULT_SMALL_GEMINI_MODEL}"


        return new_model

class TokenCountRequest(BaseModel):
    model: str
    messages: List[Message]
    system: Optional[Union[str, List[SystemContent]]] = None
    tools: Optional[List[Tool]] = None
    thinking: Optional[ThinkingConfig] = None
    tool_choice: Optional[Dict[str, Any]] = None
    original_model: Optional[str] = None

    @field_validator('model')
    def validate_model_token_count(cls, v, info):
        # Reuse the same validation logic from MessagesRequest
        # This is a bit of a hack for Pydantic v2; ideally, this would be a shared utility
        temp_request_data = {'model': v, 'max_tokens': 0, 'messages': []} # Dummy data
        validated_model = MessagesRequest.validate_model_field(v, info) # Call shared validator directly
        # validated_model = MessagesRequest.validate_model_field(v, info) # This might not work directly if context is different

        # Store the original model in the values dictionary
        values = info.data
        if isinstance(values, dict):
            values['original_model'] = v # original v before validation

        return validated_model


class TokenCountResponse(BaseModel):
    input_tokens: int

class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0 # Kept for Anthropic compatibility
    cache_read_input_tokens: int = 0  # Kept for Anthropic compatibility

class MessagesResponse(BaseModel):
    id: str
    model: str # This should be the original model requested by the user
    role: Literal["assistant"] = "assistant"
    content: List[Union[ContentBlockText, ContentBlockToolUse]]
    type: Literal["message"] = "message"
    stop_reason: Optional[Literal["end_turn", "max_tokens", "stop_sequence", "tool_use", "error"]] = None # Added error
    stop_sequence: Optional[str] = None
    usage: Usage

@app.middleware("http")
async def log_requests(request: Request, call_next):
    method = request.method
    path = request.url.path
    logger.debug(f"Request: {method} {path}")
    response = await call_next(request)
    return response

# (parse_tool_result_content function remains largely the same as it's for parsing, not provider specific)
def parse_tool_result_content(content):
    """Helper function to properly parse and normalize tool result content."""
    if content is None:
        return "No content provided"

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        result = ""
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                result += item.get("text", "") + "\n"
            elif isinstance(item, str):
                result += item + "\n"
            elif isinstance(item, dict):
                if "text" in item:
                    result += item.get("text", "") + "\n"
                else:
                    try:
                        result += json.dumps(item) + "\n"
                    except:
                        result += str(item) + "\n"
            else:
                try:
                    result += str(item) + "\n"
                except:
                    result += "Unparseable content\n"
        return result.strip()

    if isinstance(content, dict):
        if content.get("type") == "text":
            return content.get("text", "")
        try:
            return json.dumps(content)
        except:
            return str(content)

    # Fallback for any other type
    try:
        return str(content)
    except:
        return "Unparseable content"


def convert_anthropic_to_litellm(anthropic_request: MessagesRequest) -> Dict[str, Any]:
    litellm_messages = [] # Use a new list for clarity

    # System message handling (seems okay in your existing code)
    if anthropic_request.system:
        system_content_str = ""
        if isinstance(anthropic_request.system, str):
            system_content_str = anthropic_request.system
        elif isinstance(anthropic_request.system, list):
            for block in anthropic_request.system:
                if hasattr(block, 'type') and block.type == "text":
                    system_content_str += block.text + "\n\n"
                elif isinstance(block, dict) and block.get("type") == "text":
                    system_content_str += block.get("text", "") + "\n\n"
        if system_content_str.strip():
            litellm_messages.append({"role": "system", "content": system_content_str.strip()})

    for anthropic_msg in anthropic_request.messages:
        # Case 1: Simple string content
        if isinstance(anthropic_msg.content, str):
            litellm_messages.append({"role": anthropic_msg.role, "content": anthropic_msg.content})
            continue

        # Case 2: Content is a list of blocks
        current_msg_text_parts = []
        current_msg_image_parts = [] # Assuming you might handle these
        current_msg_assistant_tool_calls = []
        
        # For a 'user' message in Anthropic that contains 'tool_result' blocks
        # LiteLLM expects these as separate 'tool' role messages.
        # Any text in that 'user' message preceding the tool_result should be a separate 'user' message.
        pending_tool_role_messages = []

        for block in anthropic_msg.content:
            if block.type == "text":
                current_msg_text_parts.append(block.text)
            elif block.type == "image": # Adapt your image handling here
                if isinstance(block.source, dict) and \
                   block.source.get("type") == "base64" and \
                   "media_type" in block.source and "data" in block.source:
                    current_msg_image_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{block.source['media_type']};base64,{block.source['data']}"
                        }
                    })
                else:
                    logger.warning(f"Unsupported image block source format: {block.source}")

            elif block.type == "tool_use": # Assistant requests to use a tool
                if anthropic_msg.role == "assistant":
                    current_msg_assistant_tool_calls.append({
                        "id": block.id,
                        "type": "function", # LiteLLM standard
                        "function": {
                            "name": block.name,
                            "arguments": json.dumps(block.input) # Ensure arguments are a JSON string
                        }
                    })
                else: # Should not happen based on Anthropic spec
                    logger.error(f"CRITICAL: tool_use block found in non-assistant message: {anthropic_msg.role}")
            
            elif block.type == "tool_result": # User provides tool output
                if anthropic_msg.role == "user":
                    # If there's accumulated text for the current user message, create a user message for it first
                    if current_msg_text_parts or current_msg_image_parts:
                        user_content_for_litellm = []
                        if current_msg_text_parts:
                            user_content_for_litellm.append({"type": "text", "text": "".join(current_msg_text_parts).strip()})
                        user_content_for_litellm.extend(current_msg_image_parts)
                        
                        if user_content_for_litellm: # Only add if there's actual content
                           litellm_messages.append({
                               "role": "user", 
                               "content": user_content_for_litellm[0]["text"] if len(user_content_for_litellm) == 1 and user_content_for_litellm[0]["type"] == "text" else user_content_for_litellm
                           })
                        current_msg_text_parts = [] # Reset for next potential text block in same user message
                        current_msg_image_parts = []

                    # Now prepare the tool role message
                    parsed_tool_content = parse_tool_result_content(block.content)
                    pending_tool_role_messages.append({
                        "role": "tool",
                        "tool_call_id": block.tool_use_id,
                        "content": parsed_tool_content
                    })
                else: # Should not happen
                    logger.error(f"CRITICAL: tool_result block found in non-user message: {anthropic_msg.role}")

        # After processing all blocks for the current Anthropic message:
        # Construct the final LiteLLM message object for this Anthropic message.

        final_text_str = "".join(current_msg_text_parts).strip()

        if anthropic_msg.role == "user":
            # Any remaining text/image content for a user message (if not followed by a tool_result in the same message)
            if final_text_str or current_msg_image_parts:
                user_content_for_litellm = []
                if final_text_str:
                    user_content_for_litellm.append({"type": "text", "text": final_text_str})
                user_content_for_litellm.extend(current_msg_image_parts)

                if user_content_for_litellm: # Only add if there's actual content
                    litellm_messages.append({
                        "role": "user",
                        "content": user_content_for_litellm[0]["text"] if len(user_content_for_litellm) == 1 and user_content_for_litellm[0]["type"] == "text" else user_content_for_litellm
                    })
            # Add any pending tool messages that were part of this user message
            litellm_messages.extend(pending_tool_role_messages)

        elif anthropic_msg.role == "assistant":
            assistant_litellm_msg = {"role": "assistant"}
            
            # Content (text/image) for assistant
            assistant_content_actual = []
            if final_text_str:
                assistant_content_actual.append({"type": "text", "text": final_text_str})
            assistant_content_actual.extend(current_msg_image_parts)

            if assistant_content_actual:
                 assistant_litellm_msg["content"] = assistant_content_actual[0]["text"] if len(assistant_content_actual) == 1 and assistant_content_actual[0]["type"] == "text" else assistant_content_actual
            else:
                assistant_litellm_msg["content"] = None # Crucial: can be null if only tool_calls

            # Tool calls for assistant
            if current_msg_assistant_tool_calls:
                assistant_litellm_msg["tool_calls"] = current_msg_assistant_tool_calls
            
            # Only add the assistant message if it has text, images, or tool_calls
            if assistant_litellm_msg.get("content") or assistant_litellm_msg.get("tool_calls"):
                litellm_messages.append(assistant_litellm_msg)
    
    # --- Construct the final request dictionary for LiteLLM ---
    litellm_request_dict = {
        "model": anthropic_request.model, # Already validated model name
        "messages": litellm_messages,
        "max_tokens": min(anthropic_request.max_tokens, 8192), # Or your capping logic
        "temperature": anthropic_request.temperature,
        "stream": anthropic_request.stream,
    }

    if anthropic_request.stop_sequences:
        litellm_request_dict["stop"] = anthropic_request.stop_sequences
    if anthropic_request.top_p is not None: # Check for None explicitly
        litellm_request_dict["top_p"] = anthropic_request.top_p
    if anthropic_request.top_k is not None: # Check for None explicitly
        litellm_request_dict["top_k"] = anthropic_request.top_k

    if anthropic_request.tools:
        gemini_tools = []
        for tool_obj in anthropic_request.tools:
            tool_dict = tool_obj.dict() # Use .model_dump() if Pydantic v2
            input_schema = tool_dict.get("input_schema", {})
            cleaned_schema = clean_gemini_schema(input_schema) # Your existing schema cleaner
            gemini_tools.append({
                "type": "function",
                "function": {
                    "name": tool_dict["name"],
                    "description": tool_dict.get("description", ""),
                    "parameters": cleaned_schema
                }
            })
        litellm_request_dict["tools"] = gemini_tools

    if anthropic_request.tool_choice:
        # Your existing tool_choice conversion logic
        tool_choice_dict = anthropic_request.tool_choice
        choice_type = tool_choice_dict.get("type")
        if choice_type == "auto": litellm_request_dict["tool_choice"] = "auto"
        elif choice_type == "any": litellm_request_dict["tool_choice"] = "auto" # Or "required", Gemini "ANY"
        elif choice_type == "tool" and "name" in tool_choice_dict:
            litellm_request_dict["tool_choice"] = {"type": "function", "function": {"name": tool_choice_dict["name"]}}
        else: litellm_request_dict["tool_choice"] = "auto"
        
    return litellm_request_dict


def convert_litellm_to_anthropic(litellm_response: Union[Dict[str, Any], Any],
                                 original_request: MessagesRequest) -> MessagesResponse:
    """Convert LiteLLM (Gemini via OpenAI format) response to Anthropic API response format."""
    try:
        response_id = f"msg_{uuid.uuid4()}" # Default id
        content_text = ""
        tool_calls = None
        finish_reason = "end_turn" # Default
        prompt_tokens = 0
        completion_tokens = 0

        # Handle ModelResponse object from LiteLLM
        if hasattr(litellm_response, 'choices') and hasattr(litellm_response, 'usage'):
            choices = litellm_response.choices
            message = choices[0].message if choices and len(choices) > 0 else None
            content_text = message.content if message and hasattr(message, 'content') else ""
            tool_calls = message.tool_calls if message and hasattr(message, 'tool_calls') else None
            finish_reason = choices[0].finish_reason if choices and len(choices) > 0 else "stop"
            usage_info = litellm_response.usage
            prompt_tokens = getattr(usage_info, "prompt_tokens", 0)
            completion_tokens = getattr(usage_info, "completion_tokens", 0)
            response_id = getattr(litellm_response, 'id', response_id)
        elif isinstance(litellm_response, dict): # Handle dict response
            choices = litellm_response.get("choices", [{}])
            message = choices[0].get("message", {}) if choices and len(choices) > 0 else {}
            content_text = message.get("content", "")
            tool_calls = message.get("tool_calls", None)
            finish_reason = choices[0].get("finish_reason", "stop") if choices and len(choices) > 0 else "stop"
            usage_info = litellm_response.get("usage", {})
            prompt_tokens = usage_info.get("prompt_tokens", 0)
            completion_tokens = usage_info.get("completion_tokens", 0)
            response_id = litellm_response.get("id", response_id)
        else: # Fallback for unexpected response type
             logger.error(f"Unexpected LiteLLM response type: {type(litellm_response)}. Attempting to parse.")
             if hasattr(litellm_response, '__dict__'):
                 response_dict = litellm_response.__dict__
                 choices = response_dict.get("choices", [{}])
                 message = choices[0].get("message", {}) if choices and len(choices) > 0 else {}
                 content_text = message.get("content", "")
                 tool_calls = message.get("tool_calls", None)
                 # ... (continue extracting other fields)
             else:
                raise ValueError("LiteLLM response is not a recognized object or dictionary.")


        content_blocks = []
        if content_text is not None and content_text.strip() != "":
            content_blocks.append(ContentBlockText(type="text", text=content_text))

        if tool_calls:
            logger.debug(f"Processing tool calls from LiteLLM (Gemini): {tool_calls}")
            if not isinstance(tool_calls, list): # Ensure it's a list
                tool_calls = [tool_calls]

            for tc_idx, tool_call_item in enumerate(tool_calls):
                # tool_call_item from LiteLLM (OpenAI format):
                # { "id": "...", "type": "function", "function": { "name": "...", "arguments": "{...}"}}
                tool_id = ""
                name = ""
                arguments_str = "{}"

                if isinstance(tool_call_item, dict):
                    tool_id = tool_call_item.get("id", f"tool_{uuid.uuid4()}")
                    function_data = tool_call_item.get("function", {})
                    name = function_data.get("name", "")
                    arguments_str = function_data.get("arguments", "{}")
                elif hasattr(tool_call_item, "id") and hasattr(tool_call_item, "function"): # If it's an object
                    tool_id = tool_call_item.id
                    name = tool_call_item.function.name
                    arguments_str = tool_call_item.function.arguments
                else:
                    logger.warning(f"Skipping malformed tool_call_item: {tool_call_item}")
                    continue

                try:
                    arguments_dict = json.loads(arguments_str)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse tool arguments as JSON: {arguments_str}. Using raw string.")
                    arguments_dict = {"raw_arguments": arguments_str} # Pass as is or wrap

                content_blocks.append(ContentBlockToolUse(
                    type="tool_use",
                    id=tool_id,
                    name=name,
                    input=arguments_dict
                ))

        # Map OpenAI finish_reason to Anthropic stop_reason
        anthropic_stop_reason: Any = "end_turn" # Default
        if finish_reason == "stop":
            anthropic_stop_reason = "end_turn"
        elif finish_reason == "length":
            anthropic_stop_reason = "max_tokens"
        elif finish_reason == "tool_calls":
            anthropic_stop_reason = "tool_use"
        elif finish_reason is None and tool_calls: # Implicit tool_use if no other reason but tools are present
             anthropic_stop_reason = "tool_use"
        elif finish_reason: # other reasons like "content_filter" for Gemini
             anthropic_stop_reason = finish_reason # Pass it through if it's different

        if not content_blocks: # Must have at least one content block
            content_blocks.append(ContentBlockText(type="text", text=""))


        anthropic_response = MessagesResponse(
            id=response_id,
            model=original_request.original_model or original_request.model, # Use the originally requested model name
            role="assistant",
            content=content_blocks,
            stop_reason=anthropic_stop_reason,
            stop_sequence=None, # LiteLLM response doesn't typically include this directly
            usage=Usage(
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens
            )
        )
        return anthropic_response

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        error_message = f"Error converting LiteLLM (Gemini) response to Anthropic: {str(e)}\n\nFull traceback:\n{error_traceback}"
        logger.error(error_message)
        return MessagesResponse(
            id=f"msg_error_{uuid.uuid4()}",
            model=original_request.original_model or original_request.model,
            role="assistant",
            content=[ContentBlockText(type="text", text=f"Error converting response: {str(e)}.")],
            stop_reason="error",
            usage=Usage(input_tokens=0, output_tokens=0)
        )

def is_valid_json(json_str):
    if not isinstance(json_str, str): return False
    try:
        json.loads(json_str); return True
    except json.JSONDecodeError: return False

async def handle_streaming(response_generator, original_request: MessagesRequest):
    """Handle streaming responses from LiteLLM (Gemini) and convert to Anthropic SSE format."""
    message_id = f"msg_{uuid.uuid4().hex[:24]}"
    # Send message_start
    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': message_id, 'type': 'message', 'role': 'assistant', 'model': original_request.original_model or original_request.model, 'content': [], 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"

    # Assume first block is text, can be empty if tool use comes first
    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
    yield f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n" # Anthropic sends pings

    accumulated_text = ""
    text_block_index = 0
    tool_block_index_counter = 0 # For assigning new indices to tool blocks
    current_tool_calls_data = {} # {tool_call_id: {"index": X, "name": Y, "args_buffer": Z}}
    input_tokens = 0 # Will be updated at the end by LiteLLM's final chunk
    output_tokens = 0
    final_stop_reason = "end_turn" # Default


    async for chunk in response_generator:
        # logger.debug(f"Raw Stream Chunk: {chunk}")
        try:
            if isinstance(chunk, str): # Should not happen with LiteLLM acompletion typically
                logger.warning(f"Received string chunk: {chunk}")
                if chunk.strip() == "[DONE]": # OpenAI style done
                    break
                try:
                    chunk = json.loads(chunk) # If it's a JSON string
                except json.JSONDecodeError:
                    logger.error(f"Could not parse string chunk as JSON: {chunk}")
                    continue


            # Extract data from LiteLLM's ModelResponse (StreamingChunk)
            # LiteLLM streaming chunk (OpenAI compatible):
            # Choice(delta=Delta(content=' some text', role=None, tool_calls=None), finish_reason=None, index=0, logprobs=None)
            # Or for tool calls:
            # Choice(delta=Delta(content=None, role=None, tool_calls=[ToolCallChunk(id='call_abc', function=FunctionChunk(arguments='{"a":1', name='tool_name'), index=0, type='function')]), finish_reason=None, index=0)
            # Final chunk might have usage:
            # StreamingChunk(..., usage={"prompt_tokens":X, "completion_tokens":Y}, ...)

            delta_content_text = None
            delta_tool_calls = None
            chunk_finish_reason = None

            if hasattr(chunk, 'choices') and chunk.choices:
                choice = chunk.choices[0]
                if hasattr(choice, 'delta') and choice.delta:
                    delta = choice.delta
                    delta_content_text = delta.content
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        delta_tool_calls = delta.tool_calls
                chunk_finish_reason = choice.finish_reason

            if hasattr(chunk, 'usage') and chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens
                # This usually comes in the *last* chunk with finish_reason
                logger.debug(f"Received usage in chunk: Input={input_tokens}, Output={output_tokens}")


            # Handle text delta
            if delta_content_text:
                accumulated_text += delta_content_text
                yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': text_block_index, 'delta': {'type': 'text_delta', 'text': delta_content_text}})}\n\n"

            # Handle tool call deltas
            if delta_tool_calls:
                if not accumulated_text and text_block_index == 0: # If text block was started but no text came
                    # This means first content is a tool. We started text block at index 0.
                    # We can't "remove" it, but Anthropic UI handles empty text block if tool_use follows.
                    pass

                for tc_chunk in delta_tool_calls:
                    # tc_chunk: ToolCallChunk(id='call_abc', function=FunctionChunk(arguments='{"a":1', name='tool_name'), index=0, type='function')
                    tool_call_id = tc_chunk.id
                    tool_index_in_chunk_list = tc_chunk.index # This is the index in the list of tool_calls for *this assistant turn*

                    if tool_call_id not in current_tool_calls_data:
                        # New tool call started
                        tool_block_index_counter += 1 # This is the Anthropic content_block index
                        current_tool_block_anthropic_idx = text_block_index + tool_block_index_counter

                        current_tool_calls_data[tool_call_id] = {
                            "anthropic_idx": current_tool_block_anthropic_idx,
                            "name": tc_chunk.function.name if tc_chunk.function.name else "",
                            "args_buffer": tc_chunk.function.arguments if tc_chunk.function.arguments else "",
                            "id_sent": False, # Track if content_block_start was sent for this tool
                            "name_sent": bool(tc_chunk.function.name)
                        }
                        # Send content_block_start for the new tool
                        # It might only have ID, name might come in next chunk part
                        if not current_tool_calls_data[tool_call_id]["id_sent"]:
                             yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': current_tool_block_anthropic_idx, 'content_block': {'type': 'tool_use', 'id': tool_call_id, 'name': current_tool_calls_data[tool_call_id]['name'], 'input': {}}})}\n\n"
                             current_tool_calls_data[tool_call_id]["id_sent"] = True
                    else:
                        # Continuation of an existing tool call
                        if tc_chunk.function.name and not current_tool_calls_data[tool_call_id]["name_sent"]:
                            # This case is unlikely if LiteLLM sends name with ID, but good to handle
                            current_tool_calls_data[tool_call_id]["name"] = tc_chunk.function.name
                            # Need to update the block if name wasn't sent initially (not standard SSE way)
                            logger.warning("Tool name received in a later chunk part, which is unusual for SSE.")


                        if tc_chunk.function.arguments:
                            current_tool_calls_data[tool_call_id]["args_buffer"] += tc_chunk.function.arguments


                    # Send argument delta
                    if tc_chunk.function.arguments:
                        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': current_tool_calls_data[tool_call_id]['anthropic_idx'], 'delta': {'type': 'input_json_delta', 'partial_json': tc_chunk.function.arguments}})}\n\n"


            if chunk_finish_reason:
                final_stop_reason = "end_turn"
                if chunk_finish_reason == "length": final_stop_reason = "max_tokens"
                elif chunk_finish_reason == "tool_calls": final_stop_reason = "tool_use"
                elif chunk_finish_reason == "stop": final_stop_reason = "end_turn"
                else: final_stop_reason = chunk_finish_reason # Pass through other reasons like "content_filter"

                # Stop the text block
                yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': text_block_index})}\n\n"

                # Stop all tool blocks
                for tool_data in current_tool_calls_data.values():
                    yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': tool_data['anthropic_idx']})}\n\n"

                # Send message_delta with stop reason and final usage
                final_usage = {"input_tokens": input_tokens, "output_tokens": output_tokens} # Use totals from the final chunk if available
                yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': final_stop_reason, 'stop_sequence': None}, 'usage': final_usage})}\n\n"
                yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
                # yield "data: [DONE]\n\n" # LiteLLM usually does not send [DONE] itself for acompletion
                return # End of stream

        except Exception as e:
            logger.error(f"Error processing stream chunk: {str(e)} - Chunk: {chunk}")
            import traceback
            logger.error(traceback.format_exc())
            # Continue to next chunk if possible, or break if fatal

    # Fallback if stream ends without a finish_reason explicitly (e.g. generator exhausted)
    # This part might be reached if LiteLLM's generator finishes without a final chunk having finish_reason
    logger.debug("Stream ended without explicit finish_reason in last chunk. Finalizing.")
    yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': text_block_index})}\n\n"
    for tool_data in current_tool_calls_data.values():
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': tool_data['anthropic_idx']})}\n\n"

    final_usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': final_stop_reason, 'stop_sequence': None}, 'usage': final_usage})}\n\n"
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"


@app.post("/v1/messages")
async def create_message(
    request: MessagesRequest,
    raw_request: Request # To get original model name if needed
):
    try:
        # The request.model is already validated and prefixed by Pydantic
        # request.original_model stores the model name from the incoming request body

        logger.debug(f"📊 PROCESSING REQUEST: Original Model='{request.original_model}', Effective Model='{request.model}', Stream={request.stream}")

        litellm_request = convert_anthropic_to_litellm(request)
        litellm_request["api_key"] = GEMINI_API_KEY
        logger.debug(f"Using Gemini API key for model: {request.model}")


        # Log the LiteLLM request (be careful with sensitive data in production)
        # For debugging, you can log parts of it:
        # logger.debug(f"LiteLLM Request (messages part): {json.dumps(litellm_request.get('messages',[]), indent=2)}")
        # logger.debug(f"LiteLLM Request (tools part): {json.dumps(litellm_request.get('tools',[]), indent=2)}")


        num_tools = len(request.tools) if request.tools else 0
        log_request_beautifully(
            "POST",
            raw_request.url.path,
            request.original_model or request.model, # Display original model
            litellm_request.get('model'), # Display model being sent to LiteLLM
            len(litellm_request['messages']),
            num_tools,
            200 # Assuming success at this point of processing
        )

        if request.stream:
            response_generator = await litellm.acompletion(**litellm_request)
            return StreamingResponse(
                handle_streaming(response_generator, request),
                media_type="text/event-stream"
            )
        else:
            start_time = time.time()
            litellm_response_obj = await litellm.acompletion(**litellm_request) # Use async for consistency
            # litellm_response_obj = litellm.completion(**litellm_request) # Sync version
            logger.debug(f"✅ RESPONSE RECEIVED: Model={litellm_request.get('model')}, Time={time.time() - start_time:.2f}s")
            # logger.debug(f"LiteLLM Full Response Object: {litellm_response_obj}")

            anthropic_response = convert_litellm_to_anthropic(litellm_response_obj, request)
            return anthropic_response

    except litellm.exceptions.APIError as e: # Catch LiteLLM specific API errors
        logger.error(f"LiteLLM APIError: Status Code: {e.status_code}, Message: {e.message}, LLM Provider: {e.llm_provider}, Model: {e.model}")
        import traceback
        logger.error(traceback.format_exc())
        # Try to get more details if available in e.response
        error_detail_msg = str(e.message)
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
             try:
                response_json = json.loads(e.response.text)
                if 'error' in response_json and 'message' in response_json['error']:
                    error_detail_msg = response_json['error']['message']
             except:
                error_detail_msg = e.response.text[:500] # Truncate if too long

        raise HTTPException(status_code=e.status_code or 500, detail=f"LLM Provider Error ({e.llm_provider} - {e.model}): {error_detail_msg}")

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        error_details = {
            "error": str(e), "type": type(e).__name__, "traceback": error_traceback
        }
        # ... (rest of your detailed error logging)
        serializable_details = {}
        for key, value in error_details.items():
            try: json.dumps({key: value}); serializable_details[key] = value
            except TypeError: serializable_details[key] = f"<{type(value).__name__}>: {str(value)}"
        logger.error(f"Error processing request: {json.dumps(serializable_details, indent=2)}")

        status_code = getattr(e, 'status_code', 500)
        raise HTTPException(status_code=status_code, detail=f"Internal Server Error: {str(e)}")


@app.post("/v1/messages/count_tokens")
async def count_tokens(
    request: TokenCountRequest,
    raw_request: Request
):
    try:
        # request.model is already validated and prefixed
        # request.original_model contains the user-sent model name

        # Convert the messages to a format LiteLLM can understand for token counting
        # We pass dummy max_tokens as it's not used for counting.
        # Use MessagesRequest to leverage its structure and conversion logic, then extract parts.
        temp_messages_request = MessagesRequest(
            model=request.model, # Validated model
            max_tokens=1,
            messages=request.messages,
            system=request.system,
            tools=request.tools,
            # tool_choice=request.tool_choice, # token_counter might not use this
            # thinking=request.thinking
        )
        litellm_formatted_parts = convert_anthropic_to_litellm(temp_messages_request)

        num_tools = len(request.tools) if request.tools else 0
        log_request_beautifully(
            "POST", raw_request.url.path,
            request.original_model or request.model, # Display original
            litellm_formatted_parts.get('model'), # Display model for counting
            len(litellm_formatted_parts['messages']), num_tools, 200
        )

        token_count = litellm.token_counter(
            model=litellm_formatted_parts["model"],
            messages=litellm_formatted_parts["messages"],
            # LiteLLM's token_counter might also accept 'tools' directly for some models
            # tools=litellm_formatted_parts.get("tools") # If supported
        )
        return TokenCountResponse(input_tokens=token_count)

    except Exception as e:
        import traceback
        logger.error(f"Error counting tokens: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error counting tokens: {str(e)}")

@app.get("/")
async def root():
    return {"message": "Anthropic-Compatible Proxy for Google Gemini (via LiteLLM)"}

class Colors:
    CYAN = "\033[96m"; BLUE = "\033[94m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
    RED = "\033[91m"; MAGENTA = "\033[95m"; RESET = "\033[0m"; BOLD = "\033[1m"
    UNDERLINE = "\033[4m"; DIM = "\033[2m"

def log_request_beautifully(method, path, requested_model, gemini_model_used, num_messages, num_tools, status_code):
    """Log requests, showing mapping from requested model to the actual Gemini model used."""
    req_display = f"{Colors.CYAN}{requested_model}{Colors.RESET}"
    gemini_display = f"{Colors.GREEN}{gemini_model_used.replace('gemini/', '')}{Colors.RESET}" # Show clean name

    endpoint = path.split("?")[0] if "?" in path else path
    tools_str = f"{Colors.MAGENTA}{num_tools} tools{Colors.RESET}"
    messages_str = f"{Colors.BLUE}{num_messages} messages{Colors.RESET}"
    status_str = f"{Colors.GREEN}✓ {status_code} OK{Colors.RESET}" if status_code == 200 else f"{Colors.RED}✗ {status_code}{Colors.RESET}"

    log_line = f"{Colors.BOLD}{method} {endpoint}{Colors.RESET} {status_str}"
    model_line = f"Request: {req_display} → Gemini: {gemini_display} ({tools_str}, {messages_str})"

    print(log_line); print(model_line); sys.stdout.flush()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Run with: uvicorn your_module_name:app --reload --host 0.0.0.0 --port 8082")
        print("Ensure GEMINI_API_KEY is set in your environment or .env file.")
        print("Optional .env vars: BIG_MODEL (default gemini-1.5-pro-latest), SMALL_MODEL (default gemini-1.5-flash-latest)")
        sys.exit(0)

    if not GEMINI_API_KEY:
        print("🔴 FATAL: GEMINI_API_KEY is not set. Please set it in your environment or .env file.")
        print("If you have a .env file, ensure it's in the same directory or loaded correctly.")
        sys.exit(1)
    else:
        print(f"✅ GEMINI_API_KEY loaded. BIG_MODEL='{BIG_MODEL}', SMALL_MODEL='{SMALL_MODEL}'")


    uvicorn.run(app, host="0.0.0.0", port=8082, log_level="warning") # uvicorn log_level


if __name__ == "__main__":
    main()
