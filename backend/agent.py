import os
import json
import logging
import re
import google.generativeai as genai
from dotenv import load_dotenv
from backend.planner import generate_plans
from backend.scorer import select_best_plan
from backend.calendar_tool import schedule_plan
from backend.feedback import replan
from backend.models import Session, StudyPlan, Task, Document as DocModel
from backend.timetable import add_timeframes_to_plan
from backend.gemini_config import get_gemini_model, get_gemini_api_key, DEFAULT_MODEL
from backend.document_utils import get_all_full_texts, format_prerequisite_report

load_dotenv()
logger = logging.getLogger(__name__)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", (value or "").lower()).strip()


def _looks_like_schedule_update(message: str) -> bool:
    lowered = (message or "").lower()
    return any(keyword in lowered for keyword in [
        "keep ", "free", "reschedule", "update plan", "update my plan", "change my plan",
        "too much", "less work", "reduce", "spread", "missed", "skip", "start at", "start from",
        "more time", "longer breaks", "move", "move it"
    ])


def _looks_like_schedule_query(message: str) -> bool:
    lowered = (message or "").lower()
    return any(keyword in lowered for keyword in [
        "current plan", "my plan", "schedule", "timetable", "what am i studying", "show me my plan",
        "show my plan", "current schedule", "what is my schedule"
    ])


def _looks_like_document_query(message: str) -> bool:
    lowered = (message or "").lower()
    return any(keyword in lowered for keyword in [
        "document", "notes", "syllabus", "prerequisite", "prerequisites", "prepare", "what is",
        "what are", "explain", "tell me about", "topics", "covered"
    ])


def _extract_search_terms(message: str) -> list[str]:
    words = [w for w in re.findall(r"[a-zA-Z0-9_]+", (message or "").lower()) if len(w) > 2]
    stopwords = {
        "what", "does", "this", "that", "with", "from", "into", "your", "about", "show", "tell",
        "need", "know", "please", "help", "me", "for", "the", "and", "are", "how", "why", "can",
        "you", "his", "her", "their", "what's", "whats", "is", "was", "were", "be", "been"
    }
    return [w for w in words if w not in stopwords]


def _extract_relevant_snippets(text: str, terms: list[str], limit: int = 4) -> list[str]:
    if not text:
        return []
    snippets = []
    for block in re.split(r"\n\s*---\s*\n", text):
        block_norm = _normalize_text(block)
        score = sum(1 for term in terms if term in block_norm)
        if score > 0:
            snippets.append((score, block.strip()))
    snippets.sort(key=lambda item: (-item[0], len(item[1])))
    return [snippet for _, snippet in snippets[:limit]]


def _local_fallback_reply(user_message: str, session_state: dict) -> tuple[str, dict | None]:
    from backend.study_session import get_session_context

    plan_id = session_state.get("plan_id")

    if _looks_like_schedule_update(user_message):
        start_date = session_state.get("start_date") or "2026-04-18"
        start_time = session_state.get("start_time") or "09:00"
        return execute_tool(
            "update_study_plan",
            {
                "feedback": user_message,
                "start_date": start_date,
                "start_time": start_time,
            },
            session_state,
        )

    if _looks_like_schedule_query(user_message):
        return execute_tool("get_current_schedule", {}, session_state)

    if "prerequisite" in (user_message or "").lower() or "prepare" in (user_message or "").lower() or "overview" in (user_message or "").lower():
        return execute_tool("get_document_analysis", {}, session_state)

    try:
        ctx = get_session_context(plan_id) if plan_id else {}
    except Exception as e:
        logger.warning(f"Local fallback could not load session context: {e}")
        ctx = {}
    today_chunks = ctx.get("today_chunks", "")
    previous_chunks = ctx.get("previous_chunks", "")
    all_text = get_all_full_texts()
    search_terms = _extract_search_terms(user_message)

    candidates = []
    for label, text in [("today", today_chunks), ("earlier", previous_chunks), ("documents", all_text)]:
        for snippet in _extract_relevant_snippets(text, search_terms, limit=2):
            candidates.append((label, snippet))

    if candidates:
        lines = ["I couldn't reach the model, so I used your syllabus materials directly."]
        for label, snippet in candidates[:3]:
            lines.append(f"\n[{label} material]\n{snippet[:1200]}")
        if plan_id:
            lines.append("\nIf you want, I can also update your plan or show the current schedule.")
        return "\n".join(lines), None

    if all_text:
        return (
            "I couldn't reach the model, but I can still see your uploaded documents. Try asking about a topic from the syllabus, "
            "or ask me to show your current plan.",
            None,
        )

    return (
        "I couldn't reach the model and I don't have any uploaded documents yet. Upload a syllabus first, or ask me to show your current plan.",
        None,
    )

