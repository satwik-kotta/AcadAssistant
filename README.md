# 🎓 AI Academic Assistant - Complete Project Guide

**Status:** ✅ Production-ready (needs API keys)  
**Last Updated:** April 2026  
**Built by:** Using RAG + LLM + Tool-Calling

---

## 🚀 Quick Start (5 minutes)

```bash
# 1. Get to project directory
cd /Users/satwik/Documents/New\ GenAI/academic-assistant

# 2. Activate environment
source .venv/bin/activate

# 3. Set up .env (see Configuration section below)
cat > .env << 'EOF'
OPENAI_API_KEY=sk-your-key
GOOGLE_CALENDAR_CREDENTIALS=credentials.json
DB_URL=sqlite:///./db/assistant.db
EOF

# 4. Run backend (Terminal 1)
python -m uvicorn backend.api:app --reload --port 8000

# 5. Run frontend (Terminal 2)
streamlit run frontend/app.py

# 6. Open browser
# Frontend: http://localhost:8501
# API Docs: http://localhost:8000/docs
```

---

## 📖 What Does This Do?

This is an **AI-powered academic planning system** that:

### 1️⃣ **Reads** (RAG - Retrieval Augmented Generation)
- You upload syllabus, notes, assignments (PDF)
- System extracts key topics, deadlines, concepts
- Stores everything in a searchable vector database

### 2️⃣ **Thinks** (LLM - Language Model)
- You describe what you need (e.g., "Plan my study week")
- System generates 3 different study schedules
- Each plan respects your constraints:
  - Available study hours per day
  - Weak subjects to focus on
  - Due dates and deadlines

### 3️⃣ **Acts** (Tool Calling)
- System automatically schedules tasks in your Google Calendar
- You get reminders 15 minutes before each study session
- Tasks appear alongside your other commitments

### 4️⃣ **Adapts** (Feedback Loop)
- Your feedback updates everything
- Tell the system "too much workload" → it reschedules
- Tell it "I missed yesterday" → it shifts tasks forward
- All changes sync to your calendar instantly

---

## 🎯 Real Example

### You Say:
> "Plan my Data Structures course. I have 2 hours daily. I'm weak at Dynamic Programming."

### System Does:
1. **Reads** your DSA syllabus (from PDF)
2. **Generates 3 plans:**
   - ✅ Plan A: Intensive (40 hours total, 10 hours DP)
   - ✅ Plan B: Balanced (60 hours total, 20 hours DP)
   - ✅ Plan C: Relaxed (80 hours total, 30 hours DP)
3. **Scores them:** Picks Plan B (best balance)
4. **Schedules:**
   - Monday 9:00-11:00 → "Study: DP Basics"
   - Tuesday 9:00-11:00 → "Study: DP Examples"
   - ... (across 1 month)
5. **You see:** All tasks in Google Calendar ✨

### Your Feedback:
> "Too much, I can only do 1.5 hours"

### System Response:
- Removes 30% of tasks
- Extends timeline to 1.5 months
- Deletes old calendar events
- Creates new ones with reduced workload
- Done! ⚡

---

## 📊 Architecture

```
┌────────────────────┐
│  Streamlit UI      │  ← User Interface
│ (Web Browser)      │     • Upload PDFs
│ :8501              │     • Set constraints
└──────────┬─────────┘     • View plans
           │                • Give feedback
           │ HTTP (requests)
           ▼
┌──────────────────────────┐
│  FastAPI Backend         │  ← Brain
│ (Business Logic)         │    3 endpoints:
│ :8000                    │    • /upload
├──────────────────────────┤    • /plan
│ 6 Core Services:         │    • /feedback
│ ├─ ingest.py          │
│ ├─ retriever.py        │
│ ├─ planner.py          │
│ ├─ scorer.py           │
│ ├─ calendar_tool.py    │
│ └─ feedback.py         │
└──────────┬──────────────┘
           │
     ┌─────┼─────┐
     ▼     ▼     ▼
   ┌──────────────────┐
   │ External APIs    │
   ├──────────────────┤
   │ • OpenAI (LLM)   │
   │ • Google Calen   │
   └──────────────────┘
     ▼     ▼     ▼
   ┌──────────────────┐
   │ Local Storage    │
   ├──────────────────┤
   │ • FAISS Index    │ (Embeddings search)
   │ • SQLite DB      │ (Plans, tasks)
   │ • /uploads       │ (PDFs)
   └──────────────────┘
```

---

## 📁 Project Structure

