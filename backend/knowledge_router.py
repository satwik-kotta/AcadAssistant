"""
3-mode knowledge router:
  Mode 1 — Focused: answer from today's chunks
  Mode 2 — Recall:  answer from earlier syllabus chunks (prerequisite)
  Mode 3 — RAG:     answer from full vector search (external)
"""

import json
import logging
import re
from difflib import SequenceMatcher
from backend.gemini_config import get_gemini_model
from backend.models import Session, Document as DocModel

logger = logging.getLogger(__name__)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", (value or "").lower()).strip()


def _topic_match_score(question: str, topic: str) -> float:
    question_norm = _normalize_text(question)
    topic_norm = _normalize_text(topic)
    if not question_norm or not topic_norm:
        return 0.0

    if topic_norm in question_norm or question_norm in topic_norm:
        return 1.0

    question_tokens = set(question_norm.split())
    topic_tokens = set(topic_norm.split())
    if not topic_tokens:
        return 0.0

    overlap = len(question_tokens & topic_tokens) / len(topic_tokens)
    similarity = SequenceMatcher(None, question_norm, topic_norm).ratio()
    return max(overlap, similarity)


def _best_topic_match(question: str, topics: list[str]) -> tuple[str | None, float]:
    best_topic = None
    best_score = 0.0

    for topic in topics:
        score = _topic_match_score(question, topic)
        if score > best_score:
            best_topic = topic
            best_score = score

    return best_topic, best_score


def _collect_recall_topics(today_topics: list[str], previous_topics: list[str], dependency_graph: dict) -> list[str]:
    prerequisite_topics = []
    for topic in today_topics:
        prerequisite_topics.extend(get_all_prerequisites(topic, dependency_graph))
    return list(dict.fromkeys(previous_topics + prerequisite_topics))


# ── Dependency graph ──────────────────────────────────────────────────────────

def build_dependency_graph(topics: list[dict]) -> dict:
    """
    Given a list of topic dicts (from analysis_json topics_covered),
    ask Gemini to build a prerequisite dependency graph.

    Returns:
        {
          "Bayes Theorem": ["Conditional Probability", "Probability Basics"],
          "Conditional Probability": ["Sample Space", "Probability Basics"],
          ...
        }
    """
    if not topics:
        return {}

    topic_names = [t["topic"] for t in topics]
    model = get_gemini_model()

    prompt = f"""You are an expert academic curriculum designer.

Given these topics from a student's syllabus:
{json.dumps(topic_names, indent=2)}

Build a prerequisite dependency graph. For each topic, list which OTHER topics 
from this list must be understood first.

Return ONLY a JSON object like this (no markdown, no explanation):
{{
  "Topic A": ["prerequisite 1", "prerequisite 2"],
  "Topic B": ["prerequisite 1"],
  "Topic C": []
}}

Only include topics from the provided list as both keys and values.
If a topic has no prerequisites from this list, use an empty array."""

    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.1}
        )
        raw = (response.text or "").strip()
        raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
        graph = json.loads(raw)
        logger.info(f"Built dependency graph for {len(graph)} topics")
        return graph
    except Exception as e:
        logger.warning(f"Dependency graph build failed ({e}). Using empty graph.")
        return {t: [] for t in topic_names}


def get_all_prerequisites(topic: str, graph: dict, visited: set = None) -> list[str]:
    """Recursively get all prerequisites for a topic."""
    if visited is None:
        visited = set()
    if topic not in graph or topic in visited:
        return []
    visited.add(topic)
    prereqs = graph.get(topic, [])
    all_prereqs = list(prereqs)
    for p in prereqs:
        all_prereqs.extend(get_all_prerequisites(p, graph, visited))
    return list(set(all_prereqs))


