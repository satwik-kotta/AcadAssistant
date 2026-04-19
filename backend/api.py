import shutil, os, json, uuid, threading, secrets, time, contextlib
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from pathlib import Path
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import httpx
from backend.enhanced_ingest import ingest_enhanced, list_documents, delete_document
from backend.planner import generate_plans
from backend.scorer import select_best_plan
from backend.calendar_tool import schedule_plan
from backend.feedback import replan
from backend.agent import chat as agent_chat
from backend.models import Session, StudyPlan, Task, Document as DocModel
from backend.timetable import add_timeframes_to_plan

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT_DIR / ".env", override=True)

app = FastAPI()
GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
GOOGLE_CREDENTIALS_FILE = ROOT_DIR / "credentials.json"
GOOGLE_OAUTH_CALLBACK_URI = (
    os.getenv("GOOGLE_OAUTH_CALLBACK_URI") or "http://127.0.0.1:8013/auth/google/callback"
).strip()
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
AUTH_SESSIONS: dict[str, dict] = {}
AUTH_TOKENS: dict[str, dict] = {}
AUTH_FLOWS: dict[str, Flow] = {}
AUTH_STATE_TO_SESSION: dict[str, str] = {}
AUTH_LOCK = threading.Lock()


@contextlib.contextmanager
def _relax_oauth_scope_check():
    """Allow token responses that include additional previously-granted scopes."""
    previous = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)
        else:
            os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = previous

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8506",
        "http://127.0.0.1:8506",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PlanRequest(BaseModel):
    request: str
    daily_hours: float = 2.0
    weak_subjects: list[str] = []
    start_date: str = "2025-07-14"
    start_time: str = "09:00"


class FeedbackRequest(BaseModel):
    plan_id: int
    feedback: str
    start_date: str
    start_time: str = "09:00"


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    session_state: dict = {}
    plan_id: int | None = None
    current_plan: dict | None = None
    start_date: str | None = None
    start_time: str = "09:00"


class ChatResponse(BaseModel):
    reply: str
    history: list
    session_state: dict
    updated_plan: dict | None = None


class GoogleAuthRequest(BaseModel):
    credential: str


class AuthStartResponse(BaseModel):
    session_id: str
    status: str
    auth_url: str | None = None


class AuthStatusResponse(BaseModel):
    status: str
    user: dict | None = None
    session_token: str | None = None
    error: str | None = None


def _verify_google_credential(credential: str) -> dict:
    try:
        token_info = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID if GOOGLE_CLIENT_ID else None,
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {e}")

    if token_info.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise HTTPException(status_code=401, detail="Invalid token issuer")

    user_id = token_info.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Google token missing subject")

    return {
        "id": user_id,
        "email": token_info.get("email", ""),
        "name": token_info.get("name", ""),
        "picture": token_info.get("picture", ""),
    }


def _user_from_credentials(creds) -> dict:
    token = getattr(creds, "id_token", None)
    if token:
        return _verify_google_credential(token)

    access_token = getattr(creds, "token", None)
    if not access_token:
        raise HTTPException(status_code=401, detail="Google sign-in did not return usable tokens")

    try:
        resp = httpx.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Could not fetch Google profile: {e}")

    user_id = data.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Google profile missing subject")

    return {
        "id": user_id,
        "email": data.get("email", ""),
        "name": data.get("name", ""),
        "picture": data.get("picture", ""),
    }


def _issue_session_token(user: dict) -> str:
    token = secrets.token_urlsafe(32)
    with AUTH_LOCK:
        AUTH_TOKENS[token] = user
    return token


def _resolve_session_token(token: str) -> dict | None:
    with AUTH_LOCK:
        return AUTH_TOKENS.get(token)


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    credential = authorization.split(" ", 1)[1].strip()
    if not credential:
        raise HTTPException(status_code=401, detail="Empty Bearer token")

    session_user = _resolve_session_token(credential)
    if session_user:
        return session_user

    return _verify_google_credential(credential)


@app.get("/auth/config")
def auth_config():
    return {
        "mode": "backend-oauth",
        "google_client_id": GOOGLE_CLIENT_ID,
        "oauth_callback_uri": GOOGLE_OAUTH_CALLBACK_URI,
    }


