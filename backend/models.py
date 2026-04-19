from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

Base = declarative_base()

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    user_id = Column(String, default="default")
    filename = Column(String)
    file_path = Column(String)
    file_size = Column(Integer)
    num_pages = Column(Integer, nullable=True)
    num_chunks = Column(Integer)
    doc_type = Column(String, default="unknown")
    has_tables = Column(Integer, default=0)
    has_images = Column(Integer, default=0)
    full_text = Column(Text, nullable=True)        # entire document text
    analysis_json = Column(Text, nullable=True)    # prerequisites + topics JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer)
    chunk_index = Column(Integer)
    page_number = Column(Integer, nullable=True)
    section_title = Column(String, nullable=True)
    content_preview = Column(String)
    chunk_type = Column(String, default="text")
    relevance_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class StudyPlan(Base):
    __tablename__ = "study_plans"
    id = Column(Integer, primary_key=True)
    user_id = Column(String, default="default")
    plan_json = Column(Text)
    constraints_json = Column(Text, nullable=True)  # stores user constraints
    score = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer)
    day = Column(String)
    topic = Column(String)
    duration_minutes = Column(Integer)
    calendar_event_id = Column(String, nullable=True)
    status = Column(String, default="pending")


DEFAULT_DB_PATH = (Path(__file__).resolve().parents[1] / "db" / "assistant.db")
DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(os.getenv("DB_URL", f"sqlite:///{DEFAULT_DB_PATH}"))
Base.metadata.create_all(engine)


def _sqlite_column_names(conn, table_name: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {row[1] for row in rows}


def _migrate_sqlite_schema():
    """Best-effort SQLite migrations for newly added columns."""
    if engine.url.get_backend_name() != "sqlite":
        return

    with engine.begin() as conn:
        # documents table migrations
        doc_cols = _sqlite_column_names(conn, "documents")
        if "user_id" not in doc_cols:
            conn.execute(text("ALTER TABLE documents ADD COLUMN user_id TEXT DEFAULT 'default'"))
        if "full_text" not in doc_cols:
            conn.execute(text("ALTER TABLE documents ADD COLUMN full_text TEXT"))
        if "analysis_json" not in doc_cols:
            conn.execute(text("ALTER TABLE documents ADD COLUMN analysis_json TEXT"))

        # study_plans table migrations
        plan_cols = _sqlite_column_names(conn, "study_plans")
        if "user_id" not in plan_cols:
            conn.execute(text("ALTER TABLE study_plans ADD COLUMN user_id TEXT DEFAULT 'default'"))
        if "constraints_json" not in plan_cols:
            conn.execute(text("ALTER TABLE study_plans ADD COLUMN constraints_json TEXT"))


_migrate_sqlite_schema()
Session = sessionmaker(bind=engine)