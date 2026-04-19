# 📊 AI Academic Assistant - Complete Technical Analysis

**Date:** April 2026  
**Status:** Core architecture implemented, APIs need configuration

---

## 🎯 Project Summary

This is a **Retrieval-Augmented Generation (RAG) + LLM Planning + Calendar Execution** system that:
1. **Ingest:** Reads academic documents (syllabus, notes, assignments)
2. **Retrieve:** Uses FAISS vector store + embeddings for context
3. **Plan:** Generates 3 alternative study plans using GPT-4o-mini
4. **Score:** Selects best plan based on constraints (workload, weak subjects)
5. **Execute:** Automatically schedules tasks in Google Calendar
6. **Adapt:** Receives feedback and dynamically reschedules

---

## 🔌 APIs REQUIRED & Implementation Status

### ✅ 1. OpenAI API (IMPLEMENTED - Needs Key)
**Purpose:** LLM planning + embeddings generation  
**Current Usage in Code:**
- `planner.py`: `gpt-4o-mini` for generating 3 study plans
- `ingest.py`: `text-embedding-3-small` for document embeddings
- `feedback.py`: `gpt-4o-mini` for replanning based on feedback

**Required Configuration:**
```bash
OPENAI_API_KEY=sk-xxxxx  # Add to .env
```

**Cost Estimate:**
- Embeddings: ~$0.02 per 1M tokens
- GPT-4o-mini: ~$0.15 per 1M input / $0.60 per 1M output tokens

---

### ✅ 2. Google Calendar API (IMPLEMENTED - Needs OAuth Setup)
**Purpose:** Automatically schedule study tasks  
**Current Usage in Code:**
- `calendar_tool.py`: Creates calendar events, handles OAuth flow
- Stores event IDs in database for tracking + deletion

**Required Configuration:**

#### Step 1: Create Google Cloud Project
```
1. Go to https://console.cloud.google.com
2. Create new project "Academic Assistant"
3. Enable "Google Calendar API"
4. Create OAuth 2.0 Client ID (Desktop application)
5. Download credentials as JSON → save as credentials.json
```

#### Step 2: Place in Project Root
```
/your-project/
  ├── credentials.json  ← OAuth credentials file
  └── token.json        ← Auto-generated after first auth
```

**Note:** First run will open browser for OAuth consent screen.

---

### ❌ 3. Google Classroom API (OPTIONAL - Not Implemented)
**Purpose:** Auto-fetch assignments & deadlines  
**Status:** Mentioned in overview but NOT yet built

**If implementing:**
- Add to requirements.txt: `google-classroom` (not standard - would use google-api-python-client)
- Create endpoint: `GET /assignments` to fetch from course
- Integrate with planner constraint detection

---

### ❌ 4. Email/SMS Reminders (OPTIONAL - Not Implemented)
**Purpose:** Send reminders beyond calendar notifications  
**Options:**
- **SendGrid:** For professional email reminders
- **Twilio:** For SMS reminders
- **SMTP:** Simple email via gmail

**Status:** Calendar has built-in 15-min popup reminders; email alerts not added

---

## 📁 Project Architecture

### Current File Structure:
```
academic-assistant/
├── requirements.txt              ← All dependencies
├── backend/
│   ├── api.py                   ← FastAPI server (main endpoints)
│   ├── models.py                ← SQLite + SQLAlchemy ORM
│   ├── ingest.py                ← PDF → Chunks → Embeddings → FAISS
│   ├── retriever.py             ← Query vectorstore for context
│   ├── planner.py               ← LLM generates 3 plans
│   ├── scorer.py                ← Score & select best plan
│   ├── calendar_tool.py         ← Google Calendar integration
│   └── feedback.py              ← Replan based on feedback
├── frontend/
│   └── app.py                   ← Streamlit UI
├── uploads/                     ← Uploaded PDFs stored here
├── db/
│   └── assistant.db             ← SQLite database
└── vectorstore/
    └── index/                   ← FAISS vector store
```

---

## 🔄 Data Flow