@app.post("/auth/google/start", response_model=AuthStartResponse)
def auth_google_start():
    if not GOOGLE_CREDENTIALS_FILE.exists():
        raise HTTPException(status_code=500, detail="credentials.json is missing")

    now = time.time()
    with AUTH_LOCK:
        for sid, state in AUTH_SESSIONS.items():
            if state.get("status") == "pending":
                age = now - float(state.get("created_at", now))
                if age < 180:
                    return AuthStartResponse(
                        session_id=sid,
                        status="pending",
                        auth_url=state.get("auth_url"),
                    )
                state["status"] = "error"
                state["error"] = "Previous sign-in session timed out. Please try again."

    session_id = uuid.uuid4().hex
    flow = Flow.from_client_secrets_file(
        str(GOOGLE_CREDENTIALS_FILE),
        scopes=GOOGLE_SCOPES,
        redirect_uri=GOOGLE_OAUTH_CALLBACK_URI,
    )
    auth_url, oauth_state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )

    with AUTH_LOCK:
        AUTH_SESSIONS[session_id] = {
            "status": "pending",
            "created_at": now,
            "auth_url": auth_url,
            "oauth_state": oauth_state,
        }
        AUTH_FLOWS[session_id] = flow
        AUTH_STATE_TO_SESSION[oauth_state] = session_id

    return AuthStartResponse(session_id=session_id, status="pending", auth_url=auth_url)


@app.get("/auth/google/callback")
def auth_google_callback(state: str | None = None, code: str | None = None, error: str | None = None):
    if not state:
        return HTMLResponse("<h3>Missing OAuth state.</h3>", status_code=400)

    with AUTH_LOCK:
        session_id = AUTH_STATE_TO_SESSION.get(state)

    if not session_id:
        return HTMLResponse("<h3>Unknown or expired sign-in session.</h3>", status_code=400)

    if error:
        with AUTH_LOCK:
            AUTH_SESSIONS[session_id] = {"status": "error", "error": error}
            AUTH_FLOWS.pop(session_id, None)
        return HTMLResponse("<h3>Google sign-in was cancelled or failed.</h3><p>You can close this tab.</p>")

    if not code:
        with AUTH_LOCK:
            AUTH_SESSIONS[session_id] = {"status": "error", "error": "Missing authorization code"}
            AUTH_FLOWS.pop(session_id, None)
        return HTMLResponse("<h3>Missing authorization code.</h3>", status_code=400)

    with AUTH_LOCK:
        flow = AUTH_FLOWS.get(session_id)

    if not flow:
        return HTMLResponse("<h3>Sign-in session expired. Please try again.</h3>", status_code=400)

    try:
        with _relax_oauth_scope_check():
            flow.fetch_token(code=code)
        user = _user_from_credentials(flow.credentials)
        session_token = secrets.token_urlsafe(32)
        with AUTH_LOCK:
            AUTH_TOKENS[session_token] = user
            AUTH_SESSIONS[session_id] = {
                "status": "complete",
                "user": user,
                "session_token": session_token,
            }
            AUTH_FLOWS.pop(session_id, None)
        return HTMLResponse(
            "<h3>Sign-in complete.</h3><p>You can close this tab and return to the app.</p>"
            "<script>setTimeout(() => window.close(), 1200);</script>"
        )
    except Exception as e:
        with AUTH_LOCK:
            AUTH_SESSIONS[session_id] = {"status": "error", "error": str(e)}
            AUTH_FLOWS.pop(session_id, None)
        return HTMLResponse(
            f"<h3>Sign-in failed.</h3><p>{str(e)}</p><p>You can close this tab.</p>",
            status_code=400,
        )


@app.get("/auth/google/status/{session_id}", response_model=AuthStatusResponse)
def auth_google_status(session_id: str):
    with AUTH_LOCK:
        state = AUTH_SESSIONS.get(session_id)

    if not state:
        raise HTTPException(status_code=404, detail="Unknown auth session")

    return AuthStatusResponse(
        status=state.get("status", "pending"),
        user=state.get("user"),
        session_token=state.get("session_token"),
        error=state.get("error"),
    )


@app.post("/auth/google")
def auth_google(req: GoogleAuthRequest):
    user = _verify_google_credential(req.credential)
    session_token = _issue_session_token(user)
    return {"user": user, "session_token": session_token}


