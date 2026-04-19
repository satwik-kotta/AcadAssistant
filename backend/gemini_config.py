import os
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT_DIR / ".env", override=True)

DEFAULT_MODEL = (os.getenv("GEMINI_MODEL") or "models/gemini-2.0-flash").strip()

# Ordered preference list; code will fall back to list_models() if needed.
MODEL_CANDIDATES = [
    DEFAULT_MODEL,
    "models/gemini-2.0-flash",
    "models/gemini-1.5-flash",
    "gemini-1.5-flash",
    "models/gemini-1.5-pro",
]

def get_gemini_api_key() -> str:
    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not key or key in {"your-gemini-key", "..."}:
        raise ValueError("Gemini API key is missing. Set GEMINI_API_KEY in .env and retry.")
    return key

def _supports_generate_content(model_obj) -> bool:
    methods = getattr(model_obj, "supported_generation_methods", []) or []
    return any(m == "generateContent" for m in methods)


def _resolve_working_model_name(preferred_name: str | None = None) -> str:
    candidates = []
    if preferred_name:
        candidates.append(preferred_name)
    for name in MODEL_CANDIDATES:
        if name and name not in candidates:
            candidates.append(name)

    # First try explicit candidates quickly.
    for name in candidates:
        try:
            model_obj = genai.get_model(name)
            if _supports_generate_content(model_obj):
                return name
        except Exception:
            continue

    # Then discover from available models for this key/version.
    try:
        for model_obj in genai.list_models():
            name = getattr(model_obj, "name", "")
            if name and _supports_generate_content(model_obj):
                return name
    except Exception:
        pass

    raise ValueError(
        "No Gemini model with generateContent support is available for this API key/version. "
        "Set GEMINI_MODEL in .env to a supported model from your account."
    )


def get_gemini_model(
    model_name: str | None = None,
    system_instruction: str | None = None,
    tools=None,
):
    genai.configure(api_key=get_gemini_api_key())
    resolved_name = _resolve_working_model_name(model_name)
    kwargs = {}
    if system_instruction is not None:
        kwargs["system_instruction"] = system_instruction
    if tools is not None:
        kwargs["tools"] = tools
    return genai.GenerativeModel(resolved_name, **kwargs)