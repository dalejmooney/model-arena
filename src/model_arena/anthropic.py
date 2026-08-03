"""Streaming text out of Anthropic's Messages API.

Written against raw HTTP rather than the official SDK on purpose. Every provider
in the arena goes through the same shape, so the comparison is not distorted by
four different libraries each making their own decisions about retries, timeouts
and buffering.
"""

import json
from collections.abc import Iterator

import httpx

from model_arena.config import require_env

API_URL = "https://api.anthropic.com/v1/messages"

# Anthropic pins breaking changes behind a date header rather than a URL version,
# so this is effectively "which shape of the API am I coding against".
API_VERSION = "2023-06-01"


def stream_text(
    prompt: str,
    model: str = "claude-sonnet-5",
    max_tokens: int = 1024,
    timeout: float = 60.0,
) -> Iterator[str]:
    """Yield chunks of the model's reply as they arrive.

    Returns an Iterator rather than a string because the whole point is not waiting.
    The caller decides what to do with each piece, which for now is printing it.

    A generator also means the HTTP connection stays open only while the caller is
    still consuming. Stop iterating and the `with` blocks unwind and close it.
    """
    headers = {
        "x-api-key": require_env("ANTHROPIC_API_KEY"),
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }

    # client.stream() rather than client.post(): post() waits for the whole body
    # before returning anything, which would defeat the exercise entirely.
    with (
        httpx.Client(timeout=timeout) as client,
        client.stream("POST", API_URL, headers=headers, json=payload) as response,
    ):
        if response.status_code != 200:
            # The body has not been read yet on a streaming response, so ask for it
            # explicitly before touching .text, or you get a confusing error about
            # accessing content on a stream.
            response.read()
            raise httpx.HTTPStatusError(
                f"{response.status_code} from Anthropic: {response.text}",
                request=response.request,
                response=response,
            )

        for line in response.iter_lines():
            text = _text_from_sse_line(line)
            if text is not None:
                yield text


def _text_from_sse_line(line: str) -> str | None:
    """Pull the text out of one Server-Sent Events line, if it carries any.

    The wire format is plain text, one field per line, events separated by blanks:

        event: content_block_delta
        data: {"type": "content_block_delta", "delta": {"text": "Hello"}}

    We only care about `data:` lines, and only those carrying a text delta. Everything
    else is lifecycle noise: message_start, ping, content_block_stop and so on.
    """
    if not line.startswith("data:"):
        return None

    body = line.removeprefix("data:").strip()
    if not body or body == "[DONE]":
        return None

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        return None

    # Deliberately defensive: this is untrusted data off the network, and every
    # assumption about its shape is a guess until it arrives. mypy cannot help
    # here, because json.loads gives back Any.
    if not isinstance(event, dict) or event.get("type") != "content_block_delta":
        return None

    delta = event.get("delta")
    if not isinstance(delta, dict):
        return None

    text = delta.get("text")
    return text if isinstance(text, str) else None
