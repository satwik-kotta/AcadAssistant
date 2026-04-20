"""Enhanced document parsing with structure preservation, metadata tracking,
full-text storage, and AI-powered prerequisite extraction."""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import pdfplumber
from pypdf import PdfReader

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    pytesseract = None

from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from backend.embeddings_provider import get_embeddings
from backend.models import Session, Document as DocModel, DocumentChunk
from backend.llm_router import llm_json

logger = logging.getLogger(__name__)
VECTORSTORE_PATH = "vectorstore/index"


def _fallback_analysis_from_text(full_text: str, filename: str) -> dict:
    """Heuristic fallback when LLM output is missing/invalid."""
    text = full_text or ""
    lines = [ln.strip(" -•\t") for ln in text.splitlines() if ln.strip()]
    lowered = text.lower()

    topic_markers = [
        "topics", "syllabus", "module", "chapter", "unit", "includes", "covers", "course content"
    ]
    prereq_markers = [
        "prerequisite", "should know", "background", "before starting", "assumes knowledge"
    ]

    topics = []
    prereqs = []

    for ln in lines:
        ln_lower = ln.lower()
        if len(ln) < 4 or len(ln) > 120:
            continue
        if any(k in ln_lower for k in ["topic", "chapter", "module", "unit", "week"]):
            if ln not in topics:
                topics.append(ln)

    for ln in lines:
        ln_lower = ln.lower()
        if any(marker in ln_lower for marker in prereq_markers):
            prereqs.append({
                "topic": ln,
                "reason": "Mentioned as required background in the uploaded document.",
                "urgency": "must_know",
                "resources": "Review class notes or introductory material for this topic."
            })

    # If no explicit prerequisites found, infer from common foundational terms.
    if not prereqs:
        inferred = []
        mapping = {
            "algebra": "Algebra fundamentals",
            "calculus": "Basic calculus",
            "probability": "Basic probability",
            "statistics": "Basic statistics",
            "linear algebra": "Linear algebra basics",
            "programming": "Basic programming",
            "python": "Python basics",
            "trigonometry": "Trigonometry basics",
        }
        for key, label in mapping.items():
            if key in lowered:
                inferred.append({
                    "topic": label,
                    "reason": f"The uploaded document references {key}, suggesting prior familiarity is helpful.",
                    "urgency": "good_to_know",
                    "resources": "Quick review from introductory textbook chapters or lecture notes."
                })
        prereqs = inferred

    normalized_topics = [
        {"topic": t[:80], "difficulty": "intermediate", "estimated_hours": 2}
        for t in topics[:10]
    ]

    if not normalized_topics:
        normalized_topics = [
            {"topic": "Core concepts from uploaded document", "difficulty": "intermediate", "estimated_hours": 2}
        ]

    return {
        "document_type": "syllabus" if any(m in lowered for m in topic_markers) else "other",
        "subject": Path(filename).stem or "Uploaded document",
        "topics_covered": normalized_topics,
        "prerequisites": prereqs[:12],
        "suggested_study_order": [t["topic"] for t in normalized_topics[:8]],
        "total_estimated_hours": max(2, len(normalized_topics) * 2),
        "difficulty_level": "intermediate",
        "key_deadlines": [],
        "summary": "Analysis inferred from uploaded document text.",
    }