```
academic-assistant/
├── README.md                     ← You are here
├── QUICK_START.md                ← Setup instructions
├── PROJECT_ANALYSIS.md           ← Technical deep-dive
├── API_REFERENCE.md              ← Endpoint documentation
├── BUG_FIXES.md                  ← Known issues & solutions
├── IMPLEMENTATION_STATUS.md      ← What's done/TODO
│
├── requirements.txt              ← Python packages
├── .env                          ← API keys (git ignored)
├── credentials.json              ← Google OAuth (git ignored)
├── token.json                    ← Auto-generated token
│
├── backend/
│   ├── api.py                    ← FastAPI app (3 endpoints)
│   ├── models.py                 ← Database & ORM
│   ├── ingest.py                 ← PDF → chunks → embeddings
│   ├── retriever.py              ← Semantic search
│   ├── planner.py                ← LLM plan generation
│   ├── scorer.py                 ← Plan evaluation
│   ├── calendar_tool.py          ← Google Calendar sync
│   └── feedback.py               ← Replanning logic
│
├── frontend/
│   └── app.py                    ← Streamlit UI
│
├── db/
│   └── assistant.db              ← SQLite database (auto-created)
│
├── uploads/                      ← PDFs go here (auto-created)
│   └── *.pdf
│
└── vectorstore/                  ← FAISS index (auto-created)
    └── index/
```

---

## 🔧 Configuration

### 1. Get OpenAI API Key

```bash
# Visit: https://platform.openai.com/account/api-keys
# Generate new secret key
# Copy it (shows only once!)

# Add to .env
echo "OPENAI_API_KEY=sk-xxxxxxxxxxxxx" >> .env
```

### 2. Set Up Google Calendar OAuth

```bash
# Go to: https://console.cloud.google.com
# 1. Create new project → "Academic Assistant"
# 2. Enable Google Calendar API
# 3. Create OAuth 2.0 credentials (Desktop app)
# 4. Download JSON file
# 5. Save as: credentials.json (in project root)
```

### 3. Create Environment File

```bash
cat > .env << 'EOF'
OPENAI_API_KEY=sk-xxxxxxxxxxxxx
GOOGLE_CALENDAR_CREDENTIALS=credentials.json
DB_URL=sqlite:///./db/assistant.db
EOF
```

---

## ▶️ Running the System

### Terminal 1: Backend API

```bash
source .venv/bin/activate
python -m uvicorn backend.api:app --reload --port 8000
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

**Test it:** http://localhost:8000/docs (Swagger UI)

### Terminal 2: Frontend UI

```bash
source .venv/bin/activate
streamlit run frontend/app.py
```

**Expected output:**
```
You can now view your Streamlit app in your browser.
Local URL: http://localhost:8501
```

### First Run: OAuth Login

When you first create a plan, you'll see:
```
Please visit this URL to authorize this application:
https://accounts.google.com/o/oauth2/auth?...
```

Click the link → Authorize → Done! (auto saves token.json)

---

## 🧪 Test the System

### Step 1: Upload a Document

```bash
# Create test syllabus
python << 'PYTHON'
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("test_syllabus.pdf", pagesize=letter)
c.setFont("Helvetica", 12)
y = 750

content = """COURSE: Data Structures & Algorithms

Topics:
1. Arrays & Linked Lists (Week 1-2)
2. Stacks & Queues (Week 3)
3. Trees & Graphs (Week 4-5)
4. Dynamic Programming (Week 6-8)

Assignments Due:
- Array manipulation (Week 2)
- Tree traversal (Week 5)
- DP optimization (Week 8)

Weak Topics: DP, Graph theory"""

for line in content.split('\n'):
    if y < 50:
        c.showPage()
        y = 750
    c.drawString(50, y, line)
    y -= 15

c.save()
print("✅ test_syllabus.pdf created")
PYTHON
```

### Step 2: Go to Frontend

Open: http://localhost:8501

### Step 3: Upload & Generate

1. Upload `test_syllabus.pdf`
2. Click "Ingest documents" → Wait for "chunks ingested"
3. Enter request: "Create a 2-week study plan for DSA"
4. Set daily hours: 2.5
5. Add weak subject: "Dynamic Programming"
6. Click "Generate plan" → Wait 30-60 seconds
7. View generated plan with all days and tasks

### Step 4: Check Calendar

Open: https://calendar.google.com
- Should see study tasks scheduled!

### Step 5: Test Feedback

1. Type: "Too much workload, reduce by half"
2. Click "Update plan"
3. Calendar should update automatically!

---

## 📚 API Endpoints

### POST /upload
Upload and ingest PDF documents
```json
POST /upload
Content-Type: multipart/form-data
file: <PDF file>

Response:
{
  "message": "Uploaded and ingested",
  "filename": "syllabus.pdf",
  "chunks": 42
}
```

### POST /plan
Generate personalized study plans
```json
POST /plan
{
  "request": "Plan my study week",
  "daily_hours": 2.0,
  "weak_subjects": ["mathematics"],
  "start_date": "2025-04-14",
  "start_time": "09:00"
}

