# 🚀 Ollama Pipeline - Quick Reference

## For Developers

### The New LLM Router Flow

```python
from backend.llm_router import llm_call, llm_json, ChatSession

# 1. SIMPLE CALL - Auto provider selection
response = llm_call(
    prompt="What is Python?",
    system="You are helpful.",
    temperature=0.3
)
# Tries: Ollama first → Gemini → Local heuristics

# 2. JSON RESPONSE - Auto parsing
result = llm_json(
    prompt='{"topic": "Python"} - tell me about it',
    system="Return only valid JSON",
    temperature=0.1
)
# Result: {'topic': 'Python', ...}

# 3. MULTI-TURN CONVERSATION
chat = ChatSession(system_instruction="You are an expert tutor")
response1 = chat.send_message("What is recursion?")
response2 = chat.send_message("Give me an example")
response3 = chat.send_message("How does it relate to loops?")
# History maintained across both Ollama and Gemini
```

---

## Updated Functions Using Pipeline

### ✅ Knowledge Router
```python
from backend.knowledge_router import classify_question

mode = classify_question(
    question="What is inheritance?",
    today_topics=["OOP Basics"],
    previous_topics=["Classes"],
    dependency_graph={"OOP Basics": ["Classes"]}
)
# Mode 1: Focused   (today's material)
# Mode 2: Recall    (prior knowledge)
# Mode 3: RAG       (external knowledge)
```

### ✅ Document Analysis
```python
from backend.enhanced_ingest import analyse_document

analysis = analyse_document(
    full_text="Python is a programming language...",
    filename="python_intro.pdf"
)
# Returns: {
#   "document_type": "notes",
#   "topics_covered": [...],
#   "prerequisites": [...],
#   "summary": "..."
# }
```

### ✅ Plan Generation
```python
from backend.planner import generate_plans

plans = generate_plans(
    user_request="I need to learn Python in 2 weeks",
    constraints={
        "daily_hours": 2,
        "days_off": ["Sunday"],
        "weak_subjects": ["Data Structures"]
    }
)
# Returns: [plan1, plan2, plan3]
```

### ✅ Replanning
```python
from backend.feedback import replan

result = replan(
    plan_id=42,
    feedback="I'm overloaded, too much Monday work",
    start_date="2026-04-18",
    start_time="09:00"
)
# Returns: {"updated_plan": {...}, "calendar_events": 15}
```

### ✅ Dependency Graphs
```python
from backend.knowledge_router import build_dependency_graph

graph = build_dependency_graph([
    {"topic": "Classes", "difficulty": "intermediate"},
    {"topic": "OOP", "difficulty": "advanced"},
    {"topic": "Variables", "difficulty": "beginner"}
])
# Returns: {
#   "OOP": ["Classes"],
#   "Classes": ["Variables"],
#   "Variables": []
# }
```

---

## Environment Setup

### .env (Already Configured)
```env
USE_OLLAMA=true                          # Enable Ollama (primary)
OLLAMA_BASE_URL=http://localhost:11434   # Ollama server
OLLAMA_MODEL=llama3.1                    # Model to use
GEMINI_API_KEY=***                       # Fallback API key
```

### One-Line Setup
```bash
# Start everything
ollama serve &          # Terminal 1 (in background)
sleep 5
zsh restart_all.sh      # Terminal 2
```

### Check Everything Works
```bash
# Backend health
curl http://localhost:8013/health

# Ollama health
curl http://localhost:11434/api/tags

# Frontend
open http://localhost:8506
```

---

## Testing the Pipeline

### Quick Test in Python
```python
import sys
sys.path.insert(0, '/path/to/academic-assistant')

# Test 1: Basic LLM
from backend.llm_router import llm_call
response = llm_call("Say hello")
print(f"✓ LLM call: {response}")

# Test 2: JSON
from backend.llm_router import llm_json
result = llm_json('{"ok": true}')
print(f"✓ JSON parse: {result}")

# Test 3: Classification
from backend.knowledge_router import classify_question
result = classify_question("What is Python?", ["Python"], [])
print(f"✓ Classification: Mode {result['mode']}")
```

---

## Error Handling

All pipeline functions now have built-in fallbacks:

```python
# Code auto-handles:
# ✓ Ollama timeout        → Falls back to Gemini
# ✓ Gemini rate limit     → Falls back to heuristics
# ✓ JSON parsing errors   → Returns empty/default
# ✓ Network errors        → Uses local logic

try:
    response = llm_call("...")
except Exception as e:
    # This rarely happens - fallbacks catch most errors
    logger.error(f"All LLM providers failed: {e}")
```

---

## Performance Tips

### For Faster Ollama Responses
1. **Warm up before use**: First call takes 5-10s
2. **Keep model loaded**: Running Ollama continuously is fastest
3. **Batch requests**: Multiple calls more efficient than single large prompt
4. **Adjust temperature**: Lower (0.1-0.3) is faster, higher (0.7-0.9) slower

### For Fallback to Gemini
1. **Check budget**: Gemini free tier is limited
2. **Monitor usage**: Watch API call counts in Google Cloud Console
3. **Cache when possible**: Reuse responses for repeated questions
4. **Use Ollama first**: Already optimized for that

---

## Configuration Options

### Timeout Settings (in seconds)
```python
# llm_router.py - adjust if needed
httpx.post(..., timeout=120)  # Ollama timeout
# Increase if getting "timed out" errors
# Decrease if waiting too long
```

### Temperature (Creativity)
```
Less random:    0.0 - 0.3  (planning, analysis)
Balanced:       0.3 - 0.7  (routing, Q&A)
More creative:  0.7 - 1.0  (brainstorming)
```

