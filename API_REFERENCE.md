# 🔌 AI Academic Assistant - Complete API Reference

**Backend URL:** http://localhost:8000  
**Documentation:** http://localhost:8000/docs (Swagger UI)  
**Alternative Docs:** http://localhost:8000/redoc (ReDoc)

---

## 📋 Endpoint Overview

```
POST /upload              Upload & ingest PDF documents
POST /plan                Generate personalized study plans
POST /feedback            Update plan based on user feedback
GET  /docs               Auto-generated API documentation
GET  /redoc              Alternative documentation format
```

---

## ✅ Implemented Endpoints

### 1. POST /upload - Upload Academic Documents

**Purpose:** Upload PDF documents (syllabus, notes, assignments) and add to vector database

**Request:**
```http
POST /upload
Content-Type: multipart/form-data

file: <PDF file>
```

**Example using curl:**
```bash
curl -X POST http://localhost:8000/upload \
  -F "file=@syllabus.pdf"
```

**Example using Python:**
```python
import httpx

with open("syllabus.pdf", "rb") as f:
    files = {"file": ("syllabus.pdf", f, "application/pdf")}
    response = httpx.post("http://localhost:8000/upload", files=files)
    print(response.json())
```

**Response (Success):**
```json
{
  "message": "Uploaded and ingested",
  "filename": "syllabus.pdf",
  "chunks": 42
}
```

**Response (Error):**
```json
{
  "detail": "Failed to upload document: file not found"
}
```

**Status Codes:**
| Code | Meaning |
|------|---------|
| 200  | Success - document ingested |
| 500  | Server error (invalid PDF, API error) |

**What happens internally:**
1. File saved to `uploads/syllabus.pdf`
2. PDF parsed into 42 chunks (500 chars each)
3. Chunks converted to embeddings via OpenAI
4. Embeddings stored in FAISS vector database
5. Ready for semantic search

---

### 2. POST /plan - Generate Study Plan

**Purpose:** Generate personalized study plans based on constraints and uploaded documents

**Request Body:**
```json
{
  "request": "Create a study plan for DSA course",
  "daily_hours": 2.5,
  "weak_subjects": ["Dynamic Programming", "Graphs"],
  "start_date": "2025-04-14",
  "start_time": "09:00"
}
```

**Field Descriptions:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `request` | string | required | Natural language request for plan |
| `daily_hours` | float | 2.0 | Daily available study hours |
| `weak_subjects` | array | [] | Topics to prioritize |
| `start_date` | string | today | Start date (YYYY-MM-DD) |
| `start_time` | string | "09:00" | Start time (HH:MM, 24-hour) |

**Example using curl:**
```bash
curl -X POST http://localhost:8000/plan \
  -H "Content-Type: application/json" \
  -d '{
    "request": "Plan my study week",
    "daily_hours": 2.0,
    "weak_subjects": ["mathematics"],
    "start_date": "2025-04-14",
    "start_time": "09:00"
  }'
```

**Example using Python:**
```python
import httpx

payload = {
    "request": "Plan my study week",
    "daily_hours": 2.0,
    "weak_subjects": ["mathematics"],
    "start_date": "2025-04-14",
    "start_time": "09:00"
}

response = httpx.post("http://localhost:8000/plan", json=payload, timeout=120)
data = response.json()
print(data["plan"]["plan_name"])
print(f"Calendar events created: {data['calendar_events']}")
```

**Response (Success):**
```json
{
  "plan": {
    "plan_name": "Intensive Mathematics Bootcamp",
    "strategy": "Focus on weak areas with spaced repetition",
    "score": 85,
    "days": [
      {
        "day": "Monday",
        "tasks": [
          {
            "topic": "Linear Equations",
            "duration_minutes": 60,
            "priority": "high"
          },
          {
            "topic": "Review: Quadratic Forms",
            "duration_minutes": 30,
            "priority": "medium"
          }
        ]
      }
    ]
  },
  "calendar_events": 7,
  "plan_id": 42
}
```

**What happens internally:**
1. Retrieves 5 most relevant document chunks via semantic search
2. Sends to GPT-4o-mini with constraints as context
3. LLM generates 3 alternative plans as JSON
4. Scorer evaluates plans:
   - Penalty if daily workload exceeds available hours
   - Bonus for prioritizing weak subjects
5. Best plan selected and saved to database
6. Each task scheduled as Google Calendar event
7. Plan ID returned for future reference

**Status Codes:**
| Code | Meaning |
|------|---------|
| 200  | Success - plan created and scheduled |
| 500  | Server error (API timeout, no documents uploaded, etc.) |

---

### 3. POST /feedback - Update Plan Based on Feedback

**Purpose:** Modify existing plan based on user feedback (e.g., "too much workload")