def _normalize_analysis(raw: dict | list | None, full_text: str, filename: str) -> dict:
    """Normalize different LLM JSON shapes into the required analysis schema."""
    if isinstance(raw, list):
        # Unexpected shape: treat as topic list.
        raw = {"topics_covered": raw}

    if not isinstance(raw, dict):
        return _fallback_analysis_from_text(full_text, filename)

    # Accept wrappers like {"analysis": {...}}.
    if isinstance(raw.get("analysis"), dict):
        raw = raw["analysis"]

    topics = raw.get("topics_covered") or raw.get("topics") or []
    prereqs = raw.get("prerequisites") or raw.get("prerequisite_topics") or []
    order = raw.get("suggested_study_order") or raw.get("study_order") or []
    deadlines = raw.get("key_deadlines") or []

    norm_topics = []
    for t in topics:
        if isinstance(t, dict) and t.get("topic"):
            norm_topics.append({
                "topic": str(t.get("topic"))[:80],
                "difficulty": str(t.get("difficulty", "intermediate")),
                "estimated_hours": int(t.get("estimated_hours", 2) or 2),
            })
        elif isinstance(t, str) and t.strip():
            norm_topics.append({"topic": t.strip()[:80], "difficulty": "intermediate", "estimated_hours": 2})

    norm_prereqs = []
    for p in prereqs:
        if isinstance(p, dict) and p.get("topic"):
            norm_prereqs.append({
                "topic": str(p.get("topic"))[:80],
                "reason": str(p.get("reason", "Required background for topics in this document.")),
                "urgency": str(p.get("urgency", "good_to_know")),
                "resources": str(p.get("resources", "Review foundational notes or introductory material.")),
            })
        elif isinstance(p, str) and p.strip():
            norm_prereqs.append({
                "topic": p.strip()[:80],
                "reason": "Required background for topics in this document.",
                "urgency": "good_to_know",
                "resources": "Review foundational notes or introductory material.",
            })

    normalized = {
        "document_type": str(raw.get("document_type", "other")),
        "subject": str(raw.get("subject") or Path(filename).stem or "Uploaded document"),
        "topics_covered": norm_topics,
        "prerequisites": norm_prereqs,
        "suggested_study_order": [str(x) for x in order if str(x).strip()],
        "total_estimated_hours": int(raw.get("total_estimated_hours", max(2, len(norm_topics) * 2)) or 2),
        "difficulty_level": str(raw.get("difficulty_level", "intermediate")),
        "key_deadlines": deadlines if isinstance(deadlines, list) else [],
        "summary": str(raw.get("summary", "")),
    }

    # Guardrail: never return both empty topics and empty prerequisites.
    if not normalized["topics_covered"] and not normalized["prerequisites"]:
        return _fallback_analysis_from_text(full_text, filename)

    if not normalized["topics_covered"]:
        normalized["topics_covered"] = [
            {"topic": "Core concepts from uploaded document", "difficulty": "intermediate", "estimated_hours": 2}
        ]

    if not normalized["suggested_study_order"]:
        normalized["suggested_study_order"] = [t["topic"] for t in normalized["topics_covered"][:8]]

    if not normalized["summary"]:
        normalized["summary"] = "Analysis generated from the uploaded document."

    return normalized


# ── Prerequisite & topic extraction ──────────────────────────────────────────

