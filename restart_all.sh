#!/bin/zsh
cd "/Users/satwik/Documents/New GenAI/academic-assistant" || exit 1
pkill -f "uvicorn.*8013" 2>/dev/null || true
pkill -f "vite.*8506" 2>/dev/null || true
pkill -f "streamlit.*8506" 2>/dev/null || true
sleep 1
uvicorn backend.api:app --port 8013 &
cd frontend || exit 1

if [ ! -d "node_modules" ]; then
	npm install || exit 1
fi

npm run dev -- --host 0.0.0.0 --port 8506 --strictPort
