"""Every provider the arena can talk to, and how to name one.

Deliberately not a catalogue of models. A hardcoded list of model ids is wrong
within weeks and the arena exists precisely to try models that are newer than it
is, so a model is just a string the provider is handed. What is stable enough to
write down is the set of providers.
"""

from model_arena.providers.anthropic import Anthropic
from model_arena.providers.base import Provider, Request, collect, decode, stream_events
from model_arena.providers.gemini import Gemini
from model_arena.providers.groq import Groq
from model_arena.providers.openai import OpenAI

PROVIDERS: dict[str, Provider] = {
    provider.name: provider for provider in (Anthropic(), OpenAI(), Gemini(), Groq())
}


class UnknownProvider(KeyError):
    """A model reference named a provider that does not exist."""


def resolve(reference: str) -> tuple[Provider, str]:
    """Turn `anthropic:claude-sonnet-5` into the provider and the model it named.

    Bare `anthropic` is allowed and means that provider's default model, so trying a
    new provider does not require knowing its current model ids first.
    """
    name, _, model = reference.partition(":")
    try:
        provider = PROVIDERS[name]
    except KeyError:
        raise UnknownProvider(
            f"unknown provider {name!r}. Known: {', '.join(sorted(PROVIDERS))}"
        ) from None
    return provider, model or provider.default_model


__all__ = [
    "PROVIDERS",
    "Provider",
    "Request",
    "UnknownProvider",
    "collect",
    "decode",
    "resolve",
    "stream_events",
]
