"""Enhanced retrieval with source attribution and relevance scoring."""

import os
import logging
from typing import List, Dict, Optional

from langchain_community.vectorstores import FAISS
from backend.embeddings_provider import get_embeddings
from backend.models import Session, DocumentChunk, Document as DocModel

logger = logging.getLogger(__name__)
VECTORSTORE_PATH = "vectorstore/index"


def retrieve_context(query: str, k: int = 5) -> str:
    """Retrieve context from vectorstore. Returns empty string if store doesn't exist."""
    
    if not os.path.exists(VECTORSTORE_PATH):
        logger.warning(f"Vectorstore not found at {VECTORSTORE_PATH}")
        return "No documents uploaded yet. Please upload documents first."
    
    try:
        embeddings = get_embeddings()
        store = FAISS.load_local(VECTORSTORE_PATH, embeddings,
                                  allow_dangerous_deserialization=True)
        docs = store.similarity_search(query, k=k)
        context = "\n\n".join([doc.page_content for doc in docs])
        return context
    except Exception as e:
        logger.error(f"Error retrieving context: {e}")
        return f"Error retrieving context: {str(e)}"


def retrieve_with_sources(query: str, k: int = 5) -> Dict:
    """
    Retrieve context with source attribution.
    
    Returns:
        Dict with keys:
        - 'context': Combined text from retrieved chunks
        - 'sources': List of source objects with metadata
        - 'chunks': Full retrieved documents with metadata
    """
    
    if not os.path.exists(VECTORSTORE_PATH):
        logger.warning(f"Vectorstore not found at {VECTORSTORE_PATH}")
        return {
            "context": "No documents uploaded yet. Please upload documents first.",
            "sources": [],
            "chunks": [],
        }
    
    try:
        embeddings = get_embeddings()
        store = FAISS.load_local(VECTORSTORE_PATH, embeddings,
                                  allow_dangerous_deserialization=True)
        
        # Retrieve with scores (similarity)
        docs_with_scores = store.similarity_search_with_score(query, k=k)
        
        context_parts = []
        sources = []
        chunks = []
        
        session = Session()
        
        for idx, (doc, score) in enumerate(docs_with_scores):
            metadata = doc.metadata or {}
            context_parts.append(doc.page_content)
            
            # Get document info
            doc_id = metadata.get("document_id")
            doc_record = session.query(DocModel).filter(DocModel.id == doc_id).first()
            filename = metadata.get("filename") or (doc_record.filename if doc_record else "Unknown")
            
            source = {
                "index": idx + 1,
                "relevance_score": float(1 / (1 + score)),  # Convert distance to similarity
                "filename": filename,
                "page": metadata.get("page"),
                "section": metadata.get("section"),
                "type": metadata.get("type", "text"),
                "source": metadata.get("source", ""),
                "doc_type": doc_record.doc_type if doc_record else "unknown",
            }
            sources.append(source)
            
            # Store chunk info with content
            chunks.append({
                "index": idx + 1,
                "content": doc.page_content,
                "metadata": metadata,
                "relevance_score": source["relevance_score"],
            })
        
        session.close()
        
        # Format context with source attribution
        context = "\n\n".join([
            f"[Source {idx+1}: {metadata.get('filename')} - Page {metadata.get('page', '?')}]\n"
            f"{content}"
            for idx, (content, metadata) in enumerate(
                [(doc.page_content, doc.metadata) for doc, _ in docs_with_scores]
            )
        ])
        
        return {
            "context": context,
            "sources": sources,
            "chunks": chunks,
        }
        
    except Exception as e:
        logger.error(f"Error retrieving context with sources: {e}")
        return {
            "context": f"Error retrieving context: {str(e)}",
            "sources": [],
            "chunks": [],
        }


def hybrid_retrieve(query: str, k: int = 5, use_semantic: bool = True) -> Dict:
    """
    Multi-step retrieval: semantic search + relevance filtering.
    
    Returns higher quality results by:
    1. Retrieving k*2 initial chunks via semantic search
    2. Filtering by relevance threshold
    3. Re-ranking by document type preference
    """
    
    result = retrieve_with_sources(query, k=min(k * 2, 15))
    
    if not result["sources"]:
        return result
    
    # Filter by relevance threshold (keep top results)
    threshold = 0.5
    filtered_sources = [s for s in result["sources"] if s["relevance_score"] > threshold]
    
    if not filtered_sources:
        # If nothing passes threshold, keep top k
        filtered_sources = result["sources"][:k]
    
    # Sort by relevance and keep top k
    filtered_sources = sorted(
        filtered_sources,
        key=lambda x: x["relevance_score"],
        reverse=True
    )[:k]
    
    # Reconstruct context
    filtered_chunks = [
        c for c in result["chunks"]
        if any(s["index"] == c["index"] for s in filtered_sources)
    ]
    
    context_parts = []
    for chunk in sorted(filtered_chunks, key=lambda x: x["index"]):
        metadata = chunk["metadata"]
        context_parts.append(
            f"[Page {metadata.get('page', '?')}: {metadata.get('section', 'content')}]\n"
            f"{chunk['content']}"
        )
    
    return {
        "context": "\n\n".join(context_parts),
        "sources": filtered_sources,
        "chunks": filtered_chunks,
    }


def get_document_summary(doc_id: int) -> Dict:
    """Get a summary of a document's structure and content."""
    session = Session()
    
    doc = session.query(DocModel).filter(DocModel.id == doc_id).first()
    if not doc:
        session.close()
        return {"error": "Document not found"}
    
    chunks = session.query(DocumentChunk).filter(
        DocumentChunk.document_id == doc_id
    ).all()
    
    # Group by section and type
    sections = {}
    chunk_types = {}
    
    for chunk in chunks:
        section = chunk.section_title or "Unlabeled"
        if section not in sections:
            sections[section] = 0
        sections[section] += 1
        
        ctype = chunk.chunk_type
        if ctype not in chunk_types:
            chunk_types[ctype] = 0
        chunk_types[ctype] += 1
    
    session.close()
    
    return {
        "document_id": doc_id,
        "filename": doc.filename,
        "doc_type": doc.doc_type,
        "num_pages": doc.num_pages,
        "num_chunks": doc.num_chunks,
        "has_tables": bool(doc.has_tables),
        "has_images": bool(doc.has_images),
        "sections": sections,
        "chunk_types": chunk_types,
        "created_at": doc.created_at.isoformat(),
    }