Response:
{
  "plan": { ... },
  "calendar_events": 7,
  "plan_id": 42
}
```

### POST /feedback
Update plan based on feedback
```json
POST /feedback
{
  "plan_id": 42,
  "feedback": "Too much workload",
  "start_date": "2025-04-21"
}

Response:
{
  "updated_plan": { ... },
  "calendar_events": 10
}
```

**Full API docs:** See [API_REFERENCE.md](API_REFERENCE.md)

---

## 🐛 Common Issues

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | `pip install -r requirements.txt -U` |
| `OPENAI_API_KEY not found` | Create `.env` with your actual key |
| `credentials.json not found` | Download from Google Cloud Console, save to project root |
| `Port 8000 in use` | `pkill -f "uvicorn"` then restart |
| `SQLite locked` | `pkill -f "uvicorn"` and `pkill -f "streamlit"` |
| `No chunks ingested` | Make sure PDF is valid, not corrupted |
| `Vectorstore not found` | Upload a document first before asking for plan |

**More help:** See [BUG_FIXES.md](BUG_FIXES.md)

---

## 📊 How Plans are Generated

```
User Request
    ↓
Retrieve 5 most relevant document chunks (semantic search)
    ↓
Pass to GPT-4o-mini with:
  • Document context
  • User constraints (hours/day, weak subjects)
  • Specific JSON format request
    ↓
LLM generates 3 alternative plans in JSON:
  • Plan A: High intensity
  • Plan B: Medium balance
  • Plan C: Low intensity / Extended
    ↓
Scorer evaluates each plan:
  • Does daily load match available hours?
  • Do weak subjects get prioritized?
  • Is total workload reasonable?
    ↓
Best score wins → Plan selected
    ↓
Each task → Google Calendar event
    ↓
Displayed to user in Streamlit
```

---

## 🎓 How to Explain This

### To Your Professor:
> "An AI system that reads academic documents using retrieval-augmented generation, generates personalized study schedules using large language models, and automatically executes them by syncing to Google Calendar."

### Technical Details:
- **RAG:** PDF → 500-char chunks → OpenAI embeddings → FAISS vector store
- **Planning:** Context retrieved → GPT-4o-mini generates 3 JSON plans → Scorer evaluates → Best selected
- **Execution:** Tasks scheduled in Google Calendar via OAuth 2.0
- **Adaptation:** Feedback → LLM recalculates → Calendar events updated
- **Storage:** SQLite database tracks plans, tasks, event IDs

### Demo Script:
1. Upload syllabus
2. Request plan for 2 hours/day
3. System generates plan
4. Tasks appear in calendar
5. "Too much" feedback
6. Plan recalculates
7. Calendar auto-updates

---

## 🚀 Next Steps

### To Get Running:
1. [ ] Get OpenAI API key
2. [ ] Set up Google OAuth
3. [ ] Create `.env` file
4. [ ] Run backend & frontend
5. [ ] Test with sample PDF

### To Enhance:
1. [ ] Add user authentication (multi-user)
2. [ ] Deploy to cloud (Heroku/Railway)
3. [ ] Add email reminders
4. [ ] Integrate Google Classroom API
5. [ ] Add task completion tracking

---

## 📖 Documentation

- **[QUICK_START.md](QUICK_START.md)** - Step-by-step setup (30 min)
- **[PROJECT_ANALYSIS.md](PROJECT_ANALYSIS.md)** - Full technical architecture
- **[API_REFERENCE.md](API_REFERENCE.md)** - All endpoints & examples
- **[BUG_FIXES.md](BUG_FIXES.md)** - Known issues & solutions
- **[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)** - What's done/TODO

---

## 🔗 External Resources

| Resource | Link |
|----------|------|
| OpenAI API Docs | https://platform.openai.com/docs |
| Google Calendar API | https://developers.google.com/calendar |
| FastAPI Framework | https://fastapi.tiangolo.com/ |
| Streamlit Framework | https://docs.streamlit.io/ |
| LangChain Docs | https://python.langchain.com/ |

---

## 📞 Quick Commands

```bash
# Check backend API
curl http://localhost:8000/docs

# View database
sqlite3 db/assistant.db "SELECT * FROM study_plans;"

# Clear vectorstore
rm -rf vectorstore/index/

# Restart everything
pkill -f "uvicorn"
pkill -f "streamlit"
sleep 2
python -m uvicorn backend.api:app --reload &
streamlit run frontend/app.py &

# View logs
tail -f backend.log
```

---

## 🎉 You're Ready!

Your **AI Academic Assistant** is complete and production-ready.

**Next action:** Get API keys → Configure `.env` → Run → Test

**Time to working system:** ~1-2 hours

Good luck! 🚀

---

**Questions?** Check the documentation files in the project root, or review the code comments in `backend/` folder.