def analyse_document(full_text: str, filename: str) -> dict:
    """
    Use Ollama (Llama 3.1) to analyse the full document text and extract
    topics, prerequisites, study order, difficulty, and deadlines.
    """
    from backend.llm_router import llm_json

    if not full_text or not full_text.strip():
        return {
            "document_type": "unknown",
            "subject": filename,
            "topics_covered": [],
            "prerequisites": [],
            "suggested_study_order": [],
            "total_estimated_hours": 0,
            "difficulty_level": "unknown",
            "key_deadlines": [],
            "summary": "No text could be extracted from this document."
        }

    prompt = f"""You are a university professor reviewing a student's study material.

Read this document completely and carefully:

FILENAME: {filename}
CONTENT:
{full_text[:50000]}

After reading, extract a detailed academic analysis. Be specific — use exact terminology, concept names, and chapter references from the document itself.

Return ONLY this JSON structure, no markdown:
{{
  "document_type": "syllabus or notes or assignment or textbook or research_paper",
  "subject": "exact course or subject name as written in the document",
  "summary": "3-4 sentences explaining what this document is about, what a student will learn, and how it is structured",
  "difficulty_level": "beginner or intermediate or advanced",
  "total_estimated_hours": <integer hours to study this fully>,
  "topics_covered": [
    {{
      "topic": "exact concept name as it appears in the document",
      "difficulty": "beginner or intermediate or advanced",
      "estimated_hours": <integer>,
      "description": "one sentence explaining what this topic covers based on the document content"
    }}
  ],
  "prerequisites": [
    {{
      "topic": "specific concept the student must already know",
      "reason": "exactly why this is needed — reference what part of the document requires it",
      "urgency": "must_know or good_to_know or optional",
      "resources": "specific resource to learn this e.g. Khan Academy Calculus course, MIT OpenCourseWare 6.001"
    }}
  ],
  "suggested_study_order": [
    "topic 1 — reason why this comes first",
    "topic 2 — reason why this follows topic 1"
  ],
  "key_deadlines": [
    {{"task": "exact assignment or exam name from document", "date": "date as written or null"}}
  ]
}}

Rules:
- Every topic must be a real concept from the document, not a generic label
- Prerequisites must be things NOT in the document that the student needs beforehand
- Study order must reflect actual dependencies between topics in the document
- If no deadlines are mentioned, return empty array"""

    try:
        raw = llm_json(prompt=prompt, temperature=0.1)
        result = _normalize_analysis(raw, full_text, filename)
        logger.info(
            "Document analysis complete: %s topics, %s prerequisites",
            len(result.get("topics_covered", [])),
            len(result.get("prerequisites", [])),
        )
        return result

    except Exception as e:
        logger.warning(f"Document analysis failed ({e}). Using heuristic fallback.")
        return _fallback_analysis_from_text(full_text, filename)


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

    # Topics
    topics = analysis.get("topics_covered", [])
    if topics:
        lines.append("**Topics covered:**")
        for t in topics:
            lines.append(f"  - {t['topic']} ({t.get('difficulty','')}, ~{t.get('estimated_hours',0)}h)")
        lines.append("")

    # Prerequisites
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

    # Study order
    order = analysis.get("suggested_study_order", [])
    if order:
        lines.append("**Suggested study order:**")
        for i, topic in enumerate(order, 1):
            lines.append(f"  {i}. {topic}")
        lines.append("")

    # Deadlines
    deadlines = analysis.get("key_deadlines", [])
    if deadlines:
        lines.append("**Key deadlines found:**")
        for d in deadlines:
            date = d.get("date") or "date not specified"
            lines.append(f"  - {d['task']} — {date}")

    return "\n".join(lines)


# ── PDF Parser (unchanged from your original) ─────────────────────────────────

class EnhancedPDFParser:
    """Parse PDFs with structure preservation, table extraction, and OCR support."""

    def __init__(self, max_chunk_size: int = 1000, chunk_overlap: int = 150):
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )

    def parse_document(self, file_path: str) -> Dict:
        if not os.path.exists(file_path):
            raise ValueError(f"File not found: {file_path}")

        result = {
            "text_chunks": [],
            "tables": [],
            "images": [],
            "metadata": {},
            "warnings": [],
            "full_text": "",
        }

        try:
            result["metadata"] = self._extract_metadata(file_path)
            full_text_parts = []

            with pdfplumber.open(file_path) as pdf:
                result["metadata"]["num_pages"] = len(pdf.pages)

                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if text:
                        full_text_parts.append(text)
                        chunk = {
                            "content": text,
                            "page": page_num,
                            "section": self._detect_section(text),
                            "type": "text"
                        }
                        result["text_chunks"].append(chunk)

                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            table_text = self._format_table(table)
                            chunk = {
                                "content": table_text,
                                "page": page_num,
                                "section": None,
                                "type": "table"
                            }
                            result["tables"].append(chunk)
                            result["text_chunks"].append(chunk)

                    if page.images:
                        result["images"].append({"page": page_num, "count": len(page.images)})
                        result["metadata"]["has_images"] = 1

            # Store full document text (used for analysis and direct context)
            result["full_text"] = "\n\n".join(full_text_parts)

            total_text = len(result["full_text"])
            if result["metadata"]["num_pages"] > 3 and total_text < 500:
                logger.warning("Low text extraction. Attempting OCR...")
                result["warnings"].append("Document appears to be scanned. Running OCR...")
                ocr_chunks = self._extract_with_ocr(file_path)
                result["text_chunks"].extend(ocr_chunks)
                result["full_text"] += "\n\n" + "\n\n".join(c["content"] for c in ocr_chunks)

            result["metadata"]["has_tables"] = 1 if result["tables"] else 0

            if not result["text_chunks"]:
                raise ValueError("No readable content found in PDF")

            return result

        except Exception as e:
            logger.error(f"Error parsing PDF {file_path}: {e}")
            raise

    def _extract_metadata(self, file_path: str) -> Dict:
        metadata = {
            "filename": Path(file_path).name,
            "file_size": os.path.getsize(file_path),
            "num_pages": 0,
            "has_images": 0,
            "has_tables": 0,
        }
        try:
            reader = PdfReader(file_path)
            metadata["num_pages"] = len(reader.pages)
            if reader.metadata:
                metadata["title"] = reader.metadata.get("/Title", "")
                metadata["author"] = reader.metadata.get("/Author", "")
                metadata["creation_date"] = str(reader.metadata.get("/CreationDate", ""))
        except Exception as e:
            logger.warning(f"Could not extract PDF metadata: {e}")
        return metadata

    def _detect_section(self, text: str) -> Optional[str]:
        lines = text.split("\n")
        for line in lines[:3]:
            line = line.strip()
            if line and len(line) < 100 and line.isupper():
                return line
        return None

    def _format_table(self, table: List[List[str]]) -> str:
        if not table:
            return ""
        lines = []
        for idx, row in enumerate(table):
            lines.append(" | ".join(str(cell or "") for cell in row))
            if idx == 0:
                lines.append(" | ".join(["---"] * len(row)))
        return "\n".join(lines)

    def _extract_with_ocr(self, file_path: str) -> List[Dict]:
        if not TESSERACT_AVAILABLE:
            logger.warning("Tesseract not available. Skipping OCR.")
            return []
        chunks = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page_obj in enumerate(pdf.pages, 1):
                    im = page_obj.to_image(resolution=300)
                    text = pytesseract.image_to_string(im.original)
                    if text.strip():
                        chunks.append({
                            "content": text,
                            "page": page_num,
                            "section": None,
                            "type": "ocr_text"
                        })
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
        return chunks