@app.get("/auth/me")
def auth_me(current_user: dict = Depends(get_current_user)):
    return {"user": current_user}


@app.post("/upload")
async def upload_document(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Upload and parse a PDF document with enhanced parsing."""
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        os.makedirs("uploads", exist_ok=True)
        user_upload_dir = os.path.join("uploads", current_user["id"])
        os.makedirs(user_upload_dir, exist_ok=True)
        safe_name = os.path.basename(file.filename)
        dest = os.path.join(user_upload_dir, safe_name)
        
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Auto-detect document type from filename
        filename_lower = safe_name.lower()
        if "syllabus" in filename_lower:
            doc_type = "syllabus"
        elif "assignment" in filename_lower or "rubric" in filename_lower:
            doc_type = "assignment"
        elif "notes" in filename_lower or "lecture" in filename_lower:
            doc_type = "notes"
        elif "research" in filename_lower or "paper" in filename_lower:
            doc_type = "research_paper"
        else:
            doc_type = "unknown"

        chunks, doc_id = ingest_enhanced(dest, doc_type=doc_type, user_id=current_user["id"])
        return {
            "message": "Uploaded and ingested with enhanced parsing",
            "filename": safe_name,
            "document_id": doc_id,
            "chunks": chunks,
            "doc_type": doc_type
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to upload document: {str(e)}")


@app.get("/documents")
def get_documents(current_user: dict = Depends(get_current_user)):
    """List all uploaded documents with metadata."""
    try:
        docs = list_documents(user_id=current_user["id"])
        return {
            "documents": docs,
            "total": len(docs)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing documents: {str(e)}")


@app.delete("/documents/{doc_id}")
def remove_document(doc_id: int, current_user: dict = Depends(get_current_user)):
    """Delete a document and remove it from the vectorstore."""
    try:
        success = delete_document(doc_id, user_id=current_user["id"])
        if not success:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
        return {"message": f"Document {doc_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting document: {str(e)}")



@app.post("/plan")
def create_plan(req: PlanRequest, current_user: dict = Depends(get_current_user)):
    try:
        constraints = {
            "daily_hours": req.daily_hours,
            "weak_subjects": req.weak_subjects,
            "start_date": req.start_date
        }
        plans = generate_plans(req.request, constraints)
        best = select_best_plan(plans, constraints)
        best = add_timeframes_to_plan(best, req.start_date, req.start_time)

        session = Session()
        db_plan = StudyPlan(
            user_id=current_user["id"],
            plan_json=json.dumps(best),
            score=best.get("score", 0)
        )
        session.add(db_plan)
        session.commit()

        event_ids = schedule_plan(best, req.start_date, req.start_time)

        for i, day_block in enumerate(best.get("days", [])):
            for task in day_block["tasks"]:
                t = Task(
                    plan_id=db_plan.id,
                    day=day_block["day"],
                    topic=task["topic"],
                    duration_minutes=task["duration_minutes"],
                    calendar_event_id=event_ids[i] if i < len(event_ids) else None
                )
                session.add(t)
        session.commit()
        plan_id = db_plan.id
        session.close()

        return {"plan": best, "calendar_events": len(event_ids), "plan_id": plan_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating plan: {str(e)}")


@app.post("/feedback")
def provide_feedback(req: FeedbackRequest, current_user: dict = Depends(get_current_user)):
    try:
        session = Session()
        plan = session.query(StudyPlan).filter_by(id=req.plan_id, user_id=current_user["id"]).first()
        session.close()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found for this user")

        result = replan(req.plan_id, req.feedback, req.start_date, req.start_time)
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error replanning: {str(e)}")


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    try:
        merged_state = dict(req.session_state or {})
        if req.plan_id is not None and merged_state.get("plan_id") is None:
            merged_state["plan_id"] = req.plan_id
        if req.current_plan is not None and merged_state.get("current_plan") is None:
            merged_state["current_plan"] = req.current_plan
        if req.start_date is not None and merged_state.get("start_date") is None:
            merged_state["start_date"] = req.start_date
        if req.start_time and merged_state.get("start_time") is None:
            merged_state["start_time"] = req.start_time

        reply, updated_history, updated_plan = agent_chat(
            req.message,
            req.history,
            merged_state
        )
        # Persist updated plan to DB if plan changed
        if updated_plan and merged_state.get("plan_id"):
            db_session = Session()
            db_plan = db_session.query(StudyPlan).filter_by(
                id=merged_state["plan_id"],
                user_id=current_user["id"],
            ).first()
            if db_plan:
                db_plan.plan_json = json.dumps(updated_plan)
                db_session.commit()
            db_session.close()

        return ChatResponse(
            reply=reply,
            history=updated_history,
            session_state=merged_state,
            updated_plan=updated_plan
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error in chat: {str(e)}")
    
# ── Prerequisites & Quiz endpoints ───────────────────────────────────────────

@app.get("/prerequisites/{doc_id}")
def get_prerequisites(doc_id: int, current_user: dict = Depends(get_current_user)):
    """Generate prerequisite report for a document using full text + Ollama."""
    try:
        import json

        db_session = Session()
        doc = db_session.query(DocModel).filter_by(id=doc_id, user_id=current_user["id"]).first()
        db_session.close()

        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # Use cached analysis if available
        if doc.analysis_json:
            analysis = json.loads(doc.analysis_json)
            from backend.enhanced_ingest import format_prerequisite_report
            return {
                "doc_id": doc_id,
                "filename": doc.filename,
                "analysis": analysis,
                "report": format_prerequisite_report(analysis)
            }

        # Generate fresh analysis from full text
        if not doc.full_text:
            raise HTTPException(status_code=400, detail="Document has no extracted text. Re-upload it.")

        from backend.enhanced_ingest import analyse_document, format_prerequisite_report
        analysis = analyse_document(doc.full_text, doc.filename)

        # Cache it
        db_session = Session()
        doc = db_session.query(DocModel).filter_by(id=doc_id, user_id=current_user["id"]).first()
        doc.analysis_json = json.dumps(analysis)
        db_session.commit()
        db_session.close()

        return {
            "doc_id": doc_id,
            "filename": doc.filename,
            "analysis": analysis,
            "report": format_prerequisite_report(analysis)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating prerequisites: {str(e)}")


@app.get("/quiz/{doc_id}")
def generate_quiz(doc_id: int, num_questions: int = 10, current_user: dict = Depends(get_current_user)):
    """Generate MCQ quiz from document content using Ollama."""
    try:
        from backend.llm_router import llm_json
        import json

        db_session = Session()
        doc = db_session.query(DocModel).filter_by(id=doc_id, user_id=current_user["id"]).first()
        db_session.close()

        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        if not doc.full_text:
            raise HTTPException(status_code=400, detail="Document has no extracted text. Re-upload it.")

        # Use analysis topics to guide quiz generation
        topics_context = ""
        if doc.analysis_json:
            analysis = json.loads(doc.analysis_json)
            topics = analysis.get("topics_covered", [])
            if topics:
                topic_names = [t["topic"] for t in topics]
                topics_context = f"\nFocus on these topics: {', '.join(topic_names)}"

        prompt = f"""Read the following document carefully and generate exactly {num_questions} multiple choice questions (MCQs) that test deep understanding of the content.
{topics_context}

Document content:
{doc.full_text[:40000]}

Rules for generating questions:
1. Each question must be directly based on the document content
2. Each question must have exactly 4 options labeled A, B, C, D
3. Only one option must be correct
4. Wrong options must be plausible but clearly incorrect
5. Include questions from different topics and difficulty levels
6. Questions should test understanding, not just memorization
7. The explanation must reference specific content from the document

Return ONLY a JSON array with exactly {num_questions} objects:
[
  {{
    "question_number": 1,
    "topic": "topic this question covers",
    "difficulty": "easy|medium|hard",
    "question": "the question text",
    "options": {{
      "A": "first option",
      "B": "second option", 
      "C": "third option",
      "D": "fourth option"
    }},
    "correct_answer": "A",
    "explanation": "why this answer is correct, referencing the document"
  }}
]"""

        questions = llm_json(prompt, temperature=0.4)

        if not isinstance(questions, list) or len(questions) == 0:
            raise ValueError("LLM did not return valid questions")

        # Ensure question numbers are correct
        for i, q in enumerate(questions):
            q["question_number"] = i + 1

        return {
            "doc_id": doc_id,
            "filename": doc.filename,
            "total_questions": len(questions),
            "questions": questions
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating quiz: {str(e)}")    