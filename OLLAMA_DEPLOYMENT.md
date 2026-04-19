# Ollama Integration Deployment Guide

**Date**: April 18, 2026  
**Status**: ✅ IMPLEMENTED & READY

---

## Overview

The academic-assistant now runs on an **Ollama-first pipeline** with Gemini fallback. All LLM operations (planning, document analysis, question routing, replanning) use Ollama for local inference, with graceful fallback to Gemini API if needed.

### Benefits
- 🚀 **Local inference**: No external API calls for most operations
- 💰 **Cost reduction**: Fewer Gemini API calls
- 🔒 **Privacy**: Sensitive documents analyzed locally
- 📡 **Offline-capable**: Works without internet for many tasks
- ♻️ **Graceful degradation**: Automatic fallback to Gemini or heuristics

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        USER (Streamlit)                     │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                    FastAPI Backend (8013)                   │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐  │
│  │ Planner │  │Feedback  │  │Knowledge │  │  Ingest     │  │
│  │         │  │(Replan)  │  │ Router   │  │ (Analysis)  │  │
│  └────┬────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘  │
│       │            │             │               │          │
│       └────────────┴─────────────┴───────────────┘          │
│                    │                                         │
│       ┌────────────▼──────────────┐                          │
│       │   LLM Router (NEW)        │                          │
│       │  - llm_call()             │                          │
│       │  - llm_json()             │                          │
│       │  - ChatSession()          │                          │
│       └────────────┬──────────────┘                          │
│                    │                                         │
│       ┌────────────┴─────────────────────────────┐           │
│       │                                           │           │
│ ┌─────▼──────────────┐          ┌────────────────▼──────┐   │
│ │  OLLAMA (:11434)   │          │  GEMINI API           │   │
│ │  local inference   │          │  (fallback/timeout)   │   │
│ │  ✓ llama3.1        │          │  (free tier quota)    │   │
│ │  ✓ Deterministic   │          └───────────────────────┘   │
│ │  ✓ Private         │                                       │
│ └────────────────────┘                                       │
│                                                              │
│ DATABASE (SQLite)  │  VECTORSTORE (FAISS)  │  CALENDAR      │
│ - Plans            │  - Document chunks    │  - Google Cal  │
│ - Tasks            │  - Embeddings         │  - Events      │
│ - Documents        │  - Similarity search  │                │
└──────────────────────────────────────────────────────────────┘
```

---

## Implementation Details

### 1. Ollama-First Router: `backend/llm_router.py`

**Modified functions:**
- `llm_call()` - Single entry point for all LLM calls
- `llm_json()` - JSON parsing wrapper
- `ChatSession` - NEW: Multi-turn conversation handler

**Behavior:**
```python
llm_call(prompt, system, temperature)
  ├─ USE_OLLAMA=true?
  │  ├─ POST to http://localhost:11434/api/chat
  │  │  ├─ 200 OK → Return Ollama response ✓
  │  │  └─ Error/Timeout → Continue ↓
  └─ genai.GenerativeModel().generate_content()
     ├─ Response OK → Return Gemini response ✓
     └─ API Error → Raise exception (handle locally) ↓
```

### 2. All LLM Operations Using Router

| Module | Function | Use Case | Fallback |
|--------|----------|----------|----------|
| `knowledge_router.py` | `classify_question()` | Route q to focused/recall/RAG | Heuristic |
| `planner.py` | `generate_plans()` | Create 3 study plans | Hardcoded plans |
| `feedback.py` | `replan()` | Update plan on user feedback | Heuristic replan |
| `enhanced_ingest.py` | `analyse_document()` | Extract topics/prereqs/analysis | Minimal analysis |
| `study_session.py` | `build_dependency_graph()` | Build topic prerequisites | Empty graph |
| `agent.py` | `answer_from_documents()` | Q&A from uploaded docs | Document snippets |

### 3. Configuration: `.env`

```env
# LLM Configuration
USE_OLLAMA=true
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1

# Gemini Fallback (for now disabled due to quota)
GEMINI_API_KEY=AIzaSyDuSVEe2wo9adFlUhzhtXwrw2_ieTU-0Mw
GEMINI_MODEL=models/gemini-2.0-flash

# Other services
EMBEDDINGS_PROVIDER=local
CALENDAR_ENABLED=false
DB_URL=sqlite:///./db/assistant.db
```

---

## Getting Started

### Step 1: Start Ollama

```bash
# Terminal 1 - Start Ollama server
ollama serve

# Verify Ollama is running (in another terminal)
ollama list                    # Shows available models
curl http://localhost:11434/api/tags  # API check
```

### Step 2: Ensure llama3.1 Model

```bash
# Pull the model (one-time setup)
ollama pull llama3.1

# Verify
ollama list
# Expected output: llama3.1:latest  12GB  2 days ago
```

### Step 3: Start Services

```bash
# Terminal 2 - Start backend
cd /path/to/academic-assistant
zsh restart_backend.sh

# Terminal 3 - Start frontend
zsh restart_frontend.sh

# Or use restart_all.sh for both
zsh restart_all.sh
```

### Step 4: Access the App

- **Frontend (Streamlit)**: http://localhost:8506
- **Backend API**: http://localhost:8013/docs (Swagger UI)
- **Ollama API**: http://localhost:11434/api/tags

---

## Testing the Pipeline

### Test 1: Basic LLM Call

```bash
curl -X POST http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.1",
    "messages": [{"role": "user", "content": "Say hello"}],
    "stream": false
  }'
