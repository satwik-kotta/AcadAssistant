import json

from backend.models import Session, Document as DocModel


def get_document_analysis(doc_id: int) -> dict:
    """Fetch stored analysis for a document."""
    session = Session()
    doc = session.query(DocModel).filter_by(id=doc_id).first()
    session.close()
    if not doc or not doc.analysis_json:
        return {}
    return json.loads(doc.analysis_json)


def get_all_full_texts() -> str:
    """Return full text of all uploaded documents concatenated."""
    session = Session()
    docs = session.query(DocModel).all()
    session.close()
    parts = [d.full_text for d in docs if d.full_text]
    return "\n\n---\n\n".join(parts)


def format_prerequisite_report(analysis: dict) -> str:
    """Format the analysis dict into a friendly markdown report for the user."""
    lines = []

    subject = analysis.get("subject", "your document")
    doc_type = analysis.get("document_type", "document")
    summary = analysis.get("summary", "")
    difficulty = analysis.get("difficulty_level", "")
    total_hours = analysis.get("total_estimated_hours", 0)

    lines.append(f"### Document Analysis — {subject}")
    lines.append(f"**Type:** {doc_type.capitalize()}  |  **Difficulty:** {difficulty.capitalize()}  |  **Est. total study time:** {total_hours}h\n")

    if summary:
        lines.append(f"**Summary:** {summary}\n")

    topics = analysis.get("topics_covered", [])
    if topics:
        lines.append("**Topics covered:**")
        for t in topics:
            lines.append(f"  - {t['topic']} ({t.get('difficulty','')}, ~{t.get('estimated_hours',0)}h)")
        lines.append("")

    prereqs = analysis.get("prerequisites", [])
    if prereqs:
        must = [p for p in prereqs if p.get("urgency") == "must_know"]
        good = [p for p in prereqs if p.get("urgency") == "good_to_know"]
        optional = [p for p in prereqs if p.get("urgency") == "optional"]

        lines.append("**Prerequisites before you start:**")

        if must:
            lines.append("\n🔴 **Must know:**")
            for p in must:
                lines.append(f"  - **{p['topic']}** — {p.get('reason','')}")
                if p.get("resources"):
                    lines.append(f"    → *{p['resources']}*")

        if good:
            lines.append("\n🟡 **Good to know:**")
            for p in good:
                lines.append(f"  - **{p['topic']}** — {p.get('reason','')}")
                if p.get("resources"):
                    lines.append(f"    → *{p['resources']}*")

        if optional:
            lines.append("\n🟢 **Optional:**")
            for p in optional:
                lines.append(f"  - **{p['topic']}** — {p.get('reason','')}")
        lines.append("")

    order = analysis.get("suggested_study_order", [])
    if order:
        lines.append("**Suggested study order:**")
        for i, topic in enumerate(order, 1):
            lines.append(f"  {i}. {topic}")
        lines.append("")

    deadlines = analysis.get("key_deadlines", [])
    if deadlines:
        lines.append("**Key deadlines found:**")
        for d in deadlines:
            date = d.get("date") or "date not specified"
            lines.append(f"  - {d['task']} — {date}")

    return "\n".join(lines)