```
USER → FRONTEND (Streamlit)
    ↓
[1] Upload documents
    ↓ POST /upload
BACKEND API
    ↓
PDF Loader → Text Splitter → Embeddings (OpenAI)
    ↓
FAISS Vector Store
    ↓
SQLite DB (metadata)

[2] Request study plan
    ↓ POST /plan
Retrieve context from FAISS
    ↓
LLM generates 3 plans
    ↓
Scorer evaluates plans
    ↓
Best plan selected
    ↓
Google Calendar API: Create events
    ↓
SQLite: Save plan + tasks
    ↓
Frontend displays plan

[3] User gives feedback
    ↓ POST /feedback
LLM replans (reduce/shift tasks)
    ↓
Delete old calendar events
    ↓
Create new events
    ↓
Update SQLite
```

---

## 💾 Database Schema

### StudyPlan Table
```
id (PK)
user_id (default: "default")
plan_json (full plan as JSON)
score (integer)
created_at (datetime)
```

### Task Table
```
id (PK)
plan_id (FK → StudyPlan)
day (e.g., "Monday")
topic (study topic)
duration_minutes (int)
calendar_event_id (from Google Calendar)
status (pending, completed, skipped)
```

---

## 🚀 Current Implementation Status

### ✅ FULLY IMPLEMENTED
- [x] FastAPI backend with 2 public endpoints
- [x] PDF ingestion + text chunking
- [x] FAISS vector store for RAG
- [x] LLM-based multi-plan generation
- [x] Plan scoring system
- [x] Google Calendar event creation
- [x] Plan storage in SQLite
- [x] Feedback-based replanning
- [x] Streamlit frontend UI

### ⚠️ PARTIALLY IMPLEMENTED
- [ ] `/feedback` endpoint defined in frontend but missing in api.py
- [ ] Task status tracking in DB (schema exists but not used)
- [ ] User authentication (hardcoded "default" user)

### ❌ NOT YET IMPLEMENTED
- [ ] Multi-user support
- [ ] Email reminders
- [ ] Google Classroom API integration
- [ ] Plan persistence across sessions
- [ ] Error handling & validation
- [ ] Rate limiting for OpenAI API
- [ ] Test suite
- [ ] Docker containerization
- [ ] Production deployment config

---

## 🔐 Environment Variables Required

Create `.env` file in project root:

```env
# OpenAI
OPENAI_API_KEY=sk-xxxxxxxxxxxxx

# Google Calendar (OAuth handled via credentials.json)
GOOGLE_CALENDAR_CREDENTIALS=credentials.json

# Database
DB_URL=sqlite:///./db/assistant.db

# Frontend
API_URL=http://localhost:8000
```

---

## ⚙️ Setup Instructions

### 1. Environment Setup
```bash
cd /Users/satwik/Documents/New\ GenAI/academic-assistant

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Create credentials.json
```bash
# Download from Google Cloud Console
# Save to project root as: credentials.json
```

### 3. Create .env file
```bash
cat > .env << EOF
OPENAI_API_KEY=your-api-key-here
GOOGLE_CALENDAR_CREDENTIALS=credentials.json
DB_URL=sqlite:///./db/assistant.db
EOF
```

### 4. Run Backend
```bash
python -m uvicorn backend.api:app --reload --port 8000
```

### 5. Run Frontend (in new terminal)
```bash
streamlit run frontend/app.py
```

---

## 🐛 Current Issues & Fixes

### Issue 1: Missing `/feedback` Endpoint
**File:** `api.py`  
**Problem:** Frontend calls `POST /feedback` but endpoint doesn't exist  
**Solution:** Add endpoint to api.py:
```python
@app.post("/feedback")
def provide_feedback(plan_id: int, feedback: str, start_date: str, start_time: str = "09:00"):
    result = replan(plan_id, feedback, start_date, start_time)
    return result