```

### Test 2: Python Quick Test

```python
from backend.llm_router import llm_call, llm_json

# Test 1: Simple call
result = llm_call("What is Python?", temperature=0.3)
print(result)

# Test 2: JSON parsing
result = llm_json('{"test": "value"}', temperature=0.1)
print(result)

# Test 3: Classification
from backend.knowledge_router import classify_question
result = classify_question(
    "What is recursion?",
    today_topics=["Loops", "Functions"],
    previous_topics=["Variables"]
)
print(f"Mode {result['mode']}: {result['mode_name']}")
```

### Test 3: Via Frontend

1. Open http://localhost:8506
2. Upload a PDF document
3. Click "Generate Plan"
4. Ask a question about the document
5. Watch as Ollama processes your request locally!

---

## Monitoring & Debugging

### Check Ollama Status

```bash
# Active connections
lsof -i :11434

# Process info
ps aux | grep ollama

# Logs
tail -f ~/.ollama/logs/server.log

# Model info
ollama list
```

### Check Backend Status

```bash
# Service running
lsof -i :8013

# API health
curl http://localhost:8013/health

# Logs (if running in terminal)
# See real-time output in the running terminal
```

### Enable Debug Logging

Add to `.env`:
```env
DEBUG=true
LOG_LEVEL=DEBUG
```

View logs:
```bash
tail -f backend.log
```

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "Port 11434 already in use" | Ollama already running | `killall ollama && ollama serve` |
| "Connection refused" | Ollama not started | Start with `ollama serve` |
| Slow responses | Model warming up / CPU inference | Normal for CPU; responses faster after first call |
| "Quota exceeded" (Gemini) | Free tier limit hit | Use Ollama-only mode (recommended) |
| LLM timeout | Ollama taking too long | Increase timeout in `llm_router.py` |

---

## Performance Characteristics

### Ollama Performance (llama3.1)
- **First call**: ~5-10 seconds (model warming up)
- **Subsequent calls**: ~1-3 seconds per 100 tokens
- **Memory**: ~8GB on disk, ~4GB loaded
- **CPU**: Single core usage, can throttle for responsiveness

### Gemini Performance (Fallback)
- **Average**: 0.5-1 second
- **Cost**: Free tier (~100 calls/day), then paid
- **Quota**: Currently exceeded (rate limited)

### Recommendation
- ✅ Use **Ollama** for: Regular planning, analysis, routing
- 🔄 Use **Gemini** fallback for: Critical operations, when Ollama overloaded

---

## API Endpoints

### Backend Health Check
```
GET /health
```

### Chat Endpoint
```
POST /chat
Headers: Content-Type: application/json
Body: {
  "message": "string",
  "history": [...],
  "session_state": {...}
}
Response: {
  "reply": "string",
  "history": [...],
  "updated_plan": {...}
}
```

### Plan Generation
```
POST /generate_plan
Body: {
  "request": "string",
  "daily_hours": 2,
  "days_off": ["Sunday"],
  ...
}
```

See full API: http://localhost:8013/docs (Swagger)

---

## Troubleshooting Checklist

- [ ] Ollama running on port 11434
- [ ] llama3.1 model downloaded (`ollama list`)
- [ ] Backend running on port 8013
- [ ] Frontend running on port 8506
- [ ] Database created (`db/assistant.db` exists)
- [ ] LLM router configured with `USE_OLLAMA=true`
- [ ] Can access Swagger API docs at http://localhost:8013/docs
- [ ] Can see Streamlit app at http://localhost:8506

---

## What's New in This Release

✅ **Unified LLM Interface**
- Single `llm_call()` entry point for all operations
- Automatic provider selection and fallback

✅ **Ollama-First Strategy**
- Local inference for privacy and cost-reduction
- Graceful fallback to Gemini if needed

✅ **Multi-turn Conversations**
- `ChatSession` class for stateful chat
- Conversation history management for both providers

✅ **Error Resilience**
- All LLM calls wrapped in try-except
- Local heuristics for when both providers fail
- Meaningful error messages instead of crashes

✅ **Updated Modules**
- `feedback.py`: Uses LLM router (thread-safe)
- `enhanced_ingest.py`: Document analysis via router
- `agent.py`: Fallback Q&A using router
- `knowledge_router.py`: Classification via router
- `planner.py`: Planning via router
- `study_session.py`: Dependency graphs via router

---

## Next Steps

1. **Warm up Ollama** - Run a few test queries to cache the model
2. **Test all features** - Upload docs, generate plans, ask questions
3. **Monitor performance** - Check response times and adjust timeouts if needed
4. **Setup cost tracking** - If using Gemini fallback, monitor API usage
5. **Enable calendar** - Optional: Connect Google Calendar for event scheduling

---

## Support & Feedback

For issues or improvements:
1. Check logs: `tail -f backend.log` or Ollama server output
2. Review error messages in Streamlit UI
3. Check API docs at http://localhost:8013/docs
4. Verify configuration in `.env`

---

**Implementation Date**: April 18, 2026  
**Status**: Production-ready ✅  
**Last Updated**: April 18, 2026

---
