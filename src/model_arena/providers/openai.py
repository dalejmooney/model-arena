"""OpenAI Chat Completions, and the shape half the industry copied.

Where Anthropic names its events, OpenAI sends one repeated chunk shape with almost
everything optional, and you work out what a chunk means by which fields are filled
in. That has a consequence for validation: a chunk whose `delta` carries no content
is not broken, it is the first chunk announcing the role, or the last one carrying
`finish_reason`. So unlike Anthropic's text event, missing text here has to be
tolerated rather than raised on.

Usage is opt-in. Without `stream_options`, a streamed response reports no tokens at
all and the call silently costs an unknown amount, which for this project is worse
than an error.
"""

from collections.abc import Iterator
from typing import Any

from model_arena.config import require_env
from model_arena.events import StreamEvent, Strict, Usage
from model_arena.providers.base import Request


class ChunkUsage(Strict):
    """OpenAI's names for the same two numbers."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    def normalise(self) -> Usage:
        return Usage(input_tokens=self.prompt_tokens, output_tokens=self.completion_tokens)


class Delta(Strict):
    content: str | None = None


class Choice(Strict):
    delta: Delta = Delta()


class Chunk(Strict):
    """One streamed chunk. Text, usage, both or neither."""

    choices: list[Choice] = []
    usage: ChunkUsage | None = None

    def resolve_usage(self) -> Usage | None:
        """Where in this chunk the token counts live, if they are here at all.

        Its own method purely so a clone that puts them somewhere else can say so
        without reimplementing the parser around it.
        """
        return self.usage.normalise() if self.usage is not None else None


class OpenAI:
    name = "openai"

    # Model ids date faster than anything else in this file. Treat these as a
    # starting point and pass --model when comparing anything specific.
    default_model = "gpt-5"

    url = "https://api.openai.com/v1/chat/completions"
    key_var = "OPENAI_API_KEY"
    chunk_model: type[Chunk] = Chunk

    # `max_tokens` is deprecated here and rejected outright by the reasoning models,
    # because it used to mean "answer length" and now has to cover hidden reasoning
    # too. Compatible clones mostly did not follow, hence the override point.
    max_tokens_field = "max_completion_tokens"

    def request(self, model: str, prompt: str, max_tokens: int) -> Request:
        return Request(
            url=self.url,
            headers={
                "Authorization": f"Bearer {require_env(self.key_var)}",
                "content-type": "application/json",
            },
            payload={
                "model": model,
                self.max_tokens_field: max_tokens,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                # Without this the stream reports no token counts whatsoever.
                "stream_options": {"include_usage": True},
            },
        )

    def parse(self, chunk: dict[str, Any]) -> Iterator[StreamEvent]:
        parsed = self.chunk_model.model_validate(chunk)
        for choice in parsed.choices:
            if choice.delta.content:
                yield choice.delta.content
        usage = parsed.resolve_usage()
        if usage is not None:
            yield usage
