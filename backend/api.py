import shutil, os, json, uuid, threading, secrets, time, contextlib, logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
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
from backend.enhanced_ingest import ingest_enhanced, list_documents, delete_document, get_full_texts_for_documents
from backend.planner import generate_plans
from backend.scorer import select_best_plan
from backend.calendar_tool import schedule_plan
from backend.feedback import replan
from backend.agent import chat as agent_chat
from backend.models import Session, StudyPlan, Task, Document as DocModel, DocumentChunk
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
logger = logging.getLogger(__name__)


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
    document_ids: list[int] = []
    use_all_documents: bool = True


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


def _get_user_documents(user_id: str) -> list:
    """Fetch all documents for a user."""
    db_session = Session()
    docs = db_session.query(DocModel).filter_by(user_id=user_id).all()
    db_session.close()
    return docs


def _validate_documents_ingested(
    user_id: str,
    context: str = "quiz generation",
    require_analysis: bool = False,
):
    """
    Validate that user has uploaded and processed documents.
    Raises HTTPException with detailed message if prerequisites not met.
    """
    docs = _get_user_documents(user_id)
    
    if not docs:
        raise HTTPException(
            status_code=412,
            detail="❌ No documents uploaded. Prerequisites not met — cannot generate quiz or plan. "
                   "Please upload course materials (syllabus, notes, or textbook) first."
        )

    docs_with_text = [d for d in docs if getattr(d, "full_text", None)]
    if not docs_with_text:
        raise HTTPException(
            status_code=412,
            detail="❌ Documents uploaded but not properly parsed. "
                   "Unable to read document content — cannot proceed with " + context + ". "
                   "Please try re-uploading your documents."
        )

    if require_analysis:
        docs_with_analysis = [d for d in docs if getattr(d, "analysis_json", None)]
        if not docs_with_analysis:
            raise HTTPException(
                status_code=412,
                detail="⚠️ Documents parsed but analysis incomplete. "
                       "The model is unable to understand document structure and prerequisites. "
                       "Please wait a moment for analysis to complete, or re-upload."
            )


