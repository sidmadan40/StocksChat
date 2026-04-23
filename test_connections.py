"""Connection checks for Gemini and Alpaca APIs."""

import re

import alpaca_trade_api as tradeapi
from google import genai

from backend.config import (
    APCA_API_BASE_URL,
    APCA_API_KEY_ID,
    APCA_API_SECRET_KEY,
    GEMINI_API_KEY,
)
from backend.gemini_client import get_gemini_client, list_available_gemini_models, select_gemini_model


def _redact(text: str) -> str:
    """Redact likely secret patterns from output text."""
    cleaned = text or ""
    for value in (GEMINI_API_KEY, APCA_API_KEY_ID, APCA_API_SECRET_KEY):
        if value:
            cleaned = cleaned.replace(value, "***REDACTED***")

    cleaned = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "***REDACTED***", cleaned)
    return cleaned


def _normalize_alpaca_base_url(base_url: str) -> str:
    """Normalize Alpaca base URL to avoid /v2/v2 path issues."""
    url = (base_url or "").strip().rstrip("/")
    if url.endswith("/v2"):
        return url[:-3]
    return url


def test_gemini() -> bool:
    """Send a simple prompt to Gemini and print the response text."""
    try:
        client = get_gemini_client()
        if client is None:
            print("[Gemini] FAILED: GEMINI_API_KEY is missing.")
            return False

        model_names = list_available_gemini_models(client)
        print("[Gemini] Available models:")
        for model_name in model_names:
            print(f"  - {model_name}")

        selected_model = select_gemini_model(client)
        if not selected_model:
            print("[Gemini] FAILED: No valid Gemini models available.")
            return False

        response = client.models.generate_content(
            model=selected_model,
            contents="Say OK"
        )
        text = (response.text or "").strip() or "(empty response)"
        print(f"[Gemini] Using model: {selected_model}")
        print(f"[Gemini] SUCCESS: {text}")
        return True
    except Exception as e:
        print(f"[Gemini] FAILED: {_redact(str(e))[:240]}")
        return False


def test_alpaca_api() -> bool:
    """Fetch Alpaca account details and print cash/account status."""
    if not APCA_API_KEY_ID or not APCA_API_SECRET_KEY:
        print("[Alpaca] FAILED: APCA_API_KEY_ID or APCA_API_SECRET_KEY is missing.")
        return False

    try:
        base_url = _normalize_alpaca_base_url(APCA_API_BASE_URL)
        client = tradeapi.REST(
            key_id=APCA_API_KEY_ID,
            secret_key=APCA_API_SECRET_KEY,
            base_url=base_url,
            api_version="v2",
        )
        account = client.get_account()
        print(f"[Alpaca] SUCCESS: cash={float(account.cash):,.2f}, account_status={account.status}")
        return True
    except Exception as e:
        print(f"[Alpaca] FAILED: {_redact(str(e))[:240]}")
        return False


if __name__ == "__main__":
    print("Running API connection tests...")
    gemini_ok = test_gemini()
    alpaca_ok = test_alpaca_api()

    if gemini_ok and alpaca_ok:
        print("All connection tests PASSED.")
    else:
        print("One or more connection tests FAILED.")