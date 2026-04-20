"""
Unified LLM interface.
Uses Ollama exclusively with a primary and fallback open-source model.
"""

import json
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT_DIR / ".env", override=True)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b").strip()
OLLAMA_FALLBACK_MODEL = os.getenv("OLLAMA_FALLBACK_MODEL", "gemma4:e4b").strip()
OLLAMA_THINK = os.getenv("OLLAMA_THINK", "false").strip().lower() == "true"
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))


def _ollama_models() -> list[str]:
    models = []
    for name in [OLLAMA_MODEL, OLLAMA_FALLBACK_MODEL]:
        if name and name not in models:
            models.append(name)
    return models

def _build_messages(prompt: str, system: str = "") -> list[dict]:
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _call_ollama_messages(
    messages: list[dict],
    temperature: float = 0.3,
    response_format: str | dict | None = None,
) -> str:
    """Call Ollama with the configured primary and fallback models."""
    last_error: Exception | None = None

    for model_name in _ollama_models():
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "think": OLLAMA_THINK,
            "options": {"temperature": temperature},
        }
        if response_format is not None:
            payload["format"] = response_format

        try:
            logger.info(f"[LLM-Ollama] Calling {model_name} at {OLLAMA_BASE_URL}")
            response = httpx.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
                timeout=OLLAMA_TIMEOUT,
            )
            response.raise_for_status()
            result = (response.json().get("message", {}) or {}).get("content", "").strip()
            if result:
                logger.info(f"[LLM-Ollama] ✅ Success using {model_name} ({len(result)} chars)")
                return result
            last_error = RuntimeError(f"Ollama model {model_name} returned empty content")
            logger.warning(f"[LLM-Ollama] Empty response from {model_name}")
        except httpx.TimeoutException as e:
            last_error = TimeoutError(
                f"Ollama timed out after {OLLAMA_TIMEOUT} seconds while calling {model_name}."
            )
            logger.error(f"[LLM-Ollama] ❌ TIMEOUT for {model_name}: {e}")
        except Exception as e:
            last_error = e
            logger.error(f"[LLM-Ollama] ❌ ERROR for {model_name}: {e}")

    raise RuntimeError(
        f"All configured Ollama models failed at {OLLAMA_BASE_URL}. "
        f"Primary: {OLLAMA_MODEL}. Fallback: {OLLAMA_FALLBACK_MODEL}. "
        f"Last error: {last_error}"
    )


def llm_call(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    """
    Unified LLM call using Ollama only.
    """
    return _call_ollama_messages(_build_messages(prompt, system), temperature)


def llm_json(prompt: str, system: str = "", temperature: float = 0.1) -> dict | list:
    """
    Call LLM and parse JSON response.
    Handles markdown fences automatically.
    """
    system_with_json = (system + "\n\nReturn ONLY valid JSON. No markdown, no explanation.").strip()
    raw = _call_ollama_messages(
        _build_messages(prompt, system_with_json),
        temperature,
        response_format="json",
    )

    # Strip markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


class ChatSession:
    """Multi-turn conversation session using Ollama only."""
    
    def __init__(self, system_instruction: str = ""):
        self.system_instruction = system_instruction
        self.history = []
        self.provider = "ollama"
    
    def send_message(self, user_message: str) -> str:
        """Send a user message and get a response."""
        self.history.append({"role": "user", "content": user_message})

        response = self._send_ollama(user_message)

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

        return _call_ollama_messages(messages, temperature=0.3)