# ── Main ingest function ──────────────────────────────────────────────────────

def ingest_enhanced(file_path: str, doc_type: str = "unknown", user_id: str = "default") -> Tuple[int, int]:
    """
    Ingest a PDF with enhanced parsing.
    - Stores full text in DB for direct context use
    - Runs AI analysis to extract prerequisites and topics
    - Still builds FAISS index for hybrid retrieval
    Returns: (num_chunks, document_id)
    """
    parser = EnhancedPDFParser()
    result = parser.parse_document(file_path)
    full_text = result.get("full_text", "")

    # Run AI analysis on full document text
    logger.info(f"Running document analysis for {file_path}...")
    analysis = analyse_document(full_text, result["metadata"].get("filename", ""))

    # Infer doc_type from analysis if unknown
    if doc_type == "unknown":
        doc_type = analysis.get("document_type", "unknown")

    # Store document in DB
    session = Session()
    doc = DocModel(
        user_id=user_id,
        filename=result["metadata"].get("filename", ""),
        file_path=file_path,
        file_size=result["metadata"].get("file_size", 0),
        num_pages=result["metadata"].get("num_pages", 0),
        num_chunks=len(result["text_chunks"]),
        doc_type=doc_type,
        has_tables=result["metadata"].get("has_tables", 0),
        has_images=result["metadata"].get("has_images", 0),
        full_text=full_text,
        analysis_json=json.dumps(analysis),
    )
    session.add(doc)
    session.commit()
    doc_id = doc.id

    # Store chunks in DB
    chunks_to_embed = []
    chunk_counter = 0

    for chunk_dict in result["text_chunks"]:
        content = chunk_dict["content"]
        subchunks = parser.splitter.split_text(content) if content else []
        if not subchunks:
            subchunks = [content]

        for subchunk in subchunks:
            chunk_doc = Document(
                page_content=subchunk,
                metadata={
                    "document_id": doc_id,
                    "chunk_index": chunk_counter,
                    "page": chunk_dict.get("page"),
                    "section": chunk_dict.get("section"),
                    "type": chunk_dict.get("type", "text"),
                    "filename": result["metadata"].get("filename"),
                    "source": f"{result['metadata'].get('filename')}#{chunk_dict.get('page', '?')}",
                }
            )
            chunks_to_embed.append(chunk_doc)

            chunk_record = DocumentChunk(
                document_id=doc_id,
                chunk_index=chunk_counter,
                page_number=chunk_dict.get("page"),
                section_title=chunk_dict.get("section"),
                content_preview=subchunk[:200],
                chunk_type=chunk_dict.get("type", "text"),
            )
            session.add(chunk_record)
            chunk_counter += 1

    doc.num_chunks = len(chunks_to_embed)
    session.add(doc)
    session.commit()
    session.close()

    # Build FAISS index
    os.makedirs(os.path.dirname(VECTORSTORE_PATH), exist_ok=True)
    embeddings = get_embeddings()
    try:
        if os.path.exists(VECTORSTORE_PATH):
            existing = FAISS.load_local(
                VECTORSTORE_PATH, embeddings,
                allow_dangerous_deserialization=True,
            )
            incoming = FAISS.from_documents(chunks_to_embed, embeddings)
            existing.merge_from(incoming)
            store = existing
        else:
            store = FAISS.from_documents(chunks_to_embed, embeddings)
        store.save_local(VECTORSTORE_PATH)
    except Exception as e:
        logger.warning(f"Vectorstore rebuild needed: {e}")
        store = FAISS.from_documents(chunks_to_embed, embeddings)
        store.save_local(VECTORSTORE_PATH)

    logger.info(f"Ingested {len(chunks_to_embed)} chunks from document {doc_id}")
    return len(chunks_to_embed), doc_id


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


