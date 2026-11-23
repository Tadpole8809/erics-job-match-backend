"""Small wrapper around the Gemini API that always returns parsed JSON."""
import json

from app import config


class GeminiError(Exception):
    """Gemini is not configured, or the call failed / returned bad JSON."""


def is_configured() -> bool:
    return bool(config.gemini_api_key())


def generate_json(prompt: str) -> dict:
    """Send a prompt to Gemini and return its reply parsed as a JSON object."""
    key = config.gemini_api_key()
    if not key:
        raise GeminiError("GEMINI_API_KEY is not set in .env.")

    # Imported here so the rest of the app (and tests) work without the SDK loaded.
    from google import genai
    from google.genai import types

    try:
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=config.gemini_model(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
    except Exception as exc:  # the SDK raises several error types
        raise GeminiError(f"Gemini request failed: {exc}") from exc

    try:
        data = json.loads(response.text or "")
    except json.JSONDecodeError as exc:
        raise GeminiError("Gemini returned something that isn't valid JSON.") from exc
    if not isinstance(data, dict):
        raise GeminiError("Gemini returned JSON, but not an object.")
    return data
