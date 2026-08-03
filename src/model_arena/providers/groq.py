"""Groq, which is OpenAI's API served on different hardware.

The whole provider is four constants and one quirk, and that is the finding worth
recording: "supports the OpenAI API" is now a category, and most of what looks like
provider diversity is one wire format with local dialects. The interface earns its
keep here by making a new provider cost nothing when it is a clone, rather than by
absorbing four genuinely different designs.

The dialect: Groq reports token counts in its own `x_groq` envelope rather than the
standard `usage` field, so a client that only knows OpenAI streams from Groq quite
happily and silently never learns what anything cost.
"""

from model_arena.events import Strict, Usage
from model_arena.providers.openai import Chunk, ChunkUsage, OpenAI


class GroqExtra(Strict):
    usage: ChunkUsage | None = None


class GroqChunk(Chunk):
    x_groq: GroqExtra | None = None

    def resolve_usage(self) -> Usage | None:
        standard = super().resolve_usage()
        if standard is not None:
            return standard
        if self.x_groq is not None and self.x_groq.usage is not None:
            return self.x_groq.usage.normalise()
        return None


class Groq(OpenAI):
    name = "groq"

    # Groq serves open-weights models, so this dates with the models rather than
    # with Groq. Pass --model for anything specific.
    default_model = "llama-3.3-70b-versatile"

    url = "https://api.groq.com/openai/v1/chat/completions"
    key_var = "GROQ_API_KEY"
    chunk_model = GroqChunk

    # Groq kept `max_tokens` when OpenAI moved on, which is the usual shape of
    # compatibility: the clone tracks the version it was copied from.
    max_tokens_field = "max_tokens"
