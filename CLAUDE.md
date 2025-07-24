# CLAUDE.md

Please read english_corrections.md first.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project is a Python-based proxy server that enables using Google's Gemini models with the Anthropic Claude Code CLI. It acts as a translation layer, converting API requests and responses between the Anthropic and Gemini formats. The server is built with FastAPI and uses LiteLLM for interacting with the Gemini API.

**This proxy exclusively supports the Gemini 2.5 series models.**

## Key Files

-   `server.py`: The core of the application, containing all the FastAPI endpoints, data models (Pydantic), and logic for request/response translation.
-   `requirements.txt`: Lists all Python dependencies.
-   `.env.example`: An example environment file for configuring the server. It supports the `API_KEYS` environment variable for managing API keys.
-   `README.md`: Contains detailed setup and usage instructions.

## Common Development Tasks

### Running the Server

-   **For development (with auto-reload):**
    ```bash
    uvicorn server:app --host 0.0.0.0 --port 8082 --reload
    ```
-   **For production:**
    ```bash
    python server.py
    ```

### Installing Dependencies

-   Install or update dependencies from `requirements.txt`:
    ```bash
    pip install -r requirements.txt
    ```

### Testing

The project does not have a dedicated test suite. The primary methods for testing are:

1.  **Health Check Endpoint:**
    ```bash
    curl http://localhost:8082/health
    ```
2.  **Connection Test Endpoint:** Verifies connectivity with one of the configured API keys.
    ```bash
    curl http://localhost:8082/test-connection
    ```
3.  **Manual Testing with Claude Code:**
    -   Start the proxy server.
    -   Run Claude Code, pointing it to the local proxy:
        ```bash
        ANTHROPIC_BASE_URL=http://localhost:8082 claude
        ```

## Code Architecture

-   **FastAPI Application (`server.py`):**
    -   The main `FastAPI` instance is `app`.
    -   It defines several endpoints, with `/v1/messages` being the primary one for handling Claude Code requests.
    -   Pydantic models are used extensively for request and response validation.
-   **Configuration (`Config` class):**
    -   Loads settings from environment variables.
    -   `API_KEYS` should be a JSON array of strings. The server rotates through the list of keys for each request to balance usage.
    -   The `GEMINI_API_KEY` variable is deprecated but still supported for backward compatibility.
-   **Model Mapping (`ModelManager` class):**
    -   Maps Claude Code model aliases (e.g., `haiku`, `sonnet`) to specific Gemini 2.5 models defined in the environment variables. The default `BIG_MODEL` is `gemini-2.5-pro` and `SMALL_MODEL` is `gemini-2.5-flash`.
-   **Request/Response Translation:**
    -   `convert_anthropic_to_litellm()`: Converts incoming Anthropic-formatted requests into the format expected by LiteLLM for Gemini.
    -   `convert_litellm_to_anthropic()`: Converts responses from LiteLLM back into the Anthropic format that Claude Code understands.
    -   `handle_streaming_with_recovery()`: A robust handler for processing streaming responses from Gemini, including error recovery for malformed data chunks.
-   **Error Handling:**
    -   `classify_gemini_error()`: Provides more specific and actionable error messages for common Gemini API issues.
    -   The main `/v1/messages` endpoint includes retry logic for streaming failures, with an automatic fallback to non-streaming mode if necessary.
-   **Logging:**
    -   Uses Python's `logging` module.
    -   Log level is configurable via the `LOG_LEVEL` environment variable.
    ## Git Workflow

-   When creating commits, do not include the `Co-Authored-By` trailer.