**Request Body:**
```json
{
  "plan_id": 42,
  "feedback": "Too much workload, I need to reduce by half",
  "start_date": "2025-04-21",
  "start_time": "09:00"
}
```

**Field Descriptions:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `plan_id` | integer | yes | ID from `/plan` response |
| `feedback` | string | yes | Natural language feedback |
| `start_date` | string | yes | When to reschedule from (YYYY-MM-DD) |
| `start_time` | string | no | Start time for rescheduled tasks (HH:MM) |

**Feedback Examples:**
```
"Too much workload, reduce by half"              → Intent: overloaded
"I missed yesterday's tasks"                      → Intent: missed
"I'm struggling with calculus, focus more on it" → Intent: other
"Can we extend this over more days?"              → Intent: overloaded
```

**Example using curl:**
```bash
curl -X POST http://localhost:8000/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "plan_id": 42,
    "feedback": "Too much workload",
    "start_date": "2025-04-21",
    "start_time": "09:00"
  }'
```

**Example using Python:**
```python
import httpx

payload = {
    "plan_id": 42,
    "feedback": "Too much workload, give me less per day",
    "start_date": "2025-04-21"
}

response = httpx.post("http://localhost:8000/feedback", json=payload)
updated = response.json()
print(f"Tasks rescheduled to {updated['calendar_events']} events")
```

**Response (Success):**
```json
{
  "updated_plan": {
    "plan_name": "Intensive Mathematics Bootcamp (Reduced)",
    "strategy": "Spread workload more evenly, focus on key concepts",
    "days": [
      {
        "day": "Monday",
        "tasks": [
          {
            "topic": "Linear Equations",
            "duration_minutes": 45,
            "priority": "high"
          }
        ]
      }
    ]
  },
  "calendar_events": 10
}
```

**Response (Error - Plan Not Found):**
```json
{
  "detail": "Plan with id 999 not found"
}
```

**What happens internally:**
1. Loads existing plan from database using plan_id
2. Detects feedback intent:
   - "overloaded" → Reduces tasks 20-30%, extends across more days
   - "missed" → Shifts remaining tasks forward
   - "other" → Passes feedback to LLM for custom handling
3. LLM generates updated plan maintaining same total content
4. Deletes old calendar events
5. Creates new calendar events with rescheduled times
6. Updates database with new plan

**Status Codes:**
| Code | Meaning |
|------|---------|
| 200  | Success - plan updated and rescheduled |
| 400  | Bad request (invalid plan_id, parse error) |
| 500  | Server error (database error, calendar sync failed) |

---

## 📊 Data Models

### PlanRequest (POST /plan body)
```python
{
    "request": str,
    "daily_hours": float = 2.0,
    "weak_subjects": list[str] = [],
    "start_date": str = "2025-07-14",
    "start_time": str = "09:00"
}
```

### FeedbackRequest (POST /feedback body)
```python
{
    "plan_id": int,
    "feedback": str,
    "start_date": str,
    "start_time": str = "09:00"
}
```

### StudyPlan (Database)
```python
{
    "id": int (primary key),
    "user_id": str (default: "default"),
    "plan_json": str (full plan as JSON),
    "score": int (quality score),
    "created_at": datetime
}
```

### Task (Database)
```python
{
    "id": int (primary key),
    "plan_id": int (foreign key),
    "day": str ("Monday", "Tuesday", etc),
    "topic": str (study topic),
    "duration_minutes": int,
    "calendar_event_id": str (Google Calendar event ID),
    "status": str ("pending", "completed", "skipped")
}
```

### Plan Structure (JSON)
```json
{
  "plan_name": "string",
  "strategy": "string",
  "score": integer,
  "days": [
    {
      "day": "Monday",
      "tasks": [
        {
          "topic": "string",
          "duration_minutes": integer,
          "priority": "high|medium|low"
        }
      ]
    }
  ]
}
```

---

## 🔄 Typical Workflow

```
1. USER UPLOADS DOCUMENTS
   POST /upload with PDF
   → Chunks added to vector store
   → Confirms: "42 chunks ingested"

2. USER REQUESTS PLAN
   POST /plan with constraints
   → System retrieves relevant context
   → LLM generates 3 plans
   → Scorer evaluates
   → Best plan selected
   → Calendar events created
   → Returns plan + plan_id

3. TASKS APPEAR IN CALENDAR
   → User sees events in Google Calendar
   → Reminders set for 15 minutes before

4. USER GIVES FEEDBACK (optional)
   POST /feedback with plan_id + feedback
   → System redetects intent
   → LLM adjusts plan
   → Old calendar events deleted
   → New events created
   → Updated plan returned

5. REPEAT FEEDBACK
   → User can give feedback multiple times
   → Each call reschedules from new start_date
```

---

## ⚡ Performance & Limits