def _build_topic_catalog_from_docs(docs: list) -> list[dict]:
    """Extract topic metadata from cached document analyses for planning relevance."""
    stop_words = {
        "that", "with", "from", "this", "there", "their", "about", "which", "would", "could",
        "should", "while", "where", "when", "into", "between", "after", "before", "under",
        "over", "been", "being", "also", "than", "such", "have", "has", "had", "were", "was",
        "will", "shall", "might", "because", "through", "across", "these", "those", "they", "them",
        "your", "yours", "ours", "our", "its", "itself", "hers", "his", "and", "the", "for",
        "are", "you", "not", "can", "all", "any", "but", "one", "two", "three", "using", "used",
        "study", "document", "paper", "article", "report", "data", "information",
    }

    def _clean_topic_label(value: str) -> str:
        text = " ".join(str(value or "").split()).strip("-:;,. ")
        lowered = text.lower()
        if "http" in lowered or "www." in lowered:
            return ""
        if any(token in text for token in ["?", "=", "/", "\\", "&", "#"]):
            return ""
        if "," in text or ";" in text or ":" in text:
            return ""
        if "(" in text or ")" in text:
            return ""
        if any(ch.isdigit() for ch in text) and len(text.split()) > 6:
            return ""
        if len(text) > 72:
            return ""
        words = text.split()
        if len(words) < 2:
            return ""
        if len(words) > 8:
            return ""
        return text

    def _infer_topics_from_text(full_text: str) -> list[str]:
        import re

        words = re.findall(r"[A-Za-z][A-Za-z\-]{2,}", full_text or "")
        lowered = [w.lower() for w in words]

        unigrams = [w for w in lowered if w not in stop_words and len(w) >= 4]
        bigrams = []
        for i in range(len(lowered) - 1):
            a, b = lowered[i], lowered[i + 1]
            if a in stop_words or b in stop_words:
                continue
            if len(a) < 4 or len(b) < 4:
                continue
            bigrams.append(f"{a} {b}")

        counts = Counter(bigrams + unigrams)
        topics = []
        for phrase, _ in counts.most_common(18):
            label = " ".join(part.capitalize() for part in phrase.split())
            label = _clean_topic_label(label)
            if not label:
                continue
            if label.lower() in {x.lower() for x in topics}:
                continue
            topics.append(label)
            if len(topics) >= 8:
                break
        return topics

    catalog = []
    for doc in docs:
        if not getattr(doc, "analysis_json", None):
            continue
        try:
            analysis = json.loads(doc.analysis_json)
        except Exception:
            continue
        topics = analysis.get("topics_covered", []) if isinstance(analysis, dict) else []
        for topic in topics:
            if isinstance(topic, dict):
                name = _clean_topic_label(topic.get("topic") or "")
                if not name:
                    continue
                catalog.append(
                    {
                        "topic": name,
                        "difficulty": str(topic.get("difficulty") or "intermediate"),
                        "estimated_hours": int(topic.get("estimated_hours") or 2),
                        "source_document": getattr(doc, "filename", "selected documents"),
                    }
                )

    # If topic extraction is sparse/noisy, backfill using section titles from parsed chunks.
    if len(catalog) < 6 and docs:
        session = Session()
        doc_ids = [d.id for d in docs]
        rows = session.query(DocumentChunk.document_id, DocumentChunk.section_title).filter(
            DocumentChunk.document_id.in_(doc_ids)
        ).all()
        session.close()

        doc_name_by_id = {d.id: d.filename for d in docs}
        cleaned_sections = []
        for document_id, section_title in rows:
            label = _clean_topic_label(section_title or "")
            if label:
                cleaned_sections.append((document_id, label))

        counts = Counter(cleaned_sections)
        for (document_id, label), _ in counts.most_common(12):
            catalog.append(
                {
                    "topic": label,
                    "difficulty": "intermediate",
                    "estimated_hours": 2,
                    "source_document": doc_name_by_id.get(document_id, "selected documents"),
                }
            )

    # Final enrichment: infer concise keywords directly from document text.
    if len(catalog) < 8:
        for doc in docs:
            for topic in _infer_topics_from_text(getattr(doc, "full_text", "")[:50000]):
                catalog.append(
                    {
                        "topic": topic,
                        "difficulty": "intermediate",
                        "estimated_hours": 2,
                        "source_document": getattr(doc, "filename", "selected documents"),
                    }
                )

    # De-duplicate by topic + source and keep stable order.
    seen = set()
    deduped = []
    for item in catalog:
        key = (item["topic"].lower(), item["source_document"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


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
        # ✅ PREREQUISITE CHECK: Ensure documents are ingested and readable
        _validate_documents_ingested(current_user["id"], context="study plan generation")

        docs = _get_user_documents(current_user["id"])
        doc_map = {d.id: d for d in docs}

        selected_ids = []
        if req.use_all_documents or not req.document_ids:
            selected_ids = list(doc_map.keys())
        else:
            selected_ids = [doc_id for doc_id in req.document_ids if doc_id in doc_map]

        if not selected_ids:
            raise HTTPException(
                status_code=400,
                detail="No valid documents selected for planning. Choose one or more uploaded documents."
            )

        selected_names = [doc_map[doc_id].filename for doc_id in selected_ids]
        selected_docs = [doc_map[doc_id] for doc_id in selected_ids]
        selected_text = get_full_texts_for_documents(current_user["id"], selected_ids)
        if not selected_text.strip():
            raise HTTPException(
                status_code=412,
                detail="Selected documents have no extracted text. Please re-upload those documents."
            )

        topic_catalog = _build_topic_catalog_from_docs(selected_docs)
        
        constraints = {
            "daily_hours": req.daily_hours,
            "weak_subjects": req.weak_subjects,
            "start_date": req.start_date,
            "document_ids": selected_ids,
            "topic_catalog": topic_catalog,
        }
        plans = generate_plans(
            req.request,
            constraints,
            full_text=selected_text,
            selected_document_names=selected_names,
        )
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

        return {
            "plan": best,
            "calendar_events": len(event_ids),
            "plan_id": plan_id,
            "selected_documents": [{"id": i, "filename": doc_map[i].filename} for i in selected_ids],
        }
    except HTTPException:
        raise
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
        # ✅ PREREQUISITE CHECK: Ensure documents are ingested
        _validate_documents_ingested(current_user["id"], context="prerequisite analysis")
        
        import json

        db_session = Session()
        doc = db_session.query(DocModel).filter_by(id=doc_id, user_id=current_user["id"]).first()
        db_session.close()

        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # Use cached analysis if available
        if doc.analysis_json:
            analysis = json.loads(doc.analysis_json)
            topics = analysis.get("topics_covered", []) if isinstance(analysis, dict) else []
            prereqs = analysis.get("prerequisites", []) if isinstance(analysis, dict) else []
            # If cached analysis is effectively empty, regenerate once from full text.
            if (not topics and not prereqs) and doc.full_text:
                from backend.enhanced_ingest import analyse_document
                analysis = analyse_document(doc.full_text, doc.filename)
                db_session = Session()
                doc_to_update = db_session.query(DocModel).filter_by(id=doc_id, user_id=current_user["id"]).first()
                if doc_to_update:
                    doc_to_update.analysis_json = json.dumps(analysis)
                    db_session.commit()
                db_session.close()
            from backend.enhanced_ingest import format_prerequisite_report
            return {
                "doc_id": doc_id,
                "filename": doc.filename,
                "analysis": analysis,
                "report": format_prerequisite_report(analysis)
            }

        # Generate fresh analysis from full text
        if not doc.full_text:
            raise HTTPException(
                status_code=412,
                detail="❌ Document has no extracted text — cannot analyze prerequisites. "
                       "The model is unable to read this document. Please re-upload it."
            )

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


def _fallback_quiz_from_analysis(doc, analysis: dict, num_questions: int, topic_hints: list[str] | None = None) -> list[dict]:
    """Produce deterministic, document-grounded MCQs when LLM quiz generation fails."""
    def _clean_topic(text: str) -> str:
        cleaned = " ".join(str(text or "").split())
        cleaned = cleaned.strip("-:;,. ")
        if any(token in cleaned for token in ["?", "=", "/", "\\", "&", "#"]):
            return ""
        if "," in cleaned or ";" in cleaned or ":" in cleaned:
            return ""
        if "(" in cleaned or ")" in cleaned:
            return ""
        if len(cleaned.split()) > 8:
            return ""
        if len(cleaned) > 72:
            cleaned = cleaned[:72].rstrip() + "..."
        return cleaned or "Core concepts"

    topics = []
    if topic_hints:
        for hint in topic_hints:
            label = _clean_topic(hint)
            if label:
                topics.append(label)

    if isinstance(analysis, dict):
        for item in (analysis.get("topics_covered") or []):
            if isinstance(item, dict) and item.get("topic"):
                label = _clean_topic(item["topic"])
                if label:
                    topics.append(label)
            elif isinstance(item, str):
                label = _clean_topic(item)
                if label:
                    topics.append(label)

    if not topics:
        lines = [ln.strip(" -\t") for ln in (doc.full_text or "").splitlines() if ln.strip()]
        topics = []
        for line in lines:
            if not (6 <= len(line) <= 120):
                continue
            label = _clean_topic(line)
            if label:
                topics.append(label)
            if len(topics) >= 8:
                break

    if not topics:
        topics = ["Core concepts from uploaded document"]

    difficulties = ["easy", "medium", "hard"]
    questions = []
    for i in range(max(1, num_questions)):
        topic = topics[i % len(topics)]
        distractors = [t for t in topics if t != topic]
        while len(distractors) < 3:
            distractors.append(f"Related concept {len(distractors) + 1}")

        options = {
            "A": f"The document explicitly discusses {topic} as a key concept.",
            "B": f"The document focuses primarily on {distractors[0]} instead of {topic}.",
            "C": f"{topic} is mentioned only as unrelated background and not part of the main content.",
            "D": f"The document states that {topic} should be ignored while studying.",
        }

        questions.append(
            {
                "question_number": i + 1,
                "topic": topic,
                "difficulty": difficulties[i % len(difficulties)],
                "question": f"According to the uploaded document, what is the most accurate statement about {topic}?",
                "options": options,
                "correct_answer": "A",
                "explanation": f"The generated quiz is grounded in the document topic list, where {topic} appears as covered content.",
            }
        )
    return questions[:num_questions]


@app.get("/quiz/{doc_id}")
def generate_quiz(doc_id: int, num_questions: int = 10, current_user: dict = Depends(get_current_user)):
    """Generate MCQ quiz from document content using Ollama."""
    try:
        # ✅ PREREQUISITE CHECK: Ensure documents are ingested and readable
        _validate_documents_ingested(current_user["id"], context="quiz generation")
        
        from backend.llm_router import llm_json
        import json

        db_session = Session()
        doc = db_session.query(DocModel).filter_by(id=doc_id, user_id=current_user["id"]).first()
        db_session.close()

        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        if not doc.full_text:
            raise HTTPException(
                status_code=412,
                detail="❌ Document has no extracted text — cannot generate quiz. "
                       "The model is unable to read this document. Please re-upload it."
            )
        
        if not doc.analysis_json:
            from backend.enhanced_ingest import analyse_document

            analysis = analyse_document(doc.full_text, doc.filename)
            db_session = Session()
            doc_to_update = db_session.query(DocModel).filter_by(id=doc_id, user_id=current_user["id"]).first()
            if doc_to_update:
                doc_to_update.analysis_json = json.dumps(analysis)
                db_session.commit()
            db_session.close()
            doc.analysis_json = json.dumps(analysis)

        # Use analysis topics to guide quiz generation
        topics_context = ""
        analysis = {}
        try:
            analysis = json.loads(doc.analysis_json)
            topics = analysis.get("topics_covered", [])
            if topics:
                topic_names = [t["topic"] for t in topics]
                topics_context = f"\nFocus on these topics: {', '.join(topic_names)}"
        except Exception as e:
            import logging
            logging.warning(f"Could not parse analysis JSON: {e}")

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

        questions = []
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(llm_json, prompt, "", 0.3)
                raw_questions = future.result(timeout=40)

            if isinstance(raw_questions, list):
                questions = raw_questions
            elif isinstance(raw_questions, dict):
                questions = (
                    raw_questions.get("questions")
                    or raw_questions.get("quiz")
                    or raw_questions.get("items")
                    or []
                )
            else:
                questions = []
        except FutureTimeoutError:
            logger.warning("LLM quiz generation timed out; using deterministic fallback quiz.")
        except Exception as e:
            logger.warning("LLM quiz generation failed (%s). Falling back to deterministic quiz.", e)

        if not isinstance(questions, list) or len(questions) == 0:
            doc_topic_hints = [x.get("topic", "") for x in _build_topic_catalog_from_docs([doc])]
            questions = _fallback_quiz_from_analysis(doc, analysis, num_questions, topic_hints=doc_topic_hints)

        # Normalize each question shape.
        normalized_questions = []
        for idx, q in enumerate(questions, 1):
            if not isinstance(q, dict):
                continue
            options = q.get("options") or {}
            if not isinstance(options, dict):
                options = {}
            # Force A/B/C/D keys if LLM returned arrays or wrong keys.
            if set(options.keys()) != {"A", "B", "C", "D"}:
                vals = list(options.values()) if options else []
                while len(vals) < 4:
                    vals.append(f"Option {len(vals) + 1}")
                options = {"A": vals[0], "B": vals[1], "C": vals[2], "D": vals[3]}

            normalized_questions.append({
                "question_number": idx,
                "topic": q.get("topic", "Document concepts"),
                "difficulty": q.get("difficulty", "medium"),
                "question": q.get("question", "Question unavailable"),
                "options": options,
                "correct_answer": q.get("correct_answer", "A"),
                "explanation": q.get("explanation", "Based on the uploaded document."),
            })

        questions = normalized_questions
        if not questions:
            raise ValueError("Quiz normalization produced no valid questions")

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