"""Sentiment analysis module for trading decisions."""

from typing import Dict, List, Optional
import json
import re
from google import genai

from backend.config import GEMINI_API_KEY
from backend.gemini_client import get_gemini_client, list_available_gemini_models, select_gemini_model


def _redact_sensitive_text(text: str) -> str:
    """Redact likely secret values from loggable text."""
    redacted = text or ""
    if GEMINI_API_KEY:
        redacted = redacted.replace(GEMINI_API_KEY, "***REDACTED***")

    # Common Google API key-like pattern.
    redacted = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "***REDACTED***", redacted)
    return redacted


def get_gemini_model() -> Optional[genai.Client]:
    """Initialize and return a google-genai client."""
    return get_gemini_client()


def test_gemini_connection() -> Dict:
    """Send a simple prompt to Gemini and print a clear success/failure result."""
    try:
        client = get_gemini_model()
        if client is None:
            result = {
                "status": "error",
                "error": "GEMINI_API_KEY not configured"
            }
            print("[Gemini] FAILED: GEMINI_API_KEY not configured")
            return result

        model_names = list_available_gemini_models(client)
        if model_names:
            print("[Gemini] Available models:")
            for model_name in model_names:
                print(f"  - {model_name}")

        model_name = select_gemini_model(client)
        if not model_name:
            result = {
                "status": "error",
                "error": "No Gemini models available for this API key"
            }
            print("[Gemini] FAILED: No Gemini models available for this API key")
            return result

        response = client.models.generate_content(
            model=model_name,
            contents="Say OK",
        )
        text = (response.text or "").strip() or "(empty response)"
        result = {
            "status": "success",
            "response": text,
        }
        print(f"[Gemini] SUCCESS: {text}")
        return result
    except Exception as e:
        result = {
            "status": "error",
            "error": _redact_sensitive_text(str(e))[:200]
        }
        print(f"[Gemini] FAILED: {result['error']}")
        return result


def analyze_sentiment(headlines: List[str]) -> Dict:
    """
    Analyze sentiment from a list of headlines using Gemini API.
    
    Args:
        headlines: List of news headlines or text snippets
    
    Returns:
        dict with score (-1 to 1), label (bullish/neutral/bearish), and summary
    """
    if not headlines or not any(headlines):
        return {
            "score": 0.0,
            "label": "neutral",
            "summary": "No headlines provided"
        }
    
    try:
        client = get_gemini_model()
        if client is None:
            return {
                "score": 0.0,
                "label": "neutral",
                "summary": "Gemini SDK unavailable or GEMINI_API_KEY not configured"
            }
        
        model_name = select_gemini_model(client)
        if not model_name:
            return {
                "score": 0.0,
                "label": "neutral",
                "summary": "No Gemini models available for this API key"
            }

        # Prepare headlines text
        headlines_text = "\n".join([f"- {h}" for h in headlines if h])
        
        prompt = f"""Analyze the sentiment of these headlines and return ONLY a JSON object (no markdown, no explanation):

Headlines:
{headlines_text}

Return JSON with exactly these fields:
{{
  "score": <float between -1 (bearish) and 1 (bullish)>,
  "label": <"bullish", "neutral", or "bearish">,
  "summary": <one-sentence summary of overall sentiment>
}}

Guidelines:
- Score -1: extremely bearish, -0.5 to -1: bearish, -0.5 to 0.5: neutral, 0.5 to 1: bullish, 1: extremely bullish
- Be precise and consistent."""
        
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        raw_text = (response.text or "").strip()

        # Remove markdown code blocks if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        raw_text = raw_text.strip()

        # Parse JSON
        result = json.loads(raw_text)

        # Validate and sanitize response
        return {
            "score": float(max(-1, min(1, result.get("score", 0.0)))),
            "label": result.get("label", "neutral").lower(),
            "summary": str(result.get("summary", "No summary available"))[:200]
        }
    except json.JSONDecodeError as e:
        return {
            "score": 0.0,
            "label": "neutral",
            "summary": f"JSON parse error: {str(e)[:100]}"
        }
        
    except Exception as e:
        return {
            "score": 0.0,
            "label": "neutral",
            "summary": f"Analysis error: {str(e)[:100]}"
        }