| Metric | Value | Notes |
|--------|-------|-------|
| Max PDF size | ~50 MB | Depends on memory |
| Max chunks per upload | ~1000 | Limited by vectorstore |
| Plan generation time | 30-60 sec | Includes LLM API call |
| Max concurrent requests | 1 | FastAPI default (can increase) |
| Vectorstore search time | <100 ms | FAISS is very fast |
| Calendar API rate limit | 1000/day | Google's limit |

---

## 🐛 Error Handling

### Common Errors & Solutions

**Error: 500 - "OPENAI_API_KEY not found"**
```
Cause: .env file missing or OPENAI_API_KEY not set
Fix: 
1. Create .env file in project root
2. Add: OPENAI_API_KEY=sk-xxxxx
3. Restart backend
```

**Error: 500 - "No documents uploaded yet"**
```
Cause: Trying to generate plan without uploading documents first
Fix:
1. POST /upload with PDF first
2. Wait for confirmation
3. Then POST /plan
```

**Error: 400 - "Plan with id 999 not found"**
```
Cause: Invalid plan_id in feedback request
Fix:
1. Check plan_id from /plan response
2. Make sure database file exists (db/assistant.db)
3. Use correct plan_id
```

**Error: 500 - "Failed to upload document: file not found"**
```
Cause: File doesn't exist or can't be read
Fix:
1. Check file exists
2. Ensure file is valid PDF
3. Check file permissions
```

**Error: 500 - "Error retrieving context: failed to load index"**
```
Cause: FAISS vectorstore corrupted
Fix:
1. Delete vectorstore/index/ directory
2. Re-upload all documents
3. Try again
```

---

## 🔐 Authentication (Future)

**Current State:**
- ❌ No authentication - anyone can call endpoints
- ✅ API keys properly configured
- ❌ No rate limiting

**To add in future:**
```python
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

@app.post("/plan")
async def create_plan(req: PlanRequest, api_key: str = Depends(api_key_header)):
    # Verify API key
    if api_key != os.getenv("VALID_API_KEY"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    # ... rest of function
```

---

## 📈 Example End-to-End Session

### Step 1: Upload Document
```bash
curl -X POST http://localhost:8000/upload \
  -F "file=@DSA_Syllabus.pdf"
```
Response:
```json
{"message": "Uploaded and ingested", "chunks": 34, "filename": "DSA_Syllabus.pdf"}
```

### Step 2: Generate Plan
```bash
curl -X POST http://localhost:8000/plan \
  -H "Content-Type: application/json" \
  -d '{
    "request": "Create 2-week study plan for DSA",
    "daily_hours": 3,
    "weak_subjects": ["Dynamic Programming"],
    "start_date": "2025-04-14",
    "start_time": "14:00"
  }' \
  -w "\nHTTP Status: %{http_code}\n"
```
Response (after 45 seconds):
```json
{
  "plan": {
    "plan_name": "Advanced DSA Mastery",
    "strategy": "Focus on DP and Graph problems",
    "score": 92,
    "days": [...]
  },
  "calendar_events": 14,
  "plan_id": 7
}
```

### Step 3: Check Calendar
- Open https://calendar.google.com
- See 14 new events like "Study: Arrays", "Study: DP Basics", etc.

### Step 4: Give Feedback
```bash
curl -X POST http://localhost:8000/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "plan_id": 7,
    "feedback": "Too much, I can only do 2 hours daily",
    "start_date": "2025-04-21"
  }'
```
Response:
```json
{
  "updated_plan": {...},
  "calendar_events": 21
}
```

### Step 5: Verify Update
- Calendar automatically updated
- Old events deleted
- New events at reduced workload
- Time spread over more days

---

## 🧪 Testing with Postman

**1. Create Postman Collection:**
```
Collection: AI Academic Assistant
├─ POST /upload
│  ├─ Body: form-data with file
│  └─ Save response
├─ POST /plan
│  ├─ Body: raw JSON (use plan_id from upload response)
│  ├─ Params: daily_hours, start_date, weak_subjects
│  └─ Save plan_id
└─ POST /feedback
   ├─ Body: raw JSON with plan_id
   └─ Test different feedback types
```

**2. Environment Variables:**
```json
{
  "base_url": "http://localhost:8000",
  "plan_id": "{{response.body.plan_id}}"
}
```

---

## 🚀 Deployment Considerations

**For localhost testing:**
```bash
python -m uvicorn backend.api:app --reload --port 8000
```

**For production (Heroku):**
```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.api:app
```

**For production (Docker):**
```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "backend.api:app"]
```

---

## 📚 Related Documentation

- [PROJECT_ANALYSIS.md](PROJECT_ANALYSIS.md) - Full architecture
- [QUICK_START.md](QUICK_START.md) - Setup guide
- [BUG_FIXES.md](BUG_FIXES.md) - Issues & solutions
- [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) - Current status

