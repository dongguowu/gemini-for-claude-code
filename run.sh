#!/bin/bash
#
# This script automates the setup and execution of the Gemini Proxy Server.
# It ensures the virtual environment is created and activated, and all
# dependencies are installed before starting the server.
#
# Usage:
#   ./run.sh        - Starts the server in development mode (with auto-reload)
#   ./run.sh prod   - Starts the server in production mode

# Exit immediately if a command exits with a non-zero status.
set -e

echo "🚀 Starting Gemini Proxy Server Setup..."

# 1. Check for and create the virtual environment if it doesn't exist.
if [ ! -d ".venv" ]; then
    echo "🔍 Virtual environment not found. Creating one at ./.venv..."
    python3 -m venv .venv
    echo "✅ Virtual environment created successfully."
fi

# 2. Activate the virtual environment.
echo "⚡ Activating virtual environment..."
source .venv/bin/activate
echo "✅ Virtual environment activated."

# 3. Install or update dependencies from requirements.txt.
echo "📦 Installing/updating dependencies..."
pip install -r requirements.txt
echo "✅ Dependencies are up to date."

# 4. Run the server based on the provided argument.
if [ "$1" == "prod" ]; then
    echo "🔥 Starting server in PRODUCTION mode..."
    echo "   URL: http://0.0.0.0:8082"
    python server.py
else
    echo "🔧 Starting server in DEVELOPMENT mode (with auto-reload)..."
    echo "   URL: http://0.0.0.0:8082"
    echo "   (To run in production, use: ./run.sh prod)"
    uvicorn server:app --host 0.0.0.0 --port 8082 --reload
fi