```

### Issue 2: No Error Handling
**Problem:** Missing validation, no exception handling  
**Solution:** Add try-catch blocks, input validation

### Issue 3: Task Status Not Used
**Problem:** DB schema has `status` field but never updated  
**Solution:** Add endpoints to mark tasks as `completed`/`skipped`

### Issue 4: No User Authentication
**Problem:** All plans saved to hardcoded "default" user  
**Solution:** Implement user login / API key authentication

---

## 📊 API Endpoints Comparison

### Currently Implemented:
```
POST /upload              ← Upload and ingest documents
POST /plan                ← Generate and schedule study plan
```

### Missing (in frontend but not backend):
```
POST /feedback            ← Replan based on user feedback
```

### Should Add:
```
GET /plans                ← List user's plans
GET /plans/{id}           ← Get specific plan details
GET /tasks/{plan_id}      ← List tasks for a plan
PUT /tasks/{task_id}      ← Mark task as completed/skipped
DELETE /plans/{id}        ← Delete a plan & remove calendar events
GET /health               ← Basic health check
```

---

## 🔗 Integration Checklist

- [ ] **OpenAI API Key obtained & added to .env**
- [ ] **Google Cloud project created**
- [ ] **Google Calendar API enabled**
- [ ] **credentials.json downloaded & placed in repo**
- [ ] **Database initialized** (run models.py)
- [ ] **Backend running** (uvicorn)
- [ ] **Frontend running** (streamlit)
- [ ] **First OAuth flow completed** (browser popup)
- [ ] **Test with sample syllabus PDF**
- [ ] **Fix missing /feedback endpoint**
- [ ] **Add user authentication**
- [ ] **Deploy to production**

---

## 📈 Next Immediate Steps

### Phase 1: Get It Running (This Week)
1. Get OpenAI API key
2. Set up Google Cloud project & OAuth
3. Create .env file
4. Run backend & frontend
5. Test with sample document

### Phase 2: Fix Issues (Week 2)
1. Add missing `/feedback` endpoint
2. Add proper error handling
3. Add input validation
4. Add user authentication

### Phase 3: Enhance (Week 3+)
1. Add Google Classroom integration
2. Add email reminders
3. Add task tracking UI
4. Deploy to cloud (Heroku / Railway / AWS)

---

## 💡 Key Technical Decisions

### 1. Why FAISS?
- Fast vector search for document retrieval
- Works locally (no API calls)
- Good for small-medium document sets
- Can scale to Pinecone later if needed

### 2. Why GPT-4o-mini?
- Perfect balance of cost vs quality
- Fast response times
- Good at structured JSON generation
- Better than GPT-3.5 for complex planning

### 3. Why FastAPI?
- Modern Python async framework
- Auto-generated API docs (Swagger)
- Good for rapid development
- Production-ready

### 4. Why Streamlit?
- Zero frontend boilerplate
- Great for data apps
- Interactive widgets out of box
- Can deploy to Streamlit Cloud free

### 5. Why SQLite?
- No separate server needed
- Great for single-user/small team
- Can migrate to PostgreSQL later
- Perfect for prototyping

---

## 🎓 How to Explain This Project

### 30-Second Pitch:
> "An AI-powered study planner that reads your syllabus and notes using RAG, generates personalized study schedules using LLM planning, and automatically blocks time in your Google Calendar."

### 2-Minute Pitch:
> "The system takes your academic documents (syllabus, notes, assignments), extracts key information using embeddings and vector search, then uses an LLM to generate 3 different study plans. It evaluates each plan against your constraints (daily hours, weak subjects) and picks the best one. Finally, it automatically creates calendar events so your study sessions are scheduled alongside your other commitments. If your workload gets too heavy, you can tell the system and it reschedules everything intelligently."

### For Report/Portfolio:
> **Technical Architecture:** The system uses a modern RAG+LLM+Tools stack. The backend (FastAPI) ingests PDFs, chunks them, generates embeddings, and stores them in FAISS for semantic search. When a user requests a plan, the system retrieves relevant context, passes it to GPT-4o-mini which generates 3 alternative plans as JSON. A scoring algorithm evaluates plans against constraints (availability, weak subjects, daily workload). The selected plan is stored in SQLite and tasks are immediately scheduled in Google Calendar via OAuth. A feedback loop allows users to say "this is too much" and the system reparameters using the LLM."