SYSTEM_INSTRUCTION = """You are an intelligent AI academic assistant. You help students manage 
their studies end-to-end — planning, scheduling, answering questions, and adapting dynamically.

You understand natural language constraints like:
- "Keep Tuesdays free"
- "No math on Thursdays"
- "I study better in the evening, start at 6pm"
- "Spread ML topics across the whole week"
- "Give me a 2-hour gap between sessions"
- "Reduce Monday workload by 30%"
- "I missed yesterday, reschedule the rest"

When the user gives ANY constraint or preference about their schedule — days off, topics to 
avoid on certain days, timing preferences, workload changes — call update_study_plan and pass 
the FULL original message as the feedback so the replanner can handle it intelligently.

When a user asks about their documents, prerequisites, or what they need to study — use 
answer_from_documents which uses a 3-mode intelligent router:
  Mode 1 — answers from today's study topics (focused)
  Mode 2 — answers from earlier syllabus topics (prerequisite recall)
  Mode 3 — answers from external knowledge (RAG fallback)

When the user asks what they need to prepare or what prerequisites exist — call get_document_analysis.

Always be friendly, specific, and actionable. Never make up document content."""

tools = [
    genai.protos.Tool(function_declarations=[

        genai.protos.FunctionDeclaration(
            name="generate_study_plan",
            description="""Generate a personalized study plan. Call this when the user asks to 
plan, schedule, or organize their studies. Extract any constraints they mention 
(days off, weak subjects, preferred times, topics to prioritize) and pass them.""",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "request": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="Full user request in natural language"
                    ),
                    "daily_hours": genai.protos.Schema(
                        type=genai.protos.Type.NUMBER,
                        description="Hours available per day, default 2"
                    ),
                    "weak_subjects": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="Comma-separated weak subjects"
                    ),
                    "days_off": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="Comma-separated days to keep free, e.g. 'Tuesday,Sunday'"
                    ),
                    "topic_constraints": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="Topic/day constraints e.g. 'No Math on Thursday, ML only on weekends'"
                    ),
                    "start_date": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="Start date YYYY-MM-DD"
                    ),
                    "start_time": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="Start time HH:MM, default 09:00"
                    ),
                },
                required=["request", "start_date"]
            )
        ),

        genai.protos.FunctionDeclaration(
            name="update_study_plan",
            description="""Update the current plan based on ANY user feedback or constraint.
Call this when the user says ANYTHING that should change their schedule:
- Days to keep free ("keep Tuesdays free")
- Topics to avoid on certain days ("no physics on Monday")
- Timing changes ("start at 7pm instead")
- Workload changes ("too much on Wednesday, reduce it")
- Missed sessions ("I missed yesterday")
- Gap changes ("give me longer breaks")
- Redistribute topics ("spread ML across the whole week")
Pass the full original user message as feedback.""",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "feedback": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="The full user message describing what they want changed"
                    ),
                    "start_date": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="Date to reschedule from YYYY-MM-DD"
                    ),
                    "start_time": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="Preferred start time HH:MM"
                    ),
                },
                required=["feedback", "start_date"]
            )
        ),

        genai.protos.FunctionDeclaration(
            name="get_current_schedule",
            description="Show the user's current study schedule or timetable.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "dummy": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="Not used"
                    ),
                },
                required=[]
            )
        ),

        genai.protos.FunctionDeclaration(
            name="answer_from_documents",
            description="""Answer any question about the student's documents or study material.
Uses a 3-mode intelligent router:
- Today's topics (focused learning)
- Earlier syllabus topics (prerequisite recall)  
- External knowledge (RAG fallback)
Use for questions about topics, deadlines, concepts, assignments, exam dates, or anything academic.""",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "question": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="The user's question"
                    ),
                },
                required=["question"]
            )
        ),

        genai.protos.FunctionDeclaration(
            name="get_document_analysis",
            description="""Show the prerequisite analysis for uploaded documents.
Call when the user asks what they need to know before starting, what prerequisites
are needed, how to prepare, or wants an overview of what was uploaded.""",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "dummy": genai.protos.Schema(
                        type=genai.protos.Type.STRING,
                        description="Not used"
                    ),
                },
                required=[]
            )
        ),
    ])
]


