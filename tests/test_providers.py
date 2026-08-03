"""Tests for the interface itself, rather than for any one provider.

The point of these is that adding a fifth provider cannot quietly half-work. A
provider that forgets its auth header, builds a URL without the model in it, or
leaves the prompt out of the body will fail here rather than at the first real call.
"""

import pytest

from model_arena.providers import PROVIDERS, UnknownProvider, resolve

KEYS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"]


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """So these run identically whether or not a real key happens to be on the box."""
    for key in KEYS:
        monkeypatch.setenv(key, f"test-{key.lower()}")


@pytest.fixture(params=sorted(PROVIDERS))
def name(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def test_every_provider_can_describe_a_call(name: str) -> None:
    request = PROVIDERS[name].request("some-model", "hello", 64)
    assert request.url.startswith("https://")
    assert request.headers
    assert request.payload


def test_every_provider_puts_the_model_somewhere(name: str) -> None:
    """In the body for three of them, in the URL for Gemini. Either is fine."""
    request = PROVIDERS[name].request("some-model", "hello", 64)
    assert "some-model" in request.url or "some-model" in request.payload.values()


def test_every_provider_sends_the_prompt(name: str) -> None:
    request = PROVIDERS[name].request("some-model", "unmistakeable-prompt", 64)
    assert "unmistakeable-prompt" in repr(request.payload)


def test_every_provider_authenticates(name: str) -> None:
    request = PROVIDERS[name].request("some-model", "hello", 64)
    assert any("test-" in value for value in request.headers.values())


def test_every_provider_bounds_the_response(name: str) -> None:
    """A provider that drops max_tokens turns a typo into an expensive afternoon."""
    request = PROVIDERS[name].request("some-model", "hello", 64)
    assert "64" in repr(request.payload)


def test_a_bare_provider_name_means_its_default_model() -> None:
    provider, model = resolve("anthropic")
    assert provider.name == "anthropic"
    assert model == provider.default_model


def test_a_model_can_be_named_explicitly() -> None:
    provider, model = resolve("openai:gpt-4.1")
    assert provider.name == "openai"
    assert model == "gpt-4.1"


def test_an_unknown_provider_says_what_it_does_know() -> None:
    with pytest.raises(UnknownProvider, match="anthropc"):
        resolve("anthropc:claude-sonnet-5")
