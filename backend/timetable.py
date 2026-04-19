from datetime import datetime, timedelta


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _next_date_for_weekday(base_date: datetime, day_name: str) -> str:
    if day_name not in DAY_NAMES:
        day_name = "Monday"
    target = DAY_NAMES.index(day_name)
    delta = (target - base_date.weekday()) % 7
    return (base_date + timedelta(days=delta)).strftime("%Y-%m-%d")


def add_timeframes_to_plan(
    plan: dict,
    start_date: str,
    start_time: str = "09:00",
    break_minutes: int = 240,
) -> dict:
    """Annotate each task with concrete start/end times and day_date."""
    base = datetime.strptime(start_date, "%Y-%m-%d")

    for day_block in plan.get("days", []):
        day_name = day_block.get("day", "Monday")
        day_date = _next_date_for_weekday(base, day_name)
        day_block["day_date"] = day_date

        current = datetime.strptime(f"{day_date} {start_time}", "%Y-%m-%d %H:%M")
        for task in day_block.get("tasks", []):
            duration = int(task.get("duration_minutes", 30))
            start_dt = current
            end_dt = current + timedelta(minutes=duration)
            task["start_time"] = start_dt.strftime("%H:%M")
            task["end_time"] = end_dt.strftime("%H:%M")
            task["timeframe"] = f"{task['start_time']}-{task['end_time']}"
            current = end_dt + timedelta(minutes=break_minutes)

    return plan
