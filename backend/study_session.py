"""
Study session manager.
Tracks which topics a student is on today, fetches the right chunks,
and builds dependency-ordered study plans.
"""

import json
import logging
from datetime import date, timedelta
from backend.models import Session, StudyPlan, Document as DocModel
from backend.knowledge_router import build_dependency_graph, get_suggested_order, get_all_prerequisites
from backend.retriever import retrieve_context
from backend.gemini_config import get_gemini_model

logger = logging.getLogger(__name__)


def get_today_topics(plan: dict, target_date: str = None) -> list[str]:
    """
    Given a study plan JSON, return the list of topics scheduled for today
    (or for target_date if provided).
    """
    if target_date is None:
        target_date = str(date.today())

    for day_block in plan.get("days", []):
        day_date = day_block.get("day_date", "")
        if day_date == target_date:
            return [t["topic"] for t in day_block.get("tasks", [])]

    # Fallback: match by day name
    today_name = date.today().strftime("%A")
    for day_block in plan.get("days", []):
        if day_block.get("day", "").lower() == today_name.lower():
            return [t["topic"] for t in day_block.get("tasks", [])]

    return []


def get_previous_topics(plan: dict, target_date: str = None) -> list[str]:
    """Return all topics from days before today in the plan."""
    if target_date is None:
        target_date = str(date.today())

    previous = []
    for day_block in plan.get("days", []):
        day_date = day_block.get("day_date", "")
        if day_date and day_date < target_date:
            previous.extend([t["topic"] for t in day_block.get("tasks", [])])
    return previous


def get_all_plan_topics(plan: dict) -> list[str]:
    """Return all topics across all days."""
    topics = []
    for day_block in plan.get("days", []):
        topics.extend([t["topic"] for t in day_block.get("tasks", [])])
    return topics


def get_chunks_for_topics(topics: list[str], k_per_topic: int = 3) -> str:
    """Retrieve relevant chunks for a list of topics."""
    if not topics:
        return ""
    all_chunks = []
    for topic in topics:
        chunks = retrieve_context(topic, k=k_per_topic)
        if chunks and "No documents" not in chunks:
            all_chunks.append(f"[{topic}]\n{chunks}")
    return "\n\n---\n\n".join(all_chunks)


def get_all_document_analysis() -> tuple[list[dict], dict]:
    """
    Fetch analysis_json from all uploaded documents.
    Returns (all_topics_list, merged_dependency_graph)
    """
    db_session = Session()
    docs = db_session.query(DocModel).all()
    db_session.close()

    all_topics = []
    merged_graph = {}

    for doc in docs:
        if not doc.analysis_json:
            continue
        analysis = json.loads(doc.analysis_json)
        topics = analysis.get("topics_covered", [])
        all_topics.extend(topics)

        # Build dependency graph per document and merge
        graph = build_dependency_graph(topics)
        merged_graph.update(graph)

    return all_topics, merged_graph


def build_intelligent_plan_prompt(
    user_request: str,
    constraints: dict,
    full_text: str,
    all_topics: list[dict],
    dependency_graph: dict,
) -> str:
    """
    Build an enriched planner prompt that includes:
    - Full document context
    - Dependency-ordered topic sequence
    - User constraints (days off, topic restrictions)
    """
    ordered_topics = get_suggested_order(dependency_graph)
    days_off = constraints.get("days_off", [])
    topic_constraints = constraints.get("topic_constraints", "")
    weak_subjects = constraints.get("weak_subjects", [])
    daily_hours = constraints.get("daily_hours", 2)

    topic_details = "\n".join([
        f"- {t['topic']} (difficulty: {t.get('difficulty','?')}, "
        f"~{t.get('estimated_hours', 1)}h, "
        f"prereqs: {', '.join(dependency_graph.get(t['topic'], [])) or 'none'})"
        for t in all_topics
    ])

    prompt = f"""You are an expert academic curriculum planner.

STUDENT REQUEST: {user_request}

CONSTRAINTS:
- Daily available hours: {daily_hours}
- Days to keep completely FREE (no study): {', '.join(days_off) if days_off else 'none'}
- Topic restrictions: {topic_constraints if topic_constraints else 'none'}
- Weak subjects (needs extra time): {', '.join(weak_subjects) if weak_subjects else 'none'}
- Start date: {constraints.get('start_date', 'today')}

TOPICS FROM SYLLABUS (with difficulty and estimated hours):
{topic_details}

DEPENDENCY-ORDERED SEQUENCE (study in this order, foundational first):
{' → '.join(ordered_topics) if ordered_topics else 'as listed above'}

DOCUMENT CONTENT SUMMARY:
{full_text[:15000]}

RULES FOR THE PLAN:
1. NEVER schedule anything on days marked as free: {', '.join(days_off) if days_off else 'none'}
2. Respect topic restrictions exactly: {topic_constraints if topic_constraints else 'none'}
3. Follow the dependency order — never schedule a topic before its prerequisites
4. Give weak subjects 25% more time than estimated
5. Keep daily load within {daily_hours} hours
6. Each task must have a specific topic from the syllabus, not generic names

Generate exactly 3 different study plans as a JSON array. Each plan:
{{
  "plan_name": "string",
  "strategy": "string",
  "days": [
    {{
      "day": "Monday",
      "tasks": [
        {{"topic": "exact topic name", "duration_minutes": 60, "priority": "high|medium|low"}}
      ]
    }}
  ]
}}

IMPORTANT: If a day is in the free days list, do NOT include it in the plan at all.
Return ONLY the JSON array. No markdown. No explanation."""

    return prompt


def get_session_context(plan_id: int, target_date: str = None) -> dict:
    """
    Get full context for the current study session.
    Used by the agent's answer_from_documents tool.

    Returns:
        {
          "today_topics": [...],
          "previous_topics": [...],
          "today_chunks": "...",
          "previous_chunks": "...",
          "dependency_graph": {...},
          "all_topics": [...]
        }
    """
    if target_date is None:
        target_date = str(date.today())

    db_session = Session()
    db_plan = db_session.query(StudyPlan).filter_by(id=plan_id).first()
    db_session.close()

    if not db_plan:
        return {}

    plan = json.loads(db_plan.plan_json)
    today_topics = get_today_topics(plan, target_date)
    previous_topics = get_previous_topics(plan, target_date)

    prerequisite_topics = []
    all_topics, dependency_graph = get_all_document_analysis()
    for topic in today_topics:
        prerequisite_topics.extend(get_all_prerequisites(topic, dependency_graph))

    recall_topics = list(dict.fromkeys(previous_topics + prerequisite_topics))

    today_chunks = get_chunks_for_topics(today_topics, k_per_topic=4)
    previous_chunks = get_chunks_for_topics(recall_topics, k_per_topic=2)

    return {
        "today_topics": today_topics,
        "previous_topics": previous_topics,
        "recall_topics": recall_topics,
        "today_chunks": today_chunks,
        "previous_chunks": previous_chunks,
        "dependency_graph": dependency_graph,
        "all_topics": [t["topic"] for t in all_topics],
    }