"""
Unified LLM interface.
Tries Ollama (local, open-source) first. Falls back to Gemini if unavailable.
"""

import os
import json
import logging
import httpx
from backend.gemini_config import get_gemini_model

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
USE_OLLAMA = os.getenv("USE_OLLAMA", "true").strip().lower() == "true"


def _call_ollama(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    """Call Ollama local model."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = httpx.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["message"]["content"].strip()


def _call_gemini(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    """Call Gemini as fallback."""
    model = get_gemini_model()
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    response = model.generate_content(
        full_prompt,
        generation_config={"temperature": temperature}
    )
    return (response.text or "").strip()


def llm_call(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    """
    Unified LLM call. Ollama first, Gemini fallback.
    Raises exception only if both fail.
    """
    if USE_OLLAMA:
        try:
            result = _call_ollama(prompt, system, temperature)
            logger.debug(f"[LLM] Ollama responded ({len(result)} chars)")
            return result
        except Exception as e:
            logger.warning(f"[LLM] Ollama failed ({e}), falling back to Gemini")

    try:
        result = _call_gemini(prompt, system, temperature)
        logger.debug(f"[LLM] Gemini responded ({len(result)} chars)")
        return result
    except Exception as e:
        logger.error(f"[LLM] Both Ollama and Gemini failed: {e}")
        raise


def llm_json(prompt: str, system: str = "", temperature: float = 0.1) -> dict | list:
    """
    Call LLM and parse JSON response.
    Handles markdown fences automatically.
    """
    system_with_json = (system + "\n\nReturn ONLY valid JSON. No markdown, no explanation.").strip()
    raw = llm_call(prompt, system_with_json, temperature)

    # Strip markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


class ChatSession:
    """Multi-turn conversation session using Ollama or Gemini."""
    
    def __init__(self, system_instruction: str = ""):
        self.system_instruction = system_instruction
        self.history = []
        self.provider = None  # "ollama" or "gemini"
        self._init_provider()
    
    def _init_provider(self):
        """Determine which provider to use."""
        if USE_OLLAMA:
            self.provider = "ollama"
        else:
            self.provider = "gemini"
    
    def send_message(self, user_message: str) -> str:
        """Send a user message and get a response."""
        self.history.append({"role": "user", "content": user_message})
        
        if self.provider == "ollama":
            response = self._send_ollama(user_message)
        else:
            response = self._send_gemini(user_message)
        
        self.history.append({"role": "assistant", "content": response})
        return response
    
    def _send_ollama(self, user_message: str) -> str:
        """Send message to Ollama."""
        messages = []
        if self.system_instruction:
            messages.append({"role": "system", "content": self.system_instruction})
        
        # Add conversation history (without current user message, it's already in history)
        for msg in self.history[:-1]:  # Exclude the user message we just added
            messages.append(msg)
        messages.append({"role": "user", "content": user_message})
        
        try:
            response = httpx.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.3},
                },
                timeout=120,
            )
            response.raise_for_status()
            return response.json()["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"[Chat] Ollama failed ({e}), switching to Gemini fallback")
            self.provider = "gemini"
            return self._send_gemini(user_message)
    
    def _send_gemini(self, user_message: str) -> str:
        """Send message to Gemini."""
        try:
            import google.generativeai as genai
            model = genai.GenerativeModel(
                "models/gemini-2.0-flash",
                system_instruction=self.system_instruction
            )
            
            # Convert history to Gemini format
            genai_history = []
            for msg in self.history[:-1]:  # Exclude current user message
                role = "user" if msg["role"] == "user" else "model"
                genai_history.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}]
                })
            
            chat_session = model.start_chat(history=genai_history)
            response = chat_session.send_message(user_message)
            return (response.text or "").strip()
        except Exception as e:
            logger.error(f"[Chat] Gemini also failed ({e})")
            raise