### Model Selection
```env
# Available locally
OLLAMA_MODEL=llama3.1      # Default, 12GB
OLLAMA_MODEL=llama2        # Alternative, 7GB (less capable)
OLLAMA_MODEL=mistral       # Alternative, 5GB (fast)

# Need to: ollama pull <modelname>
```

---

## Debugging

### Check Provider Being Used
```python
from backend.llm_router import USE_OLLAMA
print(f"Ollama enabled: {USE_OLLAMA}")

import logging
logging.basicConfig(level=logging.DEBUG)
# Watch logs for: "[LLM] Ollama responded" or "[LLM] Ollama failed"
```

### Test Ollama Directly
```bash
# Terminal
ollama serve

# Another terminal - test API
curl http://localhost:11434/api/chat -d '{
  "model": "llama3.1",
  "messages": [{"role": "user", "content": "hi"}],
  "stream": false
}'
```

### Test Gemini Fallback
```python
# Temporarily disable Ollama
import os
os.environ['USE_OLLAMA'] = 'false'

from backend.llm_router import llm_call
response = llm_call("test")  # Will use Gemini
```

---

## Migration Notes

### For Existing Code
- ✅ All existing imports still work
- ✅ No breaking changes to function signatures
- ✅ Behavior is same but now uses Ollama-first

### If You Added Code That Calls Gemini Directly
```python
# OLD (still works but bypasses pipeline):
from backend.gemini_config import get_gemini_model
model = get_gemini_model()
response = model.generate_content(prompt)

# NEW (use these instead):
from backend.llm_router import llm_call, llm_json
response = llm_call(prompt)              # String response
response = llm_json(prompt)              # JSON response
```

### Migrate Your Code
```python
# Before:
from backend.gemini_config import get_gemini_model
model = get_gemini_model()
result = model.generate_content(prompt, generation_config={...})

# After:
from backend.llm_router import llm_call
result = llm_call(prompt, temperature=0.5)
```

---

## Architecture Diagram

```
┌─────────────────────────────────────┐
│   User Request (Streamlit)          │
└────────────────┬────────────────────┘
                 │
         ┌───────▼────────┐
         │  Business Logic│ (planning, routing, analysis)
         │                │
         └───────┬────────┘
                 │
    ┌────────────▼────────────┐
    │   LLM Router Entry      │
    │  llm_call() /llm_json() │
    └────────────┬────────────┘
                 │
┌────────────────┴─────────────────┐
│                                  │
▼                                  ▼
OLLAMA (:11434)                   GEMINI API
(Local, free, fast)              (Cloud, paid, reliable)
│                                  │
└────────────────┬─────────────────┘
                 │
                 ▼
            Response to User
```

---

## Quick Command Reference

```bash
# Start services
ollama serve                    # Terminal 1
cd academic-assistant && zsh restart_all.sh    # Terminal 2

# Check status
lsof -i :11434,8013,8506      # All ports

# Stop services
killall -9 python streamlit ollama

# View logs
tail -f ~/.ollama/logs/server.log    # Ollama
# Backend logs in running terminal

# Restart backend only
cd academic-assistant && zsh restart_backend.sh

# Restart frontend only  
cd academic-assistant && zsh restart_frontend.sh

# Run tests
python -m pytest tests/

# Check API
curl http://localhost:8013/docs
open http://localhost:8506
```

---

## Understanding Call Sequences

### Study Plan Generation Flow
```
User: "Create a study plan"
  ↓
execute_tool(generate_study_plan)
  ↓
generate_plans() [planner.py]
  ↓
llm_json() [llm_router.py]
  ├─ llm_call() with JSON system prompt
  ├─ Try: Ollama @ localhost:11434
  │  └─ Wait up to 120s
  └─ Fallback: Gemini API
  └─ Fallback: Hardcoded plans
  ↓
Returns 3 study plans ✓
```

### Question Classification Flow
```
User: "What is Python?"
  ↓
route_and_answer() [knowledge_router.py]
  ↓
classify_question()
  ├─ Heuristic matching (fast)
  │  └─ If score ≥ 0.65, use it
  └─ LLM classification (slower, more accurate)
     └─ llm_json() → Ollama → Gemini
  ↓
Returns mode (1=Focused, 2=Recall, 3=RAG) ✓
```

---

## Best Practices

### DO ✅
- Use llm_call() for text responses
- Use llm_json() for structured data
- Use ChatSession for conversations
- Keep prompts concise and clear
- Reuse classification results when possible
- Monitor API usage if using Gemini

### DON'T ❌
- Don't bypass llm_router for direct provider calls
- Don't hardcode temperature values - use function defaults
- Don't ignore error logs
- Don't leave Ollama running if not needed (uses RAM)

---

## Monitoring Checklist

```
Daily:
  ☐ Ollama running? (lsof -i :11434)
  ☐ Backend running? (lsof -i :8013)
  ☐ Frontend accessible? (http://localhost:8506)

Weekly:
  ☐ Check Gemini API quota (if using fallback)
  ☐ Monitor response times
  ☐ Review error logs

Monthly:
  ☐ Update Ollama model if available
  ☐ Test fallback paths
  ☐ Verify all features still working
```

---

## Support

For issues:
1. Check `/memories/session/ollama_integration_summary.md` for architecture
2. Review `OLLAMA_DEPLOYMENT.md` for detailed setup
3. Check logs for error messages
4. Test with `curl` directly to isolate problems

---

Generated: April 18, 2026  
Pipeline Status: ✅ Fully Operational
