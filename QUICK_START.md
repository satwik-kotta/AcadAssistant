# 🚀 Quick Start Implementation Guide

## Phase 0: Pre-flight Checks

```bash
cd /Users/satwik/Documents/New\ GenAI/academic-assistant

# Check Python version (need 3.8+)
python --version

# Check if venv exists
ls -la .venv/
```

---

## Phase 1: API Setup (20 minutes)

### Step 1.1: Get OpenAI API Key

1. Go to https://platform.openai.com/account/api-keys
2. Login or create free account
3. Generate new API key
4. Copy the key (starts with `sk-`)
5. **Keep it safe** (only shown once!)

**Cost Consideration:**
- Free trial: $5 credit (expires 3 months)
- After: ~$0.01-0.05 per study plan generation
- Embeddings: pennies per document

---

### Step 1.2: Set Up Google Calendar API

#### Option A: Quick Setup (5 min) - USE THIS

1. **Go to:** https://console.cloud.google.com/
2. **Create new project:**
   - Click "Select a Project" → "NEW PROJECT"
   - Name: "Academic Assistant"
   - Click "CREATE"
   - Wait 30 seconds...

3. **Enable Calendar API:**
   - Search bar: type "Google Calendar API"
   - Click "Enable"

4. **Create OAuth Credentials:**
   - Click "Create Credentials" (blue button, top-right)
   - Application type: "Desktop application"
   - Click "Create"
   - Click "Download" (JSON file)

5. **Save credentials:**
   ```bash
   # In your project root folder:
   /Users/satwik/Documents/New\ GenAI/academic-assistant/credentials.json
   ```

#### Option B: Full Documentation
https://developers.google.com/calendar/api/quickstart/python

---

### Step 1.3: Create .env File

```bash
cd /Users/satwik/Documents/New\ GenAI/academic-assistant

cat > .env << 'EOF'
OPENAI_API_KEY=sk-your-actual-key-here
GOOGLE_CALENDAR_CREDENTIALS=credentials.json
DB_URL=sqlite:///./db/assistant.db
EOF
```

**Verify:**
```bash
cat .env  # Should show your keys (never commit this!)
```

---

## Phase 2: Install Dependencies

```bash
# Activate virtual environment
source .venv/bin/activate

# Verify it worked (should show (.venv) prefix)
echo $VIRTUAL_ENV

# Install all packages
pip install -r requirements.txt

# Verify installations
pip list | grep -E "openai|langchain|fastapi|streamlit|google"
```

---

## Phase 3: Database Setup

```bash
# Python will auto-create SQLite on first run
# But let's verify the DB directory exists:

mkdir -p db/
ls -la db/

# When you run the backend for the first time,
# db/assistant.db will be created automatically
```

---

## Phase 4: Run the System

### Terminal 1: Backend (API Server)

```bash
cd /Users/satwik/Documents/New\ GenAI/academic-assistant

# Activate venv
source .venv/bin/activate

# Start FastAPI server
python -m uvicorn backend.api:app --reload --port 8000
```

**Expected Output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

**Test it:**
```bash
# In a new terminal (keep backend running):
curl http://localhost:8000/docs
# Should open Swagger UI in browser
```

---

### Terminal 2: Frontend (Web UI)

```bash
cd /Users/satwik/Documents/New\ GenAI/academic-assistant

# Activate venv
source .venv/bin/activate

# Start Streamlit app
streamlit run frontend/app.py
```

**Expected Output:**
```
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
```

---

## Phase 5: First-Time Auth (5 min)

**On first run, you'll see:**
```
Please visit this URL to authorize this application:
https://accounts.google.com/o/oauth2/auth?...
```

1. Click the link (or copy-paste into browser)
2. Login with Google account
3. Click "Allow" for Calendar access
4. Close the browser tab
5. Backend will automatically create `token.json`

✅ **From now on, authentication is automatic!**

---

## Phase 6: Test the System

### Step 1: Create Sample Documents

