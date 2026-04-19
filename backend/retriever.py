"""
Retrieval module with optional source attribution.
"""

import os
import logging

from langchain_community.vectorstores import FAISS
from backend.embeddings_provider import get_embeddings

try:
    from backend.enhanced_retriever import retrieve_with_sources, hybrid_retrieve
    ENHANCED_RETRIEVER_AVAILABLE = True
except ImportError:
    ENHANCED_RETRIEVER_AVAILABLE = False

logger = logging.getLogger(__name__)
VECTORSTORE_PATH = "vectorstore/index"


def retrieve_context(query: str, k: int = 5) -> str:
    """Retrieve context from vectorstore. Returns empty string if store doesn't exist."""
    
    # Check if vectorstore exists
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


def retrieve_context_with_sources(query: str, k: int = 5) -> dict:
    """
    Retrieve context with source attribution.
    Falls back to basic retrieval if enhanced retriever unavailable.
    
    Returns:
        Dict with 'context' and 'sources' keys
    """
    if not ENHANCED_RETRIEVER_AVAILABLE:
        # Fallback to basic retrieval
        context = retrieve_context(query, k=k)
        return {
            "context": context,
            "sources": [],
        }
    
    return retrieve_with_sources(query, k=k)


def retrieve_context_hybrid(query: str, k: int = 5) -> dict:
    """
    Multi-step hybrid retrieval with filtering and re-ranking.
    Falls back to basic retrieval if enhanced retriever unavailable.
    
    Returns:
        Dict with 'context', 'sources', and 'chunks' keys
    """
    if not ENHANCED_RETRIEVER_AVAILABLE:
        # Fallback to basic retrieval
        context = retrieve_context(query, k=k)
        return {
            "context": context,
            "sources": [],
            "chunks": [],
        }
    
    return hybrid_retrieve(query, k=k)
