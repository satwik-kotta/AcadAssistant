import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from backend.enhanced_ingest import get_all_full_texts
from backend.llm_router import llm_json
from backend.retriever import retrieve_context

logger = logging.getLogger(__name__)


def _difficulty_rank(value: str) -> int:
    v = str(value or "").lower()
    if "advanced" in v:
        return 3
    if "intermediate" in v:
        return 2
    return 1


def _topic_catalog_from_constraints(constraints: dict) -> list[dict]:
    catalog = constraints.get("topic_catalog") or []
    if not isinstance(catalog, list):
        return []

    cleaned = []
    for item in catalog:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        cleaned.append(
            {
                "topic": topic,
                "difficulty": str(item.get("difficulty") or "intermediate"),
                "estimated_hours": int(item.get("estimated_hours") or 2),
                "source_document": str(item.get("source_document") or "selected documents"),
            }
        )

    cleaned.sort(
        key=lambda x: (
            _difficulty_rank(x.get("difficulty")),
            int(x.get("estimated_hours", 0)),
        ),
        reverse=True,
    )
    return cleaned


def _catalog_as_prompt_block(catalog: list[dict]) -> str:
    if not catalog:
        return "No structured topic catalog was available. Infer topics from the full document content."

    lines = []
    for item in catalog[:24]:
        lines.append(
            f"- {item['topic']} | difficulty={item['difficulty']} | estimated_hours={item['estimated_hours']} | source={item['source_document']}"
        )
    return "\n".join(lines)

PLANNER_SYSTEM = """You are an expert academic curriculum planner.
Generate exactly 3 different study plans as a JSON array.
Each plan must have this exact structure:
[
  {
    "plan_name": "string",
    "strategy": "string",
    "summary": "string",
    "days": [
      {
        "day": "Monday",
        "study_goal": "string",
        "tasks": [
          {
            "topic": "string",
            "what_to_cover": "specific concepts from the selected documents",
            "how_to_study": "exact study method to use for this topic",
            "why_now": "why this topic belongs in this time slot",
            "source_document": "document name or section",
            "duration_minutes": 60,
            "priority": "high|medium|low"
          }
        ]
      }
    ]
  }
]
Rules:
- Use only concepts and topics that appear in the selected document content.
- Do not use vague tasks like "do this" or "review stuff".
- Every task topic must name the actual concept to study.
- Every day must explain what to study and why it appears there.
- Include a brief plan summary that references the uploaded material.
Return ONLY the JSON array. No markdown. No explanation."""


def _fallback_plans(constraints: dict) -> list:
    daily_hours = float(constraints.get("daily_hours", 2))
    per_day = max(30, int(daily_hours * 60))
    days_off = [day.lower() for day in constraints.get("days_off", [])]
    all_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    available = [day for day in all_days if day.lower() not in days_off]

    catalog = _topic_catalog_from_constraints(constraints)
    topics = [c["topic"] for c in catalog] or [
        "Review core concepts",
        "Practice problems",
        "Summarize notes",
        "Revision",
        "Mock quiz",
    ]
    day_sets = [available[:5], available[:4], available[::2][:4]]
    strategies = ["Balanced routine", "Deep-work sessions", "Distributed practice"]

    plans = []
    for index, days in enumerate(day_sets):
        blocks = []
        for day in days:
            first_topic = topics[(index + len(day)) % len(topics)]
            second_topic = topics[(index + len(day) + 1) % len(topics)]
            first_meta = next((c for c in catalog if c["topic"] == first_topic), None)
            second_meta = next((c for c in catalog if c["topic"] == second_topic), None)
            blocks.append(
                {
                    "day": day,
                    "study_goal": f"Build momentum on {first_topic.lower()} and connect it to {second_topic.lower()}",
                    "tasks": [
                        {
                            "topic": first_topic,
                            "what_to_cover": (
                                f"Core ideas, definitions, and worked examples for {first_topic.lower()} "
                                f"(difficulty: {(first_meta or {}).get('difficulty', 'intermediate')}, "
                                f"total_estimated_hours: {(first_meta or {}).get('estimated_hours', 2)}h)."
                            ),
                            "how_to_study": "Read, annotate, then answer recall questions without looking back.",
                            "why_now": "This is the main concept for the block and should be learned first.",
                            "source_document": (first_meta or {}).get("source_document", "Selected documents"),
                            "duration_minutes": int(per_day * 0.6),
                            "priority": "high",
                        },
                        {
                            "topic": second_topic,
                            "what_to_cover": (
                                f"Practice and reinforcement for {second_topic.lower()} "
                                f"(difficulty: {(second_meta or {}).get('difficulty', 'intermediate')}, "
                                f"total_estimated_hours: {(second_meta or {}).get('estimated_hours', 2)}h)."
                            ),
                            "how_to_study": "Summarize the topic in your own words and complete a short practice set.",
                            "why_now": "This follows the core topic and helps lock in retention.",
                            "source_document": (second_meta or {}).get("source_document", "Selected documents"),
                            "duration_minutes": int(per_day * 0.4),
                            "priority": "medium",
                        },
                    ],
                }
            )

        plans.append(
            {
                "plan_name": f"Study Plan {index + 1}",
                "strategy": strategies[index],
                "summary": "Fallback plan generated from the uploaded document set.",
                "days": blocks,
            }
        )

    return plans


