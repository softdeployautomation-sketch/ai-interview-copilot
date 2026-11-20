#!/bin/bash
# AI Interview Copilot — launcher

cd "$(dirname "$0")"

# Auto-load .env if it exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

PORT="${PORT:-5055}"

# Kill anything already on that port
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "⚠️  Port $PORT in use — stopping previous server..."
    lsof -ti:$PORT | xargs kill -9 2>/dev/null
    sleep 1
fi

echo "🎤 Starting AI Interview Copilot on port $PORT..."
echo ""
echo "   Open http://localhost:$PORT in your browser"
echo ""

python3 app.py
