import os
import json
from groq import Groq

SYSTEM_PROMPT = """You are a financial assistant that classifies user queries about stocks.

Given a user prompt, extract the following and return ONLY valid JSON (no markdown, no explanation):

{
  "intent": one of ["analyze", "correlation", "portfolio", "compare", "general"],
  "tickers": [list of stock ticker symbols found in the prompt, uppercase, e.g. ["TSLA", "AAPL"]],
  "query_type": short description of what the user wants (e.g. "stock analysis", "price comparison"),
  "response_style": one of ["short", "long"] based on complexity of the question
}

Intent definitions:
- "analyze": user wants analysis, recommendation, or insight on a single stock
- "correlation": user wants to see correlation between multiple stocks
- "portfolio": user wants to see or manage their portfolio
- "compare": user wants to compare two or more stocks
- "general": general market question or unrelated query

Always return valid JSON. If no tickers are found, return an empty list for tickers."""


def route_query(prompt: str) -> dict:
    """
    Use Groq to classify user intent and extract structured data from a prompt.

    Returns:
        dict with keys: intent, tickers, query_type, response_style
    """
    try:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            return {
                "intent": "general",
                "tickers": [],
                "query_type": "no_api_key",
                "response_style": "short"
            }
        
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=200
        )

        raw = response.choices[0].message.content.strip()

        # Parse JSON response
        result = json.loads(raw)

        # Validate and ensure all required keys are present
        return {
            "intent": result.get("intent", "general"),
            "tickers": result.get("tickers", []),
            "query_type": result.get("query_type", "unknown"),
            "response_style": result.get("response_style", "short")
        }

    except json.JSONDecodeError:
        return {
            "intent": "general",
            "tickers": [],
            "query_type": "parse_error",
            "response_style": "short"
        }
    except Exception as e:
        return {
            "intent": "general",
            "tickers": [],
            "query_type": f"error: {str(e)}",
            "response_style": "short"
        }