def get_suggested_order(graph: dict) -> list[str]:
    """
    Topological sort of topics based on dependency graph.
    Returns topics ordered from foundational → advanced.
    """
    if not graph:
        return []

    in_degree = {topic: 0 for topic in graph}
    dependents = {topic: [] for topic in graph}

    for topic, prereqs in graph.items():
        for prereq in prereqs:
            if prereq not in in_degree:
                in_degree[prereq] = 0
                dependents[prereq] = []
            dependents[prereq].append(topic)
            in_degree[topic] = in_degree.get(topic, 0) + 1

    ordered = []
    ready = [topic for topic, degree in in_degree.items() if degree == 0]

    while ready:
        topic = ready.pop(0)
        ordered.append(topic)

        for dependent in dependents.get(topic, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)

    for topic in graph:
        if topic not in ordered:
            ordered.append(topic)

    return ordered


# ── Similarity check (lightweight, no embeddings needed) ─────────────────────

def _topic_similarity_score(question: str, topic: str, model) -> float:
    """
    Ask Gemini: is this question related to this topic?
    Returns 0.0–1.0
    """
    prompt = f"""On a scale of 0 to 10, how relevant is this question to the topic "{topic}"?
Question: "{question}"
Return ONLY a single integer from 0 to 10. Nothing else."""
    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.0, "max_output_tokens": 5}
        )
        score = int((response.text or "0").strip())
        return min(max(score, 0), 10) / 10.0
    except Exception:
        return 0.0


def classify_question(
    question: str,
    today_topics: list[str],
    previous_topics: list[str],
    dependency_graph: dict | None,
) -> dict:
    """
    Classify a question into one of 3 modes.

    Returns:
        {
          "mode": 1 | 2 | 3,
          "mode_name": "focused" | "recall" | "rag",
          "matched_topic": "topic name or None",
          "explanation": "why this mode was chosen"
        }
    """
    model = get_gemini_model()
    dependency_graph = dependency_graph or {}
    recall_topics = _collect_recall_topics(today_topics, previous_topics, dependency_graph)

    today_match, today_score = _best_topic_match(question, today_topics)
    recall_match, recall_score = _best_topic_match(question, recall_topics)

    if today_match and today_score >= 0.62 and today_score >= recall_score - 0.05:
        return {
            "mode": 1,
            "mode_name": "focused",
            "matched_topic": today_match,
            "explanation": "direct match to today's topic",
        }

    if recall_match and recall_score >= 0.62 and recall_score > today_score + 0.03:
        return {
            "mode": 2,
            "mode_name": "recall",
            "matched_topic": recall_match,
            "explanation": "match to earlier syllabus or prerequisite topic",
        }

    dependency_summary = json.dumps(
        {topic: dependency_graph.get(topic, []) for topic in today_topics if topic in dependency_graph},
        indent=2,
    )

    prompt = f"""You are an intelligent academic tutor routing system.

A student is currently studying these topics TODAY:
{json.dumps(today_topics)}

They have already studied these topics:
{json.dumps(previous_topics)}

These are prerequisite or earlier syllabus topics that should be recalled before using external knowledge:
{json.dumps(recall_topics)}

Today's dependency graph snapshot:
{dependency_summary if today_topics else "{}"}

The student asked:
"{question}"

Classify this question into exactly one of these modes:
1. FOCUSED — The question is directly about today's topics
2. RECALL — The question is about a prerequisite or previously studied topic from the syllabus
3. RAG — The question is about something NOT covered in the syllabus at all

Also identify which topic from the syllabus (if any) this question relates to.

Return ONLY a JSON object:
{{
  "mode": 1,
  "mode_name": "focused",
  "matched_topic": "exact topic name from syllabus or null",
  "explanation": "brief reason"
}}"""

    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.1}
        )
        raw = (response.text or "").strip()
        raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(raw)
        if result.get("mode") == 3 and recall_match and recall_score >= 0.5:
            result["mode"] = 2
            result["mode_name"] = "recall"
            result["matched_topic"] = recall_match
            result["explanation"] = result.get("explanation") or "matched to syllabus prerequisite topic"
        elif result.get("mode") == 3 and today_match and today_score >= 0.5:
            result["mode"] = 1
            result["mode_name"] = "focused"
            result["matched_topic"] = today_match
            result["explanation"] = result.get("explanation") or "matched to today's topic"
        logger.info(f"[Router] Mode {result['mode']} ({result['mode_name']}) — {result.get('explanation','')}")
        return result
    except Exception as e:
        logger.warning(f"Question classification failed ({e}). Falling back to heuristic routing.")
        if today_match:
            return {"mode": 1, "mode_name": "focused", "matched_topic": today_match, "explanation": "heuristic fallback"}
        if recall_match:
            return {"mode": 2, "mode_name": "recall", "matched_topic": recall_match, "explanation": "heuristic fallback"}
        return {"mode": 3, "mode_name": "rag", "matched_topic": None, "explanation": "fallback"}


