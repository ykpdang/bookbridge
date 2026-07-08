"""Provider selection helpers for optional LLM features."""

import os
from typing import Any

from src.api.ollama_client import OllamaClient
from src.api.openai_compatible_client import OpenAICompatibleClient


def llm_provider() -> str:
    provider = (os.environ.get("LLM_PROVIDER") or "ollama").strip().lower()
    if provider in {"openai-compatible", "openai_compat", "llama", "llama-server", "llama_swap", "llama-swap"}:
        return "openai_compatible"
    if provider == "openai":
        return "openai"
    return "ollama"


def create_llm_client() -> Any:
    provider = llm_provider()
    if provider in {"openai", "openai_compatible"}:
        return OpenAICompatibleClient(provider=provider)
    return OllamaClient()