```bash
# Create a minimal syllabus for testing
cd /Users/satwik/Documents/New\ GenAI/academic-assistant

cat > test_syllabus.txt << 'EOF'
SYLLABUS: Introduction to Data Science

Topics to cover:
1. Python Basics (Week 1-2)
2. NumPy and Pandas (Week 3-4)
3. Matplotlib Visualization (Week 5)
4. Machine Learning Basics (Week 6-7)
5. Neural Networks (Week 8-9)

Assignments:
- Assignment 1: Python exercises (Due: Week 2)
- Assignment 2: Data cleaning project (Due: Week 4)
- Assignment 3: Visualization dashboard (Due: Week 5)
- Final Project: ML model (Due: Week 9)

Weak areas to focus:
- Mathematics foundations
- Advanced statistics
EOF

# Convert to PDF (requires tool, or just use the text version)
# For now, let's create a simple PDF
python << 'PYTHON'
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("test_syllabus.pdf", pagesize=letter)
c.setFont("Helvetica", 12)
y = 750

content = """SYLLABUS: Introduction to Data Science

Topics to cover:
1. Python Basics (Week 1-2)
2. NumPy and Pandas (Week 3-4)
3. Matplotlib Visualization (Week 5)
4. Machine Learning Basics (Week 6-7)
5. Neural Networks (Week 8-9)

Assignments:
- Assignment 1: Python exercises (Due: Week 2)
- Assignment 2: Data cleaning project (Due: Week 4)
- Assignment 3: Visualization dashboard (Due: Week 5)
- Final Project: ML model (Due: Week 9)

Weak areas to focus on:
- Mathematics foundations
- Advanced statistics"""

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

### Step 2: Access Frontend

1. Open: http://localhost:8501
2. Upload `test_syllabus.pdf`
3. Click "Ingest documents"
4. Wait for "✅ Chunks ingested"

### Step 3: Generate Plan

1. Enter: "Create a study plan for this course. I have 2 hours daily and weak at mathematics."
2. Keep defaults (2 hours, today's date)
3. Add weak subject: "mathematics"
4. Click "Generate plan"
5. Wait 30-60 seconds...

**Expected Result:**
- ✅ Plan created with multiple days
- ✅ Tasks scheduled in Google Calendar
- ✅ You should see tasks in your actual Google Calendar!

### Step 4: Check Calendar

1. Open Google Calendar: https://calendar.google.com
2. Look for events starting tomorrow like:
   - "Study: Python Basics"
   - "Study: Data Analysis"
   - etc.

### Step 5: Test Feedback

1. Type: "Too much workload, reduce by half"
2. Click "Update plan"
3. Calendar events should update!

---

## Phase 7: Troubleshooting

### Problem: "ModuleNotFoundError: No module named..."

```bash
# Reactivate venv
source .venv/bin/activate

# Reinstall
pip install -r requirements.txt -U

# Run again
python -m uvicorn backend.api:app --reload
```

---

### Problem: "OPENAI_API_KEY not found"

```bash
# Check .env exists and has key
cat .env

# If not, verify it's in project root:
ls -la .env

# If not, create it:
cat > .env << 'EOF'
OPENAI_API_KEY=sk-xxxxx  (your actual key)
GOOGLE_CALENDAR_CREDENTIALS=credentials.json
EOF
```

---

### Problem: "credentials.json not found"

```bash
# Should be in project root
ls -la credentials.json

# If missing, download from Google Cloud Console again
# and save to: /Users/satwik/Documents/New\ GenAI/academic-assistant/credentials.json
```

---

### Problem: "FAISS index not found"

**Error:** When uploading first document
```
FileNotFoundError: vectorstore/index
```

**Fix:**
```bash
mkdir -p vectorstore/
# The first upload will create the index
```

---

### Problem: "SQLite database locked"

**Error:** `database is locked` error

```bash
# Kill any existing backend processes
pkill -f "uvicorn"

# Restart
python -m uvicorn backend.api:app --reload
```

---

### Problem: Port Already in Use

**Error:** `Address already in use 127.0.0.1:8000`

```bash
# Find and kill process on port 8000
lsof -i :8000
kill -9 <PID>

# Or use different port
python -m uvicorn backend.api:app --reload --port 8001
```

---

## 🎯 Verification Checklist

- [ ] `pip list` shows: openai, langchain, fastapi, streamlit, google-api-python-client
- [ ] `.env` file exists with API keys
- [ ] `credentials.json` exists in project root
- [ ] Backend runs without errors on http://localhost:8000
- [ ] Frontend loads on http://localhost:8501
- [ ] Can upload PDF document
- [ ] Can generate study plan
- [ ] Tasks appear in Google Calendar
- [ ] Can give feedback and replan

---

## ✅ Success Criteria

Your system is working when:

1. **Backend starts:** No errors, shows "Application startup complete"
2. **Frontend loads:** Streamlit UI shows all sections
3. **Upload works:** PDF uploads and shows "chunks ingested"
4. **Plan generates:** Takes 30-60 seconds, shows structured plan
5. **Calendar syncs:** Tasks appear in your Google Calendar immediately
6. **Feedback works:** Changing constraints reschedules tasks

---

## 🔄 Daily Development Workflow

```bash
# Terminal 1: Backend (keep running)
cd /Users/satwik/Documents/New\ GenAI/academic-assistant
source .venv/bin/activate
python -m uvicorn backend.api:app --reload

# Terminal 2: Frontend  
cd /Users/satwik/Documents/New\ GenAI/academic-assistant
source .venv/bin/activate
streamlit run frontend/app.py

# Terminal 3: Testing/Debugging
cd /Users/satwik/Documents/New\ GenAI/academic-assistant
source .venv/bin/activate
python backend/ingest.py  # Test ingestion
python backend/planner.py  # Test plan generation
```

---

## 📚 Next Steps After Getting It Running

1. **Fix missing `/feedback` endpoint** in `api.py`
2. **Add error handling** and input validation
3. **Add user authentication** (api_key or login)
4. **Add more endpoints** (GET plans, GET tasks, etc.)
5. **Build dashboard** showing all plans
6. **Add email notifications**
7. **Deploy to cloud** (Heroku, Railway, AWS)

