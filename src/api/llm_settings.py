"""Shared environment helpers for LLM provider settings."""

import os


def llm_setting_value(legacy_key: str, default: str = "") -> str:
    """Read a generic LLM_* setting before its legacy OLLAMA_* equivalent."""
    if legacy_key.startswith("OLLAMA_"):
        generic_key = "LLM_" + legacy_key[len("OLLAMA_"):]
        generic = os.environ.get(generic_key)
        if generic is not None and generic.strip() != "":
            return generic
    return os.environ.get(legacy_key, default)


def llm_setting_truthy(legacy_key: str, default: str = "false") -> bool:
    return str(llm_setting_value(legacy_key, default)).strip().lower() in {"true", "1", "yes", "on"}
