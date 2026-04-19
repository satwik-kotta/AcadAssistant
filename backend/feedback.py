import json
import logging
from backend.models import Session, StudyPlan, Task
from backend.calendar_tool import get_calendar_service, schedule_plan
from backend.llm_router import llm_json
from backend.timetable import add_timeframes_to_plan

logger = logging.getLogger(__name__)


def _fallback_replan(current_plan: dict, intent: str) -> dict:
    new_plan = json.loads(json.dumps(current_plan))
    for day in new_plan.get("days", []):
        for task in day.get("tasks", []):
            dur = int(task.get("duration_minutes", 30))
            if intent == "overloaded":
                task["duration_minutes"] = max(20, int(dur * 0.75))
            elif intent == "missed":
                task["duration_minutes"] = dur
            else:
                task["duration_minutes"] = max(20, int(dur * 0.9))
    return new_plan

def detect_intent(message: str) -> str:
    """Returns: 'overloaded', 'missed', or 'other'"""
    lowered = message.lower()
    if any(w in lowered for w in ["too much", "overload", "reduce", "less work"]):
        return "overloaded"
    if any(w in lowered for w in ["missed", "skipped", "couldn't", "behind"]):
        return "missed"
    return "other"

def replan(plan_id: int, feedback: str, start_date: str, start_time: str = "09:00"):
    try:
        session = Session()
        db_plan = session.query(StudyPlan).filter_by(id=plan_id).first()
        
        if not db_plan:
            raise ValueError(f"Plan with id {plan_id} not found")
        
        current_plan = json.loads(db_plan.plan_json)
        intent = detect_intent(feedback)

        prompt = f"""
Current study plan (JSON):
{json.dumps(current_plan, indent=2)}

Student feedback: "{feedback}"
Intent detected: {intent}

Instructions:
- If overloaded: reduce tasks per day by 20-30%, extend across more days if needed.
- If missed: shift all remaining tasks forward from today, keeping the same total content.
- Return ONLY the updated plan as JSON (same structure). No explanation.
"""

        try:
            new_plan = llm_json(
                prompt=prompt,
                system="Return ONLY valid JSON representing the updated study plan. No explanation.",
                temperature=0.3
            )
            logger.info("Replanning with LLM router succeeded")
        except Exception as e:
            logger.warning(f"LLM replan failed ({e}). Using fallback replanner.")
            new_plan = _fallback_replan(current_plan, intent)

        new_plan = add_timeframes_to_plan(new_plan, start_date, start_time)

        # Delete old calendar events
        try:
            service = get_calendar_service()
        except Exception as e:
            print(f"⚠️ Calendar unavailable during replan ({e}). Skipping event deletions.")
            service = None

        old_tasks = session.query(Task).filter_by(plan_id=plan_id).all()
        for t in old_tasks:
            if t.calendar_event_id and service is not None:
                try:
                    service.events().delete(
                        calendarId="primary", eventId=t.calendar_event_id
                    ).execute()
                except Exception as e:
                    print(f"⚠️  Failed to delete calendar event {t.calendar_event_id}: {e}")
            session.delete(t)

        # Save updated plan
        db_plan.plan_json = json.dumps(new_plan)
        session.commit()

        # Reschedule in calendar
        event_ids = schedule_plan(new_plan, start_date, start_time)

        for day_block in new_plan.get("days", []):
            for task in day_block["tasks"]:
                t = Task(
                    plan_id=plan_id,
                    day=day_block["day"],
                    topic=task["topic"],
                    duration_minutes=task["duration_minutes"]
                )
                session.add(t)
        session.commit()
        session.close()

        return {"updated_plan": new_plan, "calendar_events": len(event_ids)}
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse plan update response: {str(e)}")
    except Exception as e:
        raise Exception(f"Error replanning: {str(e)}")