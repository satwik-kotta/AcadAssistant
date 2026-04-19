# 🐛 Code Issues & Fixes

## Critical Issues Found

### Issue 1: Missing `/feedback` Endpoint in Backend
**Severity:** 🔴 CRITICAL  
**Location:** [backend/api.py](backend/api.py)  
**Problem:** Frontend calls `POST /feedback` but endpoint doesn't exist  
**Impact:** User feedback loop completely broken

**Current Frontend Code:**
```python
r = httpx.post(f"{API}/feedback", json={...})
```

**Missing Backend Code:**
```python
# This endpoint is missing!
@app.post("/feedback")
def provide_feedback(plan_id: int, feedback: str, start_date: str):
    from backend.feedback import replan
    result = replan(plan_id, feedback, start_date)
    return result
```

**Fix:** Add endpoint to `api.py` after `/plan` endpoint

---

### Issue 2: Import Missing in api.py
**Severity:** 🟡 MEDIUM  
**Problem:** `schedule_plan` and `feedback` module not imported  
**Current:** Only imports happening:
```python
from backend.ingest import ingest_document
from backend.planner import generate_plans
from backend.scorer import select_best_plan
from backend.calendar_tool import schedule_plan  # ✓ Good
# from backend.feedback import replan  # ✗ Missing!
```

**Fix:** Add import for feedback module

---

### Issue 3: Vectorstore Not Initialized on First Run
**Severity:** 🟡 MEDIUM  
**Problem:** `retriever.py` fails if vectorstore doesn't exist yet  
**Error:** `FileNotFoundError: vectorstore/index`

**Current Code:**
```python
def retrieve_context(query: str, k: int = 5) -> str:
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    store = FAISS.load_local(VECTORSTORE_PATH, ...)  # ✗ Fails if not exists
    docs = store.similarity_search(query, k=k)
```

**Fix:** Add check for vectorstore existence, return empty context if not found

---

### Issue 4: No Request Model for Feedback
**Severity:** 🟡 MEDIUM  
**Problem:** Frontend sends feedback but no Pydantic model validates it  

**Fix:** Add FeedbackRequest model

---

### Issue 5: No Error Handling
**Severity:** 🟠 HIGH  
**Problem:** No try-catch blocks anywhere  
**Impact:** If OpenAI API fails, entire request fails with cryptic error

**Examples of missing error handling:**
```python
# What if OpenAI API is down?
response = client.chat.completions.create(...)

# What if file upload fails?
with open(dest, "wb") as f:
    shutil.copyfileobj(file.file, f)

# What if Google Calendar auth fails?
creds = flow.run_local_server(port=0)
```

---

### Issue 6: Database Session Not Closed
**Severity:** 🟠 HIGH  
**Problem:** Sessions created but not always closed (resource leak)

**Example:**
```python
session = Session()
db_plan = session.query(StudyPlan).filter_by(id=plan_id).first()
# ... no finally block to close
```

**Fix:** Use context manager or try-finally

---

### Issue 7: Calendar Event Deletion Failures Silenced
**Severity:** 🟡 MEDIUM  
**Problem:** If calendar event can't be deleted, it's silently ignored  

```python
try:
    service.events().delete(...).execute()
except Exception:  # ✗ Too broad, hides bugs
    pass
```

**Fix:** Log failures, retry logic, better exception handling

---

### Issue 8: No Input Validation
**Severity:** 🟡 MEDIUM  
**Problem:** No validation on user inputs  

**Examples:**
```python
# What if daily_hours is -5?
daily_hours: float = 2.0

# What if start_date is "not-a-date"?
start_date: str = "2025-07-14"

# What if weak_subjects is 100 items long?
weak_subjects: list[str] = []
```

---

### Issue 9: Hardcoded User ID
**Severity:** 🔴 CRITICAL  
**Problem:** All plans saved to `user_id="default"`  

```python
class StudyPlan(Base):
    user_id = Column(String, default="default")  # ✗ Always "default"
```

**Fix:** Implement user identification (API key or auth)

---

### Issue 10: No API Key or Authentication
**Severity:** 🔴 CRITICAL  
**Problem:** Anyone can call endpoints, delete other users' plans  

**Current:** No auth middleware or api_key checking

**Fix:** Add FastAPI security dependencies

---

## Priority Order for Fixes

### Must Fix (to get system working):
1. ✅ Add `/feedback` endpoint
2. ✅ Add feedback import
3. ✅ Fix vectorstore initialization
4. ✅ Add FeedbackRequest model
5. ✅ Add basic error handling

### Should Fix (for production):
6. Add input validation
7. Add user authentication
8. Fix database session management
9. Better error messages
10. Logging

### Nice to Have:
11. Rate limiting
12. Caching
13. Request timeouts
14. Monitoring