def get_full_texts_for_documents(user_id: str, document_ids: list[int] | None = None) -> str:
    """Return concatenated text for selected user documents."""
    session = Session()
    query = session.query(DocModel).filter_by(user_id=user_id)
    if document_ids:
        query = query.filter(DocModel.id.in_(document_ids))
    docs = query.all()
    session.close()
    parts = [d.full_text for d in docs if d.full_text]
    return "\n\n---\n\n".join(parts)


def get_full_text_for_query(query: str) -> str:
    """
    Return full document texts — used instead of RAG chunking
    when the query needs full-document understanding.
    """
    return get_all_full_texts()


def list_documents(user_id: str = "default") -> List[Dict]:
    session = Session()
    docs = session.query(DocModel).filter_by(user_id=user_id).all()
    session.close()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "file_size": d.file_size,
            "num_pages": d.num_pages,
            "num_chunks": d.num_chunks,
            "doc_type": d.doc_type,
            "has_tables": bool(d.has_tables),
            "has_images": bool(d.has_images),
            "created_at": d.created_at.isoformat(),
        }
        for d in docs
    ]


def delete_document(doc_id: int, user_id: str = "default") -> bool:
    session = Session()
    doc = session.query(DocModel).filter(DocModel.id == doc_id, DocModel.user_id == user_id).first()
    if not doc:
        session.close()
        return False
    session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).delete()
    session.delete(doc)
    session.commit()
    session.close()
    _rebuild_vectorstore()
    return True


def _rebuild_vectorstore():
    session = Session()
    docs = session.query(DocModel).all()
    chunks_to_embed = []
    parser = EnhancedPDFParser()

    for doc in docs:
        if not doc.file_path or not os.path.exists(doc.file_path):
            logger.warning(f"Skipping missing file for document {doc.id}: {doc.file_path}")
            continue
        try:
            parsed = parser.parse_document(doc.file_path)
            for chunk_dict in parsed.get("text_chunks", []):
                content = chunk_dict.get("content", "")
                for subchunk in parser.splitter.split_text(content) if content else []:
                    chunks_to_embed.append(
                        Document(
                            page_content=subchunk,
                            metadata={
                                "document_id": doc.id,
                                "page": chunk_dict.get("page"),
                                "section": chunk_dict.get("section"),
                                "type": chunk_dict.get("type", "text"),
                                "filename": doc.filename,
                                "source": f"{doc.filename}#{chunk_dict.get('page', '?')}",
                            },
                        )
                    )
        except Exception as e:
            logger.warning(f"Failed to rebuild embeddings for document {doc.id}: {e}")

    if not chunks_to_embed:
        import shutil
        if os.path.exists(VECTORSTORE_PATH):
            shutil.rmtree(VECTORSTORE_PATH)
        session.close()
        return

    embeddings = get_embeddings()
    store = FAISS.from_documents(chunks_to_embed, embeddings)
    store.save_local(VECTORSTORE_PATH)
    session.close()