"""
Centralized OpenAI-compatible client factory.

Defaults to Google AI Studio (Gemini) OpenAI-compatible endpoint
when OPENAI_BASE_URL is not set. Set LLM_PROVIDER=ollama to use a
local or tunneled Ollama server.

Variables:
  LLM_PROVIDER          - Optional provider selector: gemini, openai, ollama
  OPENAI_API_KEY       - API key (required)
  OPENAI_BASE_URL      - Optional custom endpoint
  OLLAMA_BASE_URL      - Optional Ollama endpoint (default http://localhost:11434/v1)
  OLLAMA_MODEL         - Optional Ollama model (default qwen2.5:3b)
  OPENAI_MODEL_GRANULES
  OPENAI_MODEL_TXT
  OPENAI_MODEL_DOCX
  OPENAI_MODEL_MATERIALS
  OPENAI_MODEL_REPAIR

Default Gemini URL:
  https://generativelanguage.googleapis.com/v1beta/openai/

Default Ollama URL:
  http://localhost:11434/v1

Default models:
  granules: gemini-2.5-pro
  txt:      gemini-2.5-flash
  docx:     gemini-2.5-pro
  materials: gemini-2.5-flash
  repair:   gemini-2.5-flash-lite
"""

from __future__ import annotations

import os
import logging
from typing import Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_DEFAULT_MODEL = "qwen2.5:3b"

_DEFAULT_MODELS = {
    "granules": "gemini-2.5-pro",
    "txt": "gemini-2.5-flash",
    "docx": "gemini-2.5-pro",
    "materials": "gemini-2.5-flash",
    "repair": "gemini-2.5-flash-lite",
}

_MODEL_ENV_MAP = {
    "granules": "OPENAI_MODEL_GRANULES",
    "txt": "OPENAI_MODEL_TXT",
    "docx": "OPENAI_MODEL_DOCX",
    "materials": "OPENAI_MODEL_MATERIALS",
    "repair": "OPENAI_MODEL_REPAIR",
}


def _provider() -> str:
    return os.getenv("LLM_PROVIDER", "").strip().lower()


def is_ollama_enabled() -> bool:
    """Return True when the app should use Ollama as the LLM backend."""
    provider = _provider()
    if provider == "ollama":
        return True
    base_url = os.getenv("OPENAI_BASE_URL", "").strip().lower()
    return "ollama" in base_url or "localhost:11434" in base_url or "127.0.0.1:11434" in base_url


def get_llm_base_url() -> str:
    """Resolve the OpenAI-compatible base URL for the selected provider."""
    explicit_base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    if explicit_base_url:
        return explicit_base_url
    if is_ollama_enabled():
        return os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL).strip() or OLLAMA_BASE_URL
    return GEMINI_BASE_URL


def get_llm_api_key() -> str:
    """Resolve API key. Ollama accepts any non-empty value."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if api_key:
        return api_key
    if is_ollama_enabled():
        return "ollama"
    raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno.")


def get_openai_client() -> OpenAI:
    """
    Create and return an OpenAI-compatible client.

    Uses OPENAI_BASE_URL if set, otherwise defaults to the selected provider.
    Uses OPENAI_API_KEY, except Ollama where a placeholder key is enough.
    """
    if OpenAI is None:
        raise RuntimeError(
            "Falta instalar el paquete openai. Ejecuta: pip install -r requirements.txt"
        )

    api_key = get_llm_api_key()
    base_url = get_llm_base_url()

    client = OpenAI(api_key=api_key, base_url=base_url)

    provider = "ollama" if is_ollama_enabled() else (_provider() or "gemini")
    print(f"[LLM] OpenAI-compatible client initialized (provider={provider}, base_url={base_url})")
    return client


def get_openai_model(task_type: Optional[str] = None) -> str:
    """
    Resolve model name for a task type.

    Priority:
    1. OPENAI_MODEL_<TASK_TYPE> env var
    2. OPENAI_MODEL env var
    3. OLLAMA_MODEL / qwen2.5:3b when LLM_PROVIDER=ollama
    4. Default model for task type
    5. "gpt-4o" fallback
    """
    if task_type and task_type in _MODEL_ENV_MAP:
        env_var = _MODEL_ENV_MAP[task_type]
        model = os.getenv(env_var)
        if model:
            return model

    model = os.getenv("OPENAI_MODEL")
    if model:
        return model

    if is_ollama_enabled():
        return os.getenv("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)

    if task_type and task_type in _DEFAULT_MODELS:
        return _DEFAULT_MODELS[task_type]

    return "gpt-4o"
