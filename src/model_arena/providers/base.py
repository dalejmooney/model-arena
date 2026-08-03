"""One HTTP path, four wire formats.

The interesting discovery of this rung is how much of "calling a model provider" is
identical and how little of it is not. All four open a streaming POST, check the
status, and read Server-Sent Events line by line. What actually differs is three
things: where to send it, what the body looks like, and how to read a chunk.

So that is the seam. `Provider` supplies those three, `stream_events` does
everything else, once. Adding a fifth provider means writing a request builder and
a parser, and touching no transport code at all.

Only the transport is async. `request` and `parse` are ordinary functions, because
neither waits for anything: one builds a dict, the other reads one. Making them
async would spread `await` across the codebase in exchange for nothing, and the
useful discipline of async is being able to point at every place that actually
blocks. Here there is exactly one, and it is the network.

Written against raw HTTP rather than each provider's official SDK on purpose. The
whole point of the arena is comparing providers, and four libraries each making
their own decisions about retries, buffering and timeouts would quietly distort
exactly the thing being measured.
"""

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from model_arena.events import StreamEvent, Usage, merge

DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT = 60.0


@dataclass(frozen=True)
class Request:
    """A streaming request, described but not yet sent."""

    url: str
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


class Provider(Protocol):
    """The whole of what a provider has to supply.

    Deliberately not an abstract base class. A Protocol says "anything with this
    shape will do" without forcing every provider to inherit from us, which matters
    because Groq genuinely is an OpenAI clone and should inherit from *that*.
    """

    name: str
    default_model: str

    def request(self, model: str, prompt: str, max_tokens: int) -> Request:
        """Describe the call. Reads its own API key from the environment."""
        ...

    def parse(self, chunk: dict[str, Any]) -> Iterator[StreamEvent]:
        """Turn one decoded SSE payload into zero or more events."""
        ...


async def stream_events(
    provider: Provider,
    prompt: str,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[StreamEvent]:
    """Yield text as it arrives, plus token usage whenever the provider reports it.

    `transport` exists so tests can hand in a fake network. It is the difference
    between being able to test that four calls really do overlap and having to take
    it on faith.
    """
    request = provider.request(model or provider.default_model, prompt, max_tokens)

    # client.stream() rather than client.post(): post() waits for the whole body
    # before returning anything, which would defeat the exercise entirely.
    async with (
        httpx.AsyncClient(timeout=timeout, transport=transport) as client,
        client.stream(
            "POST", request.url, headers=request.headers, json=request.payload
        ) as response,
    ):
        if response.status_code != 200:
            # The body has not been read yet on a streaming response, so ask for it
            # explicitly before touching .text, or you get a confusing error about
            # accessing content on a stream.
            await response.aread()
            raise httpx.HTTPStatusError(
                f"{response.status_code} from {provider.name}: {response.text}",
                request=response.request,
                response=response,
            )

        async for line in response.aiter_lines():
            chunk = decode(line)
            if chunk is not None:
                for event in provider.parse(chunk):
                    yield event


def decode(line: str) -> dict[str, Any] | None:
    """Turn one Server-Sent Events line into a payload, or None to skip it.

    The wire format is plain text, one field per line, events separated by blanks:

        event: content_block_delta
        data: {"type": "content_block_delta", "delta": {"text": "Hello"}}

    Only `data:` lines carrying a JSON object are of interest. Everything else is
    skipped without complaint: `event:` lines duplicate what the payload already
    says, OpenAI and Groq end their streams with a literal `data: [DONE]`, and a
    provider adding new event types is routine and must never look like failure.

    This is the last point at which the data is untyped. Everything a parser sees
    below is a real dict, and everything after validation is trustworthy.
    """
    if not line.startswith("data:"):
        return None

    body = line.removeprefix("data:").strip()
    if not body:
        return None

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None

    return payload if isinstance(payload, dict) else None


async def collect(
    provider: Provider,
    prompt: str,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, Usage]:
    """Run a prompt to completion and return the full text with final token counts."""
    parts: list[str] = []
    usage = Usage()
    async for event in stream_events(provider, prompt, model, max_tokens, timeout, transport):
        if isinstance(event, str):
            parts.append(event)
        else:
            usage = merge(usage, event)
    return "".join(parts), usage
