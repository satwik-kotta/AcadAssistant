import os
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _calendar_enabled() -> bool:
    return (os.getenv("CALENDAR_ENABLED") or "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def get_calendar_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            os.getenv("GOOGLE_CALENDAR_CREDENTIALS", "credentials.json"), SCOPES
        )
        creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def create_calendar_event(service, topic: str, day_str: str, start_time: str, duration_minutes: int) -> str:
    """day_str: e.g. '2025-07-14', start_time: '09:00'"""
    start_dt = datetime.strptime(f"{day_str} {start_time}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    event = {
        "summary": f"Study: {topic}",
        "description": f"AI-scheduled study session for {topic}",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "Asia/Kolkata"},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 15}],
        },
    }
    result = service.events().insert(calendarId="primary", body=event).execute()
    return result["id"]


def schedule_plan(plan: dict, start_date: str, start_time: str = "09:00"):
    if not _calendar_enabled():
        return []

    try:
        service = get_calendar_service()
    except Exception as e:
        print(f"⚠️ Calendar unavailable ({e}). Continuing without calendar events.")
        return []

    event_ids = []
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    base = datetime.strptime(start_date, "%Y-%m-%d")
    current_time = start_time

    for day_block in plan.get("days", []):
        day_name = day_block.get("day", "Monday")
        if day_name not in day_names:
            day_name = "Monday"

        target_weekday = day_names.index(day_name)
        delta = (target_weekday - base.weekday()) % 7
        day_date = (base + timedelta(days=delta)).strftime("%Y-%m-%d")

        for task in day_block.get("tasks", []):
            try:
                event_id = create_calendar_event(
                    service,
                    task["topic"],
                    day_date,
                    current_time,
                    task["duration_minutes"],
                )
                event_ids.append(event_id)
            except Exception as e:
                print(f"⚠️ Failed creating event for task {task.get('topic')}: {e}")

            h, m = map(int, current_time.split(":"))
            total = h * 60 + m + int(task.get("duration_minutes", 30)) + 15
            current_time = f"{total // 60:02d}:{total % 60:02d}"

        current_time = start_time

    return event_ids