def _normalize_task(task: dict, default_source: str = "selected documents") -> dict:
    topic = str(task.get("topic") or "Study topic").strip() or "Study topic"
    return {
        "topic": topic,
        "what_to_cover": str(
            task.get("what_to_cover")
            or task.get("focus")
            or f"Key ideas, formulas, and examples for {topic}."
        ).strip(),
        "how_to_study": str(
            task.get("how_to_study")
            or task.get("method")
            or "Read the source section, annotate it, and test yourself with recall questions."
        ).strip(),
        "why_now": str(
            task.get("why_now")
            or task.get("rationale")
            or "This topic fits the current study sequence and supports the next block."
        ).strip(),
        "source_document": str(task.get("source_document") or default_source).strip(),
        "duration_minutes": int(task.get("duration_minutes", 30) or 30),
        "priority": str(task.get("priority", "medium")),
    }


def _normalize_day(day: dict, default_source: str) -> dict:
    return {
        "day": str(day.get("day", "Monday")),
        "study_goal": str(
            day.get("study_goal")
            or day.get("goal")
            or "Cover the listed topics in a focused study block."
        ).strip(),
        "tasks": [
            _normalize_task(task, default_source=default_source)
            for task in (day.get("tasks") or [])
            if isinstance(task, dict)
        ],
    }


def _normalize_plans(raw: dict | list) -> list:
    """Normalize planner LLM output into a list of plan objects."""
    if isinstance(raw, list):
        normalized = []
        for plan in raw:
            if not isinstance(plan, dict) or not plan.get("days"):
                continue
            source = str(plan.get("source") or plan.get("source_document") or "selected documents")
            normalized.append(
                {
                    "plan_name": str(plan.get("plan_name") or "Study Plan"),
                    "strategy": str(plan.get("strategy") or "Balanced routine"),
                    "summary": str(plan.get("summary") or ""),
                    "days": [_normalize_day(day, source) for day in plan.get("days", []) if isinstance(day, dict)],
                }
            )
        return normalized

    if isinstance(raw, dict):
        for key in ["plans", "study_plans", "options", "result"]:
            candidate = raw.get(key)
            if isinstance(candidate, list):
                return _normalize_plans(candidate)

    return []


def generate_plans(
    user_request: str,
    constraints: dict,
    full_text: str | None = None,
    selected_document_names: list[str] | None = None,
) -> list:
    """Generate 3 study plans using the selected document content."""
    effective_text = full_text if full_text is not None else get_all_full_texts()
    if not effective_text or not effective_text.strip():
        logger.error("No documents to plan from.")
        raise ValueError(
            "No documents loaded. The model is unable to generate a study plan without course materials."
        )

    try:
        docs_label = ", ".join(selected_document_names or []) if selected_document_names else "all uploaded documents"
        topic_catalog = _topic_catalog_from_constraints(constraints)
        topic_catalog_block = _catalog_as_prompt_block(topic_catalog)

        prompt = f"""You are planning from these selected documents: {docs_label}

Student request: {user_request}

Constraints:
- Daily hours: {constraints.get('daily_hours', 2)}
- Days off: {constraints.get('days_off', [])}
- Weak subjects: {constraints.get('weak_subjects', [])}
- Topic restrictions: {constraints.get('topic_constraints', 'none')}
- Start date: {constraints.get('start_date', 'today')}

Document content (selected documents only):
{effective_text[:50000]}

Relevant extracted topics from selected documents (difficulty + estimated hours):
{topic_catalog_block}

Generate 3 study plans as a JSON array.

Each plan must:
- use actual topics, section names, formulas, methods, or concepts from the document content above
- prioritize difficult topics earlier and allocate duration proportionally to estimated_hours
- include when to study each topic in the day block
- include how to study that topic using a concrete method such as active recall, worked examples, practice questions, summary writing, or spaced review
- avoid generic wording like "do this" or "review more"
- include a short plan summary that names the document topics being covered"""

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(llm_json, prompt, PLANNER_SYSTEM, 0.5)
            raw_plans = future.result(timeout=50)
        plans = _normalize_plans(raw_plans)
        if plans:
            logger.info("Generated %s plans from selected documents", len(plans))
            return plans
    except FutureTimeoutError:
        logger.warning("Primary planner timed out, using retrieval-assisted planner.")
    except Exception as exc:
        logger.warning("Primary planner failed (%s), trying retrieval-assisted planner", exc)

    try:
        context = retrieve_context(user_request)
        prompt = f"""Academic context:
{context}

Student request: {user_request}

Constraints:
- Daily hours: {constraints.get('daily_hours', 2)}
- Days off: {constraints.get('days_off', [])}
- Weak subjects: {constraints.get('weak_subjects', [])}
- Topic restrictions: {constraints.get('topic_constraints', 'none')}
- Start date: {constraints.get('start_date', 'today')}

Generate 3 study plans as a JSON array.

Each plan must include concrete topics from the uploaded documents, not generic placeholders.
Each task must state what to cover, how to study it, why it appears there, and which document or section it came from."""

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(llm_json, prompt, PLANNER_SYSTEM, 0.5)
            raw_plans = future.result(timeout=45)
        plans = _normalize_plans(raw_plans)
        if plans:
            return plans
    except FutureTimeoutError:
        logger.warning("Retrieval-assisted planner timed out. Using topic-catalog fallback plan.")
    except Exception as exc:
        logger.warning("Basic planner also failed (%s). Using fallback.", exc)

    return _fallback_plans(constraints)