# ── Tool executor ─────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, args: dict, session_state: dict) -> tuple[str, dict | None]:
    """Returns (text_result, updated_plan_or_None)"""

    if tool_name == "generate_study_plan":
        days_off = [d.strip() for d in args.get("days_off", "").split(",") if d.strip()]
        topic_constraints = args.get("topic_constraints", "")

        constraints = {
            "daily_hours": args.get("daily_hours", 2),
            "weak_subjects": [s.strip() for s in args.get("weak_subjects", "").split(",") if s.strip()],
            "start_date": args.get("start_date"),
            "days_off": days_off,
            "topic_constraints": topic_constraints,
        }
        start_date = args.get("start_date", "2026-04-18")
        start_time = args.get("start_time", "09:00")

        # Enrich request with full document context
        full_text = get_all_full_texts()
        enriched_request = args["request"]
        if full_text:
            enriched_request = (
                f"{args['request']}\n\n"
                f"[Document context for planning:]\n{full_text[:20000]}"
            )

        plans = generate_plans(enriched_request, constraints)
        best = select_best_plan(plans, constraints)
        best = add_timeframes_to_plan(best, start_date, start_time)

        db_session = Session()
        db_plan = StudyPlan(
            plan_json=json.dumps(best),
            score=best.get("score", 0),
            constraints_json=json.dumps(constraints)
        )
        db_session.add(db_plan)
        db_session.commit()
        plan_id = db_plan.id

        event_ids = schedule_plan(best, start_date, start_time)

        for day_block in best.get("days", []):
            for task in day_block["tasks"]:
                db_session.add(Task(
                    plan_id=plan_id,
                    day=day_block["day"],
                    topic=task["topic"],
                    duration_minutes=task["duration_minutes"]
                ))
        db_session.commit()
        db_session.close()

        session_state["plan_id"] = plan_id
        session_state["current_plan"] = best
        session_state["start_date"] = start_date
        session_state["start_time"] = start_time
        session_state["constraints"] = constraints

        summary = f"Plan **'{best['plan_name']}'** created! {len(event_ids)} events added to Google Calendar.\n\n"
        summary += f"*Strategy: {best.get('strategy', '')}*\n\n"
        for day in best["days"]:
            day_label = day.get("day", "")
            day_date = day.get("day_date", "")
            label = f"{day_label} ({day_date})" if day_date else day_label
            summary += f"**{label}:**\n"
            for t in day["tasks"]:
                tf = t.get("timeframe", "")
                summary += f"  - {tf} {t['topic']} ({t['duration_minutes']} min) [{t['priority']}]\n"

        if days_off:
            summary += f"\n✅ Days kept free: {', '.join(days_off)}"
        if topic_constraints:
            summary += f"\n✅ Constraints applied: {topic_constraints}"

        return summary, best

    elif tool_name == "update_study_plan":
        plan_id = session_state.get("plan_id")
        if not plan_id:
            return "I don't have an active plan to update. Please generate a plan first.", None

        start_date = args.get("start_date", session_state.get("start_date", "2026-04-18"))
        start_time = args.get("start_time", session_state.get("start_time", "09:00"))

        result = replan(plan_id, args["feedback"], start_date, start_time)
        new_plan = result["updated_plan"]

        session_state["current_plan"] = new_plan
        session_state["start_date"] = start_date
        session_state["start_time"] = start_time

        summary = f"Got it! Plan updated. {result['calendar_events']} calendar events rescheduled.\n\n"
        for day in new_plan["days"]:
            day_label = day.get("day", "")
            day_date = day.get("day_date", "")
            label = f"{day_label} ({day_date})" if day_date else day_label
            summary += f"**{label}:**\n"
            for t in day["tasks"]:
                tf = t.get("timeframe", "")
                summary += f"  - {tf} {t['topic']} ({t['duration_minutes']} min) [{t['priority']}]\n"
        return summary, new_plan

    elif tool_name == "get_current_schedule":
        plan = session_state.get("current_plan")
        plan_id = session_state.get("plan_id")

        if not plan and plan_id:
            db_session = Session()
            db_plan = db_session.query(StudyPlan).filter_by(id=plan_id).first()
            db_session.close()
            if db_plan:
                plan = json.loads(db_plan.plan_json)

        if not plan:
            return "No active plan found. Tell me what you want to study and I'll create one!", None

        summary = f"**{plan.get('plan_name', 'Your Study Plan')}**\n"
        summary += f"*{plan.get('strategy', '')}*\n\n"
        for day in plan["days"]:
            day_label = day.get("day", "")
            day_date = day.get("day_date", "")
            label = f"{day_label} ({day_date})" if day_date else day_label
            summary += f"**{label}:**\n"
            for t in day["tasks"]:
                tf = t.get("timeframe", "")
                summary += f"  - {tf} {t['topic']} ({t['duration_minutes']} min, {t['priority']} priority)\n"
            summary += "\n"
        return summary, None

    elif tool_name == "answer_from_documents":
        from backend.knowledge_router import route_and_answer
        from backend.study_session import get_session_context

        plan_id = session_state.get("plan_id")

        if plan_id:
            ctx = get_session_context(plan_id)
            today_topics = ctx.get("today_topics", [])
            previous_topics = ctx.get("previous_topics", [])
            today_chunks = ctx.get("today_chunks", "")
            previous_chunks = ctx.get("previous_chunks", "")
            dependency_graph = ctx.get("dependency_graph", {})
        else:
            today_topics = []
            previous_topics = []
            today_chunks = ""
            previous_chunks = ""
            dependency_graph = {}

        # If no plan exists yet, fall back to full document text
        if not today_topics and not previous_topics:
            full_text = get_all_full_texts()
            if not full_text:
                return "No documents uploaded yet. Please upload your syllabus first.", None
            from backend.llm_router import llm_call
            response_text = llm_call(
                prompt=f"Answer this question using the student's documents:\n\nQuestion: {args['question']}\n\nDocuments:\n{full_text[:40000]}",
                system="Answer based on the provided documents. Be accurate and cite the source material.",
                temperature=0.5
            )
            return response_text, None

        # 3-mode routing
        result = route_and_answer(
            question=args["question"],
            today_topics=today_topics,
            previous_topics=previous_topics,
            today_chunks=today_chunks,
            previous_chunks=previous_chunks,
            rag_context="",
            dependency_graph=dependency_graph,
        )

        mode_labels = {
            1: "📖 Focused — from today's material",
            2: "🔁 Prerequisite recall — from earlier topics",
            3: "🔍 External reference — outside syllabus"
        }
        mode_tag = mode_labels.get(result["mode"], "")
        topic_tag = f" — *{result['matched_topic']}*" if result.get("matched_topic") else ""

        return result["answer"] + f"\n\n*{mode_tag}{topic_tag}*", None

    elif tool_name == "get_document_analysis":
        db_session = Session()
        docs = db_session.query(DocModel).all()
        db_session.close()

        if not docs:
            return "No documents uploaded yet. Please upload your syllabus or notes first.", None

        reports = []
        for doc in docs:
            if doc.analysis_json:
                analysis = json.loads(doc.analysis_json)
                reports.append(format_prerequisite_report(analysis))

        if not reports:
            return "Documents uploaded but analysis unavailable. Try re-uploading.", None

        return "\n\n---\n\n".join(reports), None

    return "I didn't understand that request. Could you rephrase?", None


