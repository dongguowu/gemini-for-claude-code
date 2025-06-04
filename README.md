# Gemini for Claude Code: An Anthropic-Compatible Proxy

This server acts as a bridge, enabling you to use **Claude Code** with Google's powerful **Gemini models**. It translates API requests and responses between the Anthropic format (used by Claude Code) and the Gemini format (via LiteLLM), allowing seamless integration.

![Claude Code with Gemini Proxy](image.png)

## Features

- **Claude Code Compatibility with Gemini**: Directly use the Claude Code CLI with Google Gemini models.
- **Seamless Model Mapping**: Intelligently maps Claude Code model requests (e.g., `haiku`, `sonnet`, `opus` aliases) to your chosen Gemini models.
- **LiteLLM Integration**: Leverages LiteLLM for robust and flexible interaction with the Gemini API.
- **Full Streaming Support**: Handles streaming responses from Gemini for an interactive Claude Code experience, with improved error handling for streaming issues.
- **Complete Tool Use for Claude Code**: Translates Claude Code's tool usage (function calling) to and from Gemini's format, with robust handling of tool results.
- **Enhanced Error Handling**: Provides more specific and actionable error messages for common Gemini API issues.
- **Diagnostic Endpoints**: Includes `/health` and `/test-connection` for easier troubleshooting of your setup.
- **Token Counting**: Offers a `/v1/messages/count_tokens` endpoint compatible with Claude Code.

## Prerequisites

- A Google Gemini API key.
- Python 3.8+.
- Claude Code CLI installed (e.g., `npm install -g @anthropic-ai/claude-code`).

## Setup

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/coffeegrind123/gemini-code.git # Or your fork
    cd gemini-code
    ```

2.  **Create and activate a virtual environment** (recommended):
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables**:
    Copy the example environment file:
    ```bash
    cp .env.example .env
    ```
    Edit `.env` and add your Gemini API key. You can also customize model mappings and server settings:
    ```dotenv
    GEMINI_API_KEY="your-google-ai-studio-key" # Required

    # Optional: Customize which Gemini models are used for Claude Code's model aliases
    # BIG_MODEL="gemini-1.5-pro-latest"    # For 'sonnet' or 'opus' requests from Claude Code
    # SMALL_MODEL="gemini-1.5-flash-latest" # For 'haiku' requests from Claude Code
    
    # Optional: Server and performance settings
    # HOST="0.0.0.0"
    # PORT="8082"
    # LOG_LEVEL="INFO" # (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    # MAX_TOKENS_LIMIT="8192" # Max tokens for Gemini
    # REQUEST_TIMEOUT="60" # Seconds
    # MAX_RETRIES="2"      # LiteLLM retries to Gemini
    ```
    The server defaults to `gemini-1.5-pro-latest` for `BIG_MODEL` and `gemini-1.5-flash-latest` for `SMALL_MODEL`.

5.  **Run the server**:
    The `server.py` script includes a `main()` function that starts the Uvicorn server:
    ```bash
    python server.py
    ```
    For development with auto-reload (restarts when you save changes to `server.py`):
    ```bash
    uvicorn server:app --host 0.0.0.0 --port 8082 --reload
    ```
    You can view all startup options, including configurable environment variables, by running:
    ```bash
    python server.py --help
    ```

## Usage with Claude Code

1.  **Start the Proxy Server**: Ensure the Gemini proxy server (this application) is running (see step 5 above).

2.  **Configure Claude Code to Use the Proxy**:
    Set the `ANTHROPIC_BASE_URL` environment variable when running Claude Code:
    ```bash
    ANTHROPIC_BASE_URL=http://localhost:8082 claude
    ```
    Replace `localhost:8082` if your proxy is running on a different host or port.

3.  **Utilize `CLAUDE.md` for Optimal Gemini Performance (Crucial)**:
    - This repository includes a `CLAUDE.md` file. This file contains specific instructions and best practices tailored to help **Gemini** effectively understand and respond to **Claude Code's** unique command structure, tool usage patterns, and desired output formats.
    - **Copy `CLAUDE.md` into your project directory**:
      ```bash
      cp /path/to/gemini-code/CLAUDE.md /your/project/directory/
      ```
    - When Claude Code starts in a directory containing `CLAUDE.md`, it automatically reads this file and incorporates its content into the system prompt. This is essential for guiding Gemini to work optimally within the Claude Code environment.

## How It Works: Powering Claude Code with Gemini

1.  **Claude Code Request**: You issue a command or prompt in the Claude Code CLI.
2.  **Anthropic Format**: Claude Code sends an API request (in Anthropic's Messages API format) to the proxy server's address (`http://localhost:8082`).
3.  **Proxy Translation (Anthropic to Gemini)**: The proxy server:
    *   Receives the Anthropic-formatted request.
    *   Validates it and maps any Claude model aliases (like `claude-3-sonnet...`) to the corresponding Gemini model specified in your `.env` (e.g., `gemini-1.5-pro-latest`).
    *   Translates the message structure, content blocks, and tool definitions into a format LiteLLM can use with the Gemini API.
