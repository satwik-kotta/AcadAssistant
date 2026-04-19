"""
Legacy ingest module — delegates to enhanced_ingest for backward compatibility.
"""

import logging
from backend.enhanced_ingest import ingest_enhanced

logger = logging.getLogger(__name__)


def ingest_document(file_path: str) -> int:
	"""
	Ingest a PDF into FAISS and return the number of created chunks.
	
	This function maintains backward compatibility by delegating to enhanced_ingest.
	For new code, use ingest_enhanced() directly which returns (num_chunks, doc_id).
	"""
	try:
		num_chunks, doc_id = ingest_enhanced(file_path, doc_type="unknown")
		logger.info(f"Ingested document {doc_id} with {num_chunks} chunks")
		return num_chunks
	except Exception as e:
		logger.error(f"Error ingesting document: {e}")
		raise

