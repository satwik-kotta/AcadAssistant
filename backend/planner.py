import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from backend.retriever import retrieve_context
from backend.gemini_config import get_gemini_model
from backend.document_utils import get_all_full_texts

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert academic curriculum planner.
Generate exactly 3 different study plans as a JSON array.
Each plan must follow this exact structure:
{
  "plan_name": "string",
  "strategy": "string",
  "days": [
    {
      "day": "Monday",
      "tasks": [
        {"topic": "string", "duration_minutes": 60, "priority": "high|medium|low"}
      ]
    }
  ]
}
Return ONLY the JSON array. No markdown, no explanation, no code fences."""


def _fallback_plans(constraints: dict) -> list:
    daily_hours = float(constraints.get("daily_hours", 2))
    per_day = max(30, int(daily_hours * 60))
    days_off = [d.lower() for d in constraints.get("days_off", [])]

    all_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    available_days = [d for d in all_days if d.lower() not in days_off]

    topics = ["Review core concepts", "Practice problems", "Summarize notes",
              "Revision and recall", "Mock quiz"]
    day_sets = [available_days[:5], available_days[:4], available_days[::2][:4]]
    strategies = ["Balanced routine", "Deep-work sessions", "Distributed practice"]

    plans = []
    for i, days in enumerate(day_sets):
        blocks = []
        for d in days:
            t1 = topics[(i + len(d)) % len(topics)]
            t2 = topics[(i + len(d) + 1) % len(topics)]
            blocks.append({
                "day": d,
                "tasks": [
                    {"topic": t1, "duration_minutes": int(per_day * 0.6), "priority": "high"},
                    {"topic": t2, "duration_minutes": int(per_day * 0.4), "priority": "medium"},
                ]
            })
        plans.append({"plan_name": f"Study Plan Option {i+1}", "strategy": strategies[i], "days": blocks})
    return plans


def generate_plans(user_request: str, constraints: dict) -> list:
    try:
        # Try to use intelligent plan builder with dependency graph
        try:
            from backend.study_session import (
                get_all_document_analysis,
                build_intelligent_plan_prompt,
            )
            all_topics, dependency_graph = get_all_document_analysis()
            full_text = get_all_full_texts()

            if all_topics and dependency_graph:
                prompt = build_intelligent_plan_prompt(
                    user_request, constraints, full_text,
                    all_topics, dependency_graph
                )
                model = get_gemini_model()
                ex = ThreadPoolExecutor(max_workers=1)
                future = ex.submit(
                    model.generate_content,
                    [SYSTEM_PROMPT, prompt],
                    generation_config={"temperature": 0.7},
                    request_options={"timeout": 40},
                )
                try:
                    response = future.result(timeout=45)
                finally:
                    ex.shutdown(wait=False, cancel_futures=True)

                raw = (response.text or "").strip()
                raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
                plans = json.loads(raw)
                if isinstance(plans, list) and len(plans) > 0:
                    logger.info(f"Generated {len(plans)} intelligent plans using dependency graph")
                    return plans
        except Exception as e:
            logger.warning(f"Intelligent planner failed ({e}), falling back to basic planner")

        # Basic planner fallback
        context = retrieve_context(user_request)
        model = get_gemini_model()
        user_message = f"""
Academic context from uploaded documents:
{context}

Student request: {user_request}

Constraints:
- Daily hours: {constraints.get('daily_hours', 2)}
- Days off: {constraints.get('days_off', [])}
- Weak subjects: {constraints.get('weak_subjects', [])}
- Topic constraints: {constraints.get('topic_constraints', 'none')}
- Start date: {constraints.get('start_date', 'today')}

Generate 3 study plans as a JSON array."""

        ex = ThreadPoolExecutor(max_workers=1)
        future = ex.submit(
            model.generate_content,
            [SYSTEM_PROMPT, user_message],
            generation_config={"temperature": 0.7},
            request_options={"timeout": 40},
        )
        try:
            response = future.result(timeout=45)
        except FutureTimeoutError:
            future.cancel()
            ex.shutdown(wait=False, cancel_futures=True)
            logger.warning("Gemini planning timed out. Using fallback.")
            return _fallback_plans(constraints)
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

        raw = (response.text or "").strip()
        raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
        plans = json.loads(raw)

        if not isinstance(plans, list) or len(plans) == 0:
            raise ValueError("LLM did not return a valid list of plans")
        return plans

    except Exception as e:
        logger.warning(f"Planning failed ({e}). Using fallback.")
        return _fallback_plans(constraints)