4.  **LiteLLM to Gemini**: LiteLLM sends the prepared request to the target Gemini model using your `GEMINI_API_KEY`.
5.  **Gemini Response**: Gemini processes the request and sends its response back through LiteLLM.
6.  **Proxy Translation (Gemini to Anthropic)**: The proxy server:
    *   Receives the Gemini response from LiteLLM (this can be a stream of events or a complete JSON object).
    *   Converts Gemini's output (text, tool calls, stop reasons) back into the Anthropic Messages API format that Claude Code expects.
7.  **Response to Claude Code**: The proxy sends the Anthropic-formatted response back to your Claude Code client, which then displays the result or performs the requested action.

## Model Mapping for Claude Code

To ensure Claude Code's model requests are handled correctly by Gemini:

- Requests from Claude Code for model names containing **"haiku"** (e.g., `claude-3-haiku-20240307`) are mapped to the Gemini model specified by your `SMALL_MODEL` environment variable (default: `gemini-1.5-flash-latest`).
- Requests from Claude Code for model names containing **"sonnet"** or **"opus"** (e.g., `claude-3-sonnet-20240229`, `claude-3-opus-20240229`) are mapped to the Gemini model specified by your `BIG_MODEL` environment variable (default: `gemini-1.5-pro-latest`).
- If Claude Code requests a full Gemini model name (e.g., `gemini/gemini-1.5-pro-latest`), the proxy will use that directly.

The server maintains a list of known Gemini models. If a recognized Gemini model is requested by the client without the `gemini/` prefix, the proxy will add it.

## Endpoints

- `POST /v1/messages`: The primary endpoint for Claude Code to send messages to Gemini. It's fully compatible with the Anthropic Messages API specification that Claude Code uses.
- `POST /v1/messages/count_tokens`: Allows Claude Code to estimate the token count for a set of messages, using Gemini's tokenization.
- `GET /health`: Returns the health status of the proxy, including API key configuration and basic API key validation.
- `GET /test-connection`: Performs a quick API call to Gemini to verify connectivity and that your `GEMINI_API_KEY` is working.
- `GET /`: Root endpoint providing a welcome message, current configuration summary (models, limits), and available endpoints.

## Logging

The server provides detailed logs, which are especially useful for understanding how Claude Code requests are translated for Gemini. Logs are colorized in TTY environments for easier reading. Adjust verbosity with the `LOG_LEVEL` environment variable.

## The `CLAUDE.MD` File: Guiding Gemini for Claude Code

The `CLAUDE.MD` file included in this repository is critical for achieving the best experience when using this proxy with Claude Code and Gemini.

**Purpose:**

- **Tailors Gemini to Claude Code's Needs**: Claude Code has specific ways it expects an LLM to behave, especially regarding tool use, file operations, and output formatting. `CLAUDE.MD` provides Gemini with explicit instructions on these expectations.
- **Improves Tool Reliability**: By outlining how tools should be called and results interpreted, it helps Gemini make more effective use of Claude Code's capabilities.
- **Enhances Code Generation & Understanding**: Gives Gemini context about the development environment and coding standards, leading to better code suggestions within Claude Code.
- **Reduces Misinterpretations**: Helps bridge any gaps between how Anthropic models might interpret Claude Code directives versus how Gemini might.

**How Claude Code Uses It:**

When you run `claude` in a project directory, the Claude Code CLI automatically looks for a `CLAUDE.MD` file in that directory. If found, its contents are prepended to the system prompt for every request sent to the LLM (in this case, your Gemini proxy).

**Recommendation:** Always copy the `CLAUDE.MD` from this proxy's repository into the root of any project where you intend to use Claude Code with this Gemini proxy. This ensures Gemini receives these vital instructions for every session.

## Contributing

Contributions, issues, and feature requests are welcome! Please submit them on the GitHub repository.

## Thanks

This project was heavily inspired by and builds upon the foundational work of the [claude-code-proxy by @1rgs](https://github.com/1rgs/claude-code-proxy). Their original proxy was instrumental in demonstrating the viability of such a bridge.
