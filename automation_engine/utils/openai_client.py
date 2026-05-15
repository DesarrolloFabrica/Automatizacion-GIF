"""
Centralized OpenAI-compatible client factory.

Defaults to Google AI Studio (Gemini) OpenAI-compatible endpoint
when OPENAI_BASE_URL is not set.

Variables:
  OPENAI_API_KEY       - API key (required)
  OPENAI_BASE_URL      - Optional custom endpoint
  OPENAI_MODEL_GRANULES
  OPENAI_MODEL_TXT
  OPENAI_MODEL_DOCX
  OPENAI_MODEL_MATERIALS
  OPENAI_MODEL_REPAIR

Default Gemini URL:
  https://generativelanguage.googleapis.com/v1beta/openai/

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


def get_openai_client() -> OpenAI:
    """
    Create and return an OpenAI-compatible client.

    Uses OPENAI_BASE_URL if set, otherwise defaults to Gemini endpoint.
    Uses OPENAI_API_KEY (required).
    """
    if OpenAI is None:
        raise RuntimeError(
            "Falta instalar el paquete openai. Ejecuta: pip install -r requirements.txt"
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno.")

    base_url = os.getenv("OPENAI_BASE_URL", GEMINI_BASE_URL)

    client = OpenAI(api_key=api_key, base_url=base_url)

    print(f"[LLM] Gemini/OpenAI-compatible client initialized (base_url={base_url})")
    return client


def get_openai_model(task_type: Optional[str] = None) -> str:
    """
    Resolve model name for a task type.

    Priority:
    1. OPENAI_MODEL_<TASK_TYPE> env var
    2. OPENAI_MODEL env var
    3. Default model for task type
    4. "gpt-4o" fallback
    """
    if task_type and task_type in _MODEL_ENV_MAP:
        env_var = _MODEL_ENV_MAP[task_type]
        model = os.getenv(env_var)
        if model:
            return model

    model = os.getenv("OPENAI_MODEL")
    if model:
        return model

    if task_type and task_type in _DEFAULT_MODELS:
        return _DEFAULT_MODELS[task_type]

    return "gpt-4o"
