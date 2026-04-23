"""Utilities for Gemini client initialization and dynamic model selection."""

from typing import List, Optional

from google import genai

from backend.config import GEMINI_API_KEY


PREFERRED_MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-1.5-flash",
    "models/gemini-1.5-pro",
    "models/gemini-1.0-pro",
]


def get_gemini_client(api_key: Optional[str] = None) -> Optional[genai.Client]:
    """Create a Gemini client if an API key is available."""
    key = (api_key or GEMINI_API_KEY or "").strip()
    if not key:
        return None
    return genai.Client(api_key=key)


def list_available_gemini_models(client: genai.Client) -> List[str]:
    """List available Gemini model names via client.models.list()."""
    names: List[str] = []
    for model in client.models.list():
        name = getattr(model, "name", None)
        if not name:
            continue
        names.append(str(name))
    return names


def select_gemini_model(
    client: genai.Client,
    preferred_models: Optional[List[str]] = None,
) -> Optional[str]:
    """Pick a valid model dynamically, preferring known stable models."""
    available = list_available_gemini_models(client)
    if not available:
        return None

    preferred = preferred_models or PREFERRED_MODELS
    available_set = set(available)
    for model_name in preferred:
        if model_name in available_set:
            return model_name

    # Fallback to first Gemini text model if preferred models are unavailable.
    for model_name in available:
        if model_name.startswith("models/gemini"):
            return model_name

    return None