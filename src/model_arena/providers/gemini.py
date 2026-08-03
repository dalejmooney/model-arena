"""Google Gemini, the one that shares no assumptions with the other three.

Almost every decision here goes the other way:

  - the model is part of the URL, not the body, so switching model changes the
    endpoint rather than a field
  - the response is only Server-Sent Events because `?alt=sse` asks for it. The
    default streams a growing JSON array, which you cannot read a line at a time
  - text is nested two levels down a list of candidates, each holding a list of
    parts, so one chunk can legitimately carry several pieces of text
  - usage is a running total repeated on every chunk rather than reported once

The last one is the trap. Anthropic and OpenAI report each number once, so summing
what arrives is correct for them and would triple-count here. Taking the newest
value instead is right for all four, which is why that rule lives in `events.merge`
and not in any one provider.
"""

from collections.abc import Iterator
from typing import Any

from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

from model_arena.config import require_env
from model_arena.events import StreamEvent, Strict, Usage
from model_arena.providers.base import Request

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"


class Wire(Strict):
    """Gemini sends camelCase. Derive the wire names rather than aliasing by hand.

    One rule beats fifteen `Field(alias=...)` declarations, and it cannot drift out
    of step with the field it describes.
    """

    model_config = ConfigDict(extra="ignore", alias_generator=to_camel, populate_by_name=True)


class Part(Wire):
    text: str | None = None


class Content(Wire):
    parts: list[Part] = []


class Candidate(Wire):
    # A candidate can arrive carrying no content at all, for instance when the
    # chunk exists only to report why generation stopped.
    content: Content = Content()


class UsageMetadata(Wire):
    prompt_token_count: int = 0
    candidates_token_count: int = 0

    # Thinking models bill reasoning tokens as output but leave them out of
    # candidatesTokenCount, so a naive read undercounts what the call cost.
    thoughts_token_count: int = 0

    def normalise(self) -> Usage:
        return Usage(
            input_tokens=self.prompt_token_count,
            output_tokens=self.candidates_token_count + self.thoughts_token_count,
        )


class Chunk(Wire):
    candidates: list[Candidate] = []
    usage_metadata: UsageMetadata | None = None


class Gemini:
    name = "gemini"

    # Model ids date fast. Pass --model when comparing anything specific.
    default_model = "gemini-2.5-flash"

    def request(self, model: str, prompt: str, max_tokens: int) -> Request:
        return Request(
            # alt=sse is what makes this readable line by line at all.
            url=f"{API_ROOT}/{model}:streamGenerateContent?alt=sse",
            headers={
                "x-goog-api-key": require_env("GEMINI_API_KEY"),
                "content-type": "application/json",
            },
            payload={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens},
            },
        )

    def parse(self, chunk: dict[str, Any]) -> Iterator[StreamEvent]:
        parsed = Chunk.model_validate(chunk)
        for candidate in parsed.candidates:
            for part in candidate.content.parts:
                if part.text:
                    yield part.text
        if parsed.usage_metadata is not None:
            yield parsed.usage_metadata.normalise()
