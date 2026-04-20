import hashlib
import math
import os
import re
from typing import List

from langchain_core.embeddings import Embeddings


class LocalHashEmbeddings(Embeddings):
    """Lightweight deterministic local embeddings fallback.

    This avoids external embedding API failures and keeps FAISS usable.
    """

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())

    def _vectorize(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for tok in self._tokenize(text):
            h = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if (h[4] & 1) == 0 else -1.0
            vec[idx] += sign

        # L2 normalize for cosine-like behavior in FAISS
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._vectorize(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._vectorize(text)


def _gemini_embeddings_client(model_name: str):
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    from backend.gemini_config import get_gemini_api_key

    return GoogleGenerativeAIEmbeddings(
        model=model_name,
        google_api_key=get_gemini_api_key(),
    )


def get_embeddings():
    provider = (os.getenv("EMBEDDINGS_PROVIDER") or "auto").strip().lower()
    model_name = (os.getenv("GEMINI_EMBEDDING_MODEL") or "models/text-embedding-004").strip()

    if provider == "local":
        return LocalHashEmbeddings()

    if provider == "gemini":
        emb = _gemini_embeddings_client(model_name)
        # Fail fast with a tiny probe to surface configuration errors immediately.
        emb.embed_query("health-check")
        return emb

    # auto mode: try Gemini first, then fall back to local.
    try:
        emb = _gemini_embeddings_client(model_name)
        emb.embed_query("health-check")
        return emb
    except Exception as e:
        print(f"⚠️ Gemini embeddings unavailable ({e}). Falling back to local embeddings.")
        return LocalHashEmbeddings()
