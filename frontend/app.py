import streamlit as st
import httpx
from datetime import date

API = "http://localhost:8013"

st.set_page_config(page_title="AI Academic Assistant", layout="wide")
st.title("AI Academic Assistant")

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

# --- Upload ---
st.header("1. Upload your documents")
files = st.file_uploader(
    "Upload syllabus, notes, or assignments (PDF)",
    type=["pdf"],
    accept_multiple_files=True,
    key="upload_docs",
)
if st.button("Ingest documents") and files:
    for f in files:
        try:
            with st.spinner(f"Ingesting {f.name}..."):
                r = httpx.post(
                    f"{API}/upload",
                    files={"file": (f.name, f, "application/pdf")},
                    timeout=300,
                )
                r.raise_for_status()
                data = r.json()
            st.success(f"{f.name}: {data.get('chunks', 0)} chunks ingested")
        except httpx.ReadTimeout:
            st.error(
                f"Upload timed out for {f.name}. Try a smaller PDF or retry."
            )
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", "")
            except Exception:
                detail = e.response.text
            st.error(f"Upload failed for {f.name}: {detail or str(e)}")
        except httpx.RequestError as e:
            st.error(f"Request failed for {f.name}: {e}")
        except Exception as e:
            st.error(f"Unexpected error for {f.name}: {e}")

st.divider()

# --- Plan ---
st.header("2. Generate your study plan")
request_text = st.text_area("What do you need help with?", "Plan my study schedule for this week.")
col1, col2 = st.columns(2)
daily_hours = col1.slider("Daily available hours", 1.0, 8.0, 2.0, 0.5)
start_date = col2.date_input("Start date", date.today(), key="plan_start_date")
weak_subjects = st.text_input("Weak subjects (comma-separated)", "")
start_time = st.text_input("Start time (HH:MM)", "09:00")

if st.button("Generate plan"):
    payload = {
        "request": request_text,
        "daily_hours": daily_hours,
        "weak_subjects": [s.strip() for s in weak_subjects.split(",") if s.strip()],
        "start_date": str(start_date),
        "start_time": start_time,
    }
    try:
        with st.spinner("Generating your personalized plan..."):
            r = httpx.post(f"{API}/plan", json=payload, timeout=180)
            r.raise_for_status()
            data = r.json()
            plan = data["plan"]
            st.session_state["plan_id"] = data.get("plan_id", 1)
            st.session_state["current_plan"] = plan

        st.success(f"Plan created! {data['calendar_events']} events added to Google Calendar.")
        st.subheader(plan["plan_name"])
        st.caption(plan["strategy"])

        for day_block in plan["days"]:
            day = day_block.get("day", "Unknown Day")
            day_date = day_block.get("day_date", "")
            label = day if not day_date else f"{day} ({day_date})"
            
            with st.expander(f"📅 {label}"):
                for task in day_block["tasks"]:
                    # Display: "HH:MM-HH:MM | Topic - 72 min [Priority]"
                    timeframe = task.get("timeframe", f"{task.get('start_time','--:--')}-{task.get('end_time','--:--')}")
                    st.write(f"**{timeframe}** • {task['topic']} ({task['duration_minutes']} min) — [{task['priority']}]")
    except httpx.ReadTimeout:
        st.error("Plan generation timed out. Please retry.")
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            detail = e.response.text
        st.error(f"Plan generation failed: {detail or str(e)}")
    except httpx.RequestError as e:
        st.error(f"Request failed while generating plan: {e}")
    except Exception as e:
        st.error(f"Unexpected error while generating plan: {e}")

st.divider()

# --- Feedback ---
st.header("3. Give feedback")
feedback_msg = st.text_input("Tell me how it's going", "Too much workload, I need less per day")
feedback_date = st.date_input("Reschedule from", date.today(), key="feedback_date")

if st.button("Update plan") and "plan_id" in st.session_state:
    try:
        r = httpx.post(
            f"{API}/feedback",
            json={
                "plan_id": st.session_state["plan_id"],
                "feedback": feedback_msg,
                "start_date": str(feedback_date),
                "start_time": start_time,
            },
            timeout=180,
        )
        r.raise_for_status()
        st.success("Plan updated and calendar rescheduled!")
        updated = r.json()["updated_plan"]
        st.session_state["current_plan"] = updated
        for day_block in updated["days"]:
            day = day_block.get("day", "Unknown Day")
            day_date = day_block.get("day_date", "")
            label = day if not day_date else f"{day} ({day_date})"
            
            with st.expander(f"📅 Updated - {label}"):
                for task in day_block["tasks"]:
                    timeframe = task.get("timeframe", f"{task.get('start_time','--:--')}-{task.get('end_time','--:--')}")
                    st.write(f"**{timeframe}** • {task['topic']} ({task['duration_minutes']} min) — [{task['priority']}]")
    except httpx.ReadTimeout:
        st.error("Replanning timed out. Please retry.")
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            detail = e.response.text
        st.error(f"Plan update failed: {detail or str(e)}")
    except httpx.RequestError as e:
        st.error(f"Request failed while updating plan: {e}")
    except Exception as e:
        st.error(f"Unexpected error while updating plan: {e}")

st.divider()

# --- Chatbot ---
st.header("4. Chat with your academic assistant")

for msg in st.session_state["chat_history"]:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

chat_input = st.chat_input("Ask anything about your study materials or plan...")
if chat_input:
    st.session_state["chat_history"].append({"role": "user", "content": chat_input})
    with st.chat_message("user"):
        st.write(chat_input)

    try:
        payload = {
            "message": chat_input,
            "history": st.session_state["chat_history"][-12:],
            "plan_id": st.session_state.get("plan_id"),
            "current_plan": st.session_state.get("current_plan"),
            "start_date": str(start_date),
            "start_time": start_time,
        }
        with st.spinner("Assistant is thinking..."):
            r = httpx.post(f"{API}/chat", json=payload, timeout=120)
            r.raise_for_status()
            resp = r.json()
            reply = resp.get("reply", "I could not generate a response right now.")
            updated_plan = resp.get("updated_plan")
            if updated_plan:
                st.session_state["current_plan"] = updated_plan
    except httpx.ReadTimeout:
        reply = "I timed out while generating a response. Please try again."
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            detail = e.response.text
        reply = f"Chat request failed: {detail or str(e)}"
    except httpx.RequestError as e:
        reply = f"Network error during chat: {e}"
    except Exception as e:
        reply = f"Unexpected chat error: {e}"

    st.session_state["chat_history"].append({"role": "assistant", "content": reply})
    with st.chat_message("assistant"):
        st.write(reply)

if st.session_state.get("current_plan"):
    st.divider()
    st.subheader("📊 Live Timetable (Updated via Chat)")
    p = st.session_state["current_plan"]
    
    # Create a formatted view of the entire week
    for day_block in p.get("days", []):
        day = day_block.get("day", "Unknown Day")
        day_date = day_block.get("day_date", "")
        label = day if not day_date else f"{day} • {day_date}"
        
        st.markdown(f"### {label}")
        for task in day_block.get("tasks", []):
            timeframe = task.get("timeframe", f"{task.get('start_time','--:--')}-{task.get('end_time','--:--')}")
            topic = task.get("topic", "Study")
            duration = task.get("duration_minutes", 0)
            priority = task.get("priority", "Normal")
            
            # Format: "🕐 HH:MM-HH:MM | Topic • 72 min • High Priority"
            st.markdown(f"🕐 **{timeframe}** | {topic} • {duration} min • ⭐ {priority}")