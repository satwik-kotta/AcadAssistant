import json
import logging
from backend.models import Session, StudyPlan, Task
from backend.calendar_tool import get_calendar_service, schedule_plan
from backend.llm_router import llm_json, llm_call
from backend.timetable import add_timeframes_to_plan

logger = logging.getLogger(__name__)

REPLAN_SYSTEM = """You are an expert academic schedule optimizer.
You receive a student's current study plan as JSON and their feedback in natural language.
You must intelligently modify the plan to satisfy EXACTLY what they asked.
Return ONLY valid JSON with the same structure as the input plan. No explanation, no markdown."""


def _fallback_replan(current_plan: dict, feedback: str) -> dict:
    """Rule-based fallback when LLM is unavailable."""
    new_plan = json.loads(json.dumps(current_plan))
    fb = feedback.lower()

    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    free_days = [d.capitalize() for d in day_names if f"keep {d}" in fb or f"{d} free" in fb or f"free {d}" in fb]
    overloaded = any(w in fb for w in ["too much", "overload", "reduce", "less", "lighter"])
    missed = any(w in fb for w in ["missed", "skipped", "behind", "couldn't", "forgot"])

    surviving_days = []
    for day in new_plan.get("days", []):
        day_name = day.get("day", "")
        if day_name in free_days:
            continue
        for task in day.get("tasks", []):
            dur = int(task.get("duration_minutes", 30))
            if overloaded:
                task["duration_minutes"] = max(20, int(dur * 0.75))
            elif missed:
                task["duration_minutes"] = dur
        surviving_days.append(day)

    new_plan["days"] = surviving_days
    return new_plan


def detect_intent(message: str) -> str:
    """Classify feedback intent for logging purposes."""
    lowered = message.lower()
    if any(w in lowered for w in ["keep", "free", "off", "no study"]):
        return "free_day"
    if any(w in lowered for w in ["too much", "overload", "reduce", "less", "lighter"]):
        return "overloaded"
    if any(w in lowered for w in ["missed", "skipped", "behind", "couldn't"]):
        return "missed"
    if any(w in lowered for w in ["more time", "extend", "longer", "harder"]):
        return "increase"
    if any(w in lowered for w in ["move", "shift", "reschedule", "swap"]):
        return "reschedule"
    if any(w in lowered for w in ["spread", "distribute", "spread out"]):
        return "redistribute"
    return "other"


def replan(plan_id: int, feedback: str, start_date: str, start_time: str = "09:00") -> dict:
    """
    Intelligently replan based on any natural language feedback.
    Returns {"updated_plan": ..., "calendar_events": N}
    """
    session = Session()
    db_plan = session.query(StudyPlan).filter_by(id=plan_id).first()

    if not db_plan:
        raise ValueError(f"Plan with id {plan_id} not found")

    current_plan = json.loads(db_plan.plan_json)
    intent = detect_intent(feedback)
    logger.info(f"[Replan] Intent: {intent} | Feedback: {feedback[:80]}")

    prompt = f"""You are an expert academic scheduler. A student has a study plan and is giving you specific feedback about what needs to change.

CURRENT PLAN:
{json.dumps(current_plan, indent=2)}

STUDENT FEEDBACK: "{feedback}"

Read the feedback carefully and make EXACTLY the changes requested. Do not change anything not mentioned.

How to handle common feedback:
- "keep [day] free" or "[day] off" → remove ALL tasks from that day, redistribute those topics proportionally across other days so no content is lost
- "no [topic] on [day]" → move that specific topic to another suitable day
- "too much workload" or "reduce" → cut each task duration by 20-25%, add an extra day if needed to fit remaining content
- "I missed [day/session]" → shift all tasks from that day forward to the next available day, preserving total content
- "more time on [topic]" → increase that topic's duration by 30-50%, reduce another topic slightly to compensate
- "start at [time]" → update strategy field to note the preferred start time; do not change durations
- "spread [topic] across the week" → split that topic into 2-3 smaller sessions across different days
- "[topic] is too hard" → break it into 2 smaller prerequisite chunks on consecutive days
- "reduce [day] workload" → cut tasks on that specific day by 30%, move overflow to adjacent days
- "I want fewer sessions per day" → merge short tasks on the same topic, reduce task count per day

RULES:
1. Never silently drop topics — if a day is freed, redistribute its topics to other days
2. Never add new topics that were not in the original plan
3. Keep the same JSON structure as the input
4. The plan must remain realistic — no day should exceed 8 hours total
5. Preserve task fields like how_to_study, what_to_cover, why_now if they exist

Return the COMPLETE updated plan as JSON:
{{
  "plan_name": "...",
  "strategy": "...",
  "days": [
    {{
      "day": "Monday",
      "study_goal": "...",
      "tasks": [
        {{
          "topic": "...",
          "duration_minutes": 60,
          "priority": "high|medium|low",
          "how_to_study": "...",
          "what_to_cover": "...",
          "why_now": "..."
        }}
      ]
    }}
  ]
}}"""

    try:
        new_plan = llm_json(prompt, REPLAN_SYSTEM, temperature=0.2)
        if not isinstance(new_plan, dict) or "days" not in new_plan:
            raise ValueError("LLM returned invalid plan structure")
        logger.info(f"[Replan] LLM succeeded — {len(new_plan.get('days', []))} days in updated plan")
    except Exception as e:
        logger.warning(f"[Replan] LLM failed ({e}). Using rule-based fallback.")
        new_plan = _fallback_replan(current_plan, feedback)

    # Ensure required top-level fields
    new_plan.setdefault("plan_name", current_plan.get("plan_name", "Updated Plan"))
    new_plan.setdefault("strategy", f"Updated based on: {feedback[:100]}")

    new_plan = add_timeframes_to_plan(new_plan, start_date, start_time)

    # Delete old calendar events
    try:
        service = get_calendar_service()
    except Exception as e:
        logger.warning(f"Calendar unavailable during replan ({e}). Skipping deletions.")
        service = None

    old_tasks = session.query(Task).filter_by(plan_id=plan_id).all()
    for t in old_tasks:
        if t.calendar_event_id and service is not None:
            try:
                service.events().delete(
                    calendarId="primary", eventId=t.calendar_event_id
                ).execute()
            except Exception as e:
                logger.warning(f"Failed to delete calendar event {t.calendar_event_id}: {e}")
        session.delete(t)

    db_plan.plan_json = json.dumps(new_plan)
    session.commit()

    event_ids = schedule_plan(new_plan, start_date, start_time)

    for day_block in new_plan.get("days", []):
        for task in day_block.get("tasks", []):
            session.add(Task(
                plan_id=plan_id,
                day=day_block["day"],
                topic=task["topic"],
                duration_minutes=task["duration_minutes"],
            ))
    session.commit()
    session.close()

    return {"updated_plan": new_plan, "calendar_events": len(event_ids)}