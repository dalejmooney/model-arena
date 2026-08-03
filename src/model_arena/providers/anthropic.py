"""Anthropic Messages API.

The odd one out in two ways, both of which are why it was written first.

Its stream is typed at the event level rather than the chunk level: instead of one
repeated shape with optional fields, you get half a dozen named event types and
have to know which carry what. And it reports the two halves of token usage at
opposite ends of the stream, so neither event on its own tells you what a call cost.
"""

from collections.abc import Iterator
from typing import Any

from model_arena.config import require_env
from model_arena.events import StreamEvent, Strict, Usage
from model_arena.providers.base import Request

API_URL = "https://api.anthropic.com/v1/messages"

# Anthropic pins breaking changes behind a date header rather than a URL version,
# so this is effectively "which shape of the API am I coding against".
API_VERSION = "2023-06-01"


class TextDelta(Strict):
    text: str


class ContentBlockDelta(Strict):
    """The event that actually carries generated text."""

    delta: TextDelta


class MessageInfo(Strict):
    usage: Usage


class MessageStart(Strict):
    """Arrives first. Carries the prompt's input token count."""

    message: MessageInfo


class MessageDelta(Strict):
    """Arrives last. Carries the completion's output token count."""

    usage: Usage


class Anthropic:
    name = "anthropic"
    default_model = "claude-sonnet-5"

    def request(self, model: str, prompt: str, max_tokens: int) -> Request:
        return Request(
            url=API_URL,
            headers={
                "x-api-key": require_env("ANTHROPIC_API_KEY"),
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            payload={
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
            },
        )

    def parse(self, chunk: dict[str, Any]) -> Iterator[StreamEvent]:
        match chunk.get("type"):
            case "content_block_delta":
                yield ContentBlockDelta.model_validate(chunk).delta.text
            case "message_start":
                yield MessageStart.model_validate(chunk).message.usage
            case "message_delta":
                yield MessageDelta.model_validate(chunk).usage
            case _:
                # ping, content_block_start, content_block_stop, message_stop and any
                # future event we have not met. Not our business.
                return
