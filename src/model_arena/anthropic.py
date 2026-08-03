"""Streaming text and token usage out of Anthropic's Messages API.

Written against raw HTTP rather than the official SDK on purpose. Every provider in
the arena goes through the same shape, so the comparison is not distorted by four
different libraries each making their own decisions about retries and buffering.

Two layers here, deliberately:

  stream_events()  the real one. Yields typed events, including token usage.
  stream_text()    a thin filter over it for callers that only want the words.

Splitting them means the CLI stays simple while the accounting still gets its data,
rather than having one function that returns a tuple of unrelated things.
"""

import json
from collections.abc import Iterator

import httpx
from pydantic import ValidationError

from model_arena.config import require_env
from model_arena.events import ContentBlockDelta, MessageDelta, MessageStart, Usage

API_URL = "https://api.anthropic.com/v1/messages"

# Anthropic pins breaking changes behind a date header rather than a URL version,
# so this is effectively "which shape of the API am I coding against".
API_VERSION = "2023-06-01"

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT = 60.0

# An event is either a piece of text or an update to the token counts.
StreamEvent = str | Usage


def stream_events(
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
) -> Iterator[StreamEvent]:
    """Yield text as it arrives, plus token usage whenever the provider reports it."""
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
            yield from _parse_sse_line(line)


def stream_text(
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
) -> Iterator[str]:
    """Just the words. Everything else from the stream is dropped."""
    for event in stream_events(prompt, model, max_tokens, timeout):
        if isinstance(event, str):
            yield event


def _parse_sse_line(line: str) -> Iterator[StreamEvent]:
    """Turn one Server-Sent Events line into zero or more typed events.

    The wire format is plain text, one field per line, events separated by blanks:

        event: content_block_delta
        data: {"type": "content_block_delta", "delta": {"text": "Hello"}}

    Anything that is not a `data:` line carrying JSON we understand is skipped. A
    provider adding new event types is routine and must never be treated as failure.
    """
    if not line.startswith("data:"):
        return

    body = line.removeprefix("data:").strip()
    if not body:
        return

    try:
        raw = json.loads(body)
    except json.JSONDecodeError:
        return

    # json.loads hands back Any, so this is the last point at which the data is
    # untyped. Everything below is validated, and everything after is trustworthy.
    if not isinstance(raw, dict):
        return

    match raw.get("type"):
        case "content_block_delta":
            yield ContentBlockDelta.model_validate(raw).delta.text
        case "message_start":
            yield MessageStart.model_validate(raw).message.usage
        case "message_delta":
            yield MessageDelta.model_validate(raw).usage
        case _:
            # ping, content_block_start, content_block_stop, message_stop and any
            # future event we have not met. Not our business.
            return


def collect(
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[str, Usage]:
    """Run a prompt to completion and return the full text with final token counts.

    Input and output token counts arrive in different events, so they are merged as
    they turn up rather than assuming a single event carries both.
    """
    parts: list[str] = []
    usage = Usage()
    for event in stream_events(prompt, model, max_tokens, timeout):
        if isinstance(event, str):
            parts.append(event)
        else:
            usage = Usage(
                input_tokens=event.input_tokens or usage.input_tokens,
                output_tokens=event.output_tokens or usage.output_tokens,
            )
    return "".join(parts), usage


__all__ = ["ValidationError", "collect", "stream_events", "stream_text"]