# ── Mode handlers ─────────────────────────────────────────────────────────────

def answer_focused(question: str, today_chunks: str, today_topics: list[str]) -> str:
    """Mode 1: Answer using only today's study material."""
    model = get_gemini_model()
    response = model.generate_content(
        f"""You are a focused academic tutor. The student is currently studying:
{', '.join(today_topics)}

Answer their question using ONLY the material below. Be clear, concise, and use examples.
If the answer requires prerequisite knowledge, briefly mention it and return to the current topic.

Today's study material:
{today_chunks}

Student question: {question}""",
        generation_config={"temperature": 0.3}
    )
    return response.text


def answer_recall(
    question: str,
    matched_topic: str,
    previous_chunks: str,
    today_topics: list[str],
    dependency_graph: dict,
) -> str:
    """Mode 2: Answer from earlier syllabus chunks, then bridge back to today's topic."""
    model = get_gemini_model()
    prereqs = get_all_prerequisites(matched_topic, dependency_graph) if matched_topic else []

    response = model.generate_content(
        f"""You are a patient academic tutor helping a student recall prerequisite knowledge.

The student is currently studying: {', '.join(today_topics)}
They asked about a prerequisite topic: "{matched_topic}"
This topic's prerequisites are: {', '.join(prereqs) if prereqs else 'none'}

Answer their question clearly using the syllabus material below.
After answering, in 1-2 sentences, bridge back to how this connects to what they're studying today.

Relevant syllabus material:
{previous_chunks}

Student question: {question}""",
        generation_config={"temperature": 0.3}
    )
    return response.text


def answer_rag(question: str, rag_context: str, today_topics: list[str]) -> str:
    """Mode 3: Answer from external RAG context when topic is outside the syllabus."""
    model = get_gemini_model()
    response = model.generate_content(
        f"""You are a helpful academic tutor. The student asked about something 
outside their current syllabus.

They are currently studying: {', '.join(today_topics)}

Answer their question using the context below. Be honest if the topic is outside 
their syllabus — briefly note it, answer clearly, then suggest how it might 
connect to their current studies if relevant.

External context:
{rag_context}

Student question: {question}""",
        generation_config={"temperature": 0.4}
    )
    return response.text


# ── Main router function ──────────────────────────────────────────────────────

def route_and_answer(
    question: str,
    today_topics: list[str],
    previous_topics: list[str],
    today_chunks: str,
    previous_chunks: str,
    rag_context: str = "",
    dependency_graph: dict | None = None,
) -> dict:
    """
    Full 3-mode routing and answering pipeline.

    Returns:
        {
          "answer": "...",
          "mode": 1 | 2 | 3,
          "mode_name": "focused | recall | rag",
          "matched_topic": "...",
        }
    """
    classification = classify_question(
        question, today_topics, previous_topics, dependency_graph
    )
    mode = classification["mode"]
    matched_topic = classification.get("matched_topic")

    if mode == 3 and not rag_context:
        from backend.retriever import retrieve_context

        rag_context = retrieve_context(question, k=6)

    if mode == 1:
        answer = answer_focused(question, today_chunks, today_topics)
    elif mode == 2:
        answer = answer_recall(
            question, matched_topic, previous_chunks,
            today_topics, dependency_graph
        )
    else:
        answer = answer_rag(question, rag_context, today_topics)

    return {
        "answer": answer,
        "mode": mode,
        "mode_name": classification["mode_name"],
        "matched_topic": matched_topic,
    }