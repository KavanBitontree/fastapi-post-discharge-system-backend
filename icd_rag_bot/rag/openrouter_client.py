import os
import requests
from typing import Any, Dict, List, Optional


OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(RuntimeError):
    pass


def chat_completion(
    *,
    model: str,
    api_key: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 900,
    extra_headers: Optional[Dict[str, str]] = None,
) -> str:
    """
    Calls OpenRouter Chat Completions API and returns the assistant text.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Optional but recommended by OpenRouter for analytics/rate-limits:
    # You can set these in your environment if you want:
    #   OPENROUTER_SITE_URL, OPENROUTER_APP_NAME
    site_url = os.getenv("OPENROUTER_SITE_URL")
    app_name = os.getenv("OPENROUTER_APP_NAME")
    if site_url:
        headers["HTTP-Referer"] = site_url
    if app_name:
        headers["X-Title"] = app_name

    if extra_headers:
        headers.update(extra_headers)

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        raise OpenRouterError(f"OpenRouter request failed: {e}") from e

    if resp.status_code >= 400:
        raise OpenRouterError(f"OpenRouter error {resp.status_code}: {resp.text}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise OpenRouterError(f"Unexpected OpenRouter response: {data}")