# ── Main chat function ────────────────────────────────────────────────────────

def chat(user_message: str, history: list, session_state: dict) -> tuple[str, list, dict | None]:
    """
    Main agent chat function.
    Returns (reply_text, updated_history, updated_plan_or_None)
    """
    genai.configure(api_key=get_gemini_api_key())

    model = genai.GenerativeModel(
        DEFAULT_MODEL,
        system_instruction=SYSTEM_INSTRUCTION,
        tools=tools
    )

    # Build Gemini-compatible history
    gemini_history = []
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content") or msg.get("parts", "")
        if isinstance(content, str):
            gemini_history.append({"role": role, "parts": [{"text": content}]})
        elif isinstance(content, list):
            text_parts = [p if isinstance(p, dict) else {"text": str(p)} for p in content]
            if text_parts:
                gemini_history.append({"role": role, "parts": text_parts})

    try:
        chat_session = model.start_chat(history=gemini_history)
        response = chat_session.send_message(user_message)
    except Exception as e:
        logger.error(f"Agent chat error: {e}")
        try:
            fallback, updated_plan = _local_fallback_reply(user_message, session_state)
        except Exception as fallback_error:
            logger.error(f"Local fallback failed: {fallback_error}")
            fallback = (
                "I couldn't reach the model, and the local fallback also failed. "
                "Try again in a moment, or use 'Show me my current plan' / 'Keep Tuesdays free'."
            )
            updated_plan = None

        updated_history = (history or []) + [
            {"role": "user", "parts": [{"text": user_message}]},
            {"role": "model", "parts": [{"text": fallback}]},
        ]
        return fallback, updated_history, updated_plan

    final_reply = ""
    updated_plan = None

    # Agentic loop — up to 5 tool calls per turn
    for _ in range(5):
        part = response.candidates[0].content.parts[0]

        if hasattr(part, "function_call") and part.function_call.name:
            fn = part.function_call
            tool_name = fn.name
            args = dict(fn.args)
            logger.info(f"[Agent] Tool: {tool_name} | Args: {args}")

            tool_result, plan_result = execute_tool(tool_name, args, session_state)
            if plan_result is not None:
                updated_plan = plan_result

            response = chat_session.send_message(
                genai.protos.Content(parts=[
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=tool_name,
                            response={"result": tool_result}
                        )
                    )
                ])
            )
        else:
            final_reply = part.text
            break

    if not final_reply:
        final_reply = "Done! Let me know if you need anything else."

    updated_history = [
        {
            "role": m.role,
            "parts": [p.text if hasattr(p, "text") else "" for p in m.parts]
        }
        for m in chat_session.history
    ]

    return final_reply, updated_history, updated_plan