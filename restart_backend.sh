#!/bin/zsh
cd "/Users/satwik/Documents/New GenAI/academic-assistant" || exit 1
source "/Users/satwik/Documents/New GenAI/.venv/bin/activate" || exit 1
pkill -f "uvicorn.*8013" 2>/dev/null || true
python -m uvicorn backend.api:app --port 8013
