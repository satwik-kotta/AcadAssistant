def score_plan(plan: dict, constraints: dict) -> int:
    score = 0
    daily_hours = constraints.get("daily_hours", 2)
    weak_subjects = [s.lower() for s in constraints.get("weak_subjects", [])]

    for day in plan.get("days", []):
        total_minutes = sum(t["duration_minutes"] for t in day["tasks"])
        # Penalize overloaded days
        if total_minutes <= daily_hours * 60:
            score += 10
        else:
            score -= 5

        # Reward prioritizing weak subjects
        for task in day["tasks"]:
            if any(w in task["topic"].lower() for w in weak_subjects):
                if task["priority"] == "high":
                    score += 5

    return score


def select_best_plan(plans: list, constraints: dict) -> dict:
    scored = [(plan, score_plan(plan, constraints)) for plan in plans]
    scored.sort(key=lambda x: x[1], reverse=True)
    best_plan, best_score = scored[0]
    best_plan["score"] = best_score
    return best_plan
def score_plan(plan: dict, constraints: dict) -> int:
    score = 0
    daily_hours = constraints.get("daily_hours", 2)
    weak_subjects = [s.lower() for s in constraints.get("weak_subjects", [])]

    for day in plan.get("days", []):
        total_minutes = sum(t["duration_minutes"] for t in day["tasks"])
        # Penalize overloaded days
        if total_minutes <= daily_hours * 60:
            score += 10
        else:
            score -= 5

        # Reward prioritizing weak subjects
        for task in day["tasks"]:
            if any(w in task["topic"].lower() for w in weak_subjects):
                if task["priority"] == "high":
                    score += 5

    return score

def select_best_plan(plans: list, constraints: dict) -> dict:
    scored = [(plan, score_plan(plan, constraints)) for plan in plans]
    scored.sort(key=lambda x: x[1], reverse=True)
    best_plan, best_score = scored[0]
    best_plan["score"] = best_score
    return best_plan