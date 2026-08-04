"""Tests for the fan-out.

The claim this rung makes is that four models cost the slowest one rather than the
sum of four, and a claim like that is worth actually measuring rather than assuming.
`httpx.MockTransport` gives us a fake network with controllable delays, so the test
can assert the overlap really happens without ever leaving the machine.

The other two things worth pinning are what happens when a provider misbehaves: one
failure must not take down the run, and results must not quietly reorder themselves.
"""

import asyncio
import time

import httpx
import pytest

from model_arena.arena import run_many
from model_arena.providers import UnknownProvider

KEYS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"]

# A minimal but genuinely valid stream for each provider, in that provider's shape.
BODIES = {
    "anthropic": (
        b'data: {"type":"message_start","message":{"usage":{"input_tokens":10}}}\n\n'
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Blue"}}\n\n'
        b'data: {"type":"message_delta","usage":{"output_tokens":2}}\n\n'
    ),
    "openai": (
        b'data: {"choices":[{"delta":{"content":"Blue"}}]}\n\n'
        b'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":3}}\n\n'
        b"data: [DONE]\n\n"
    ),
    "gemini": (
        b'data: {"candidates":[{"content":{"parts":[{"text":"Blue"}]}}],'
        b'"usageMetadata":{"promptTokenCount":7,"candidatesTokenCount":1,'
        b'"thoughtsTokenCount":5}}\n\n'
    ),
    "groq": (
        b'data: {"choices":[{"delta":{"content":"Blue"}}]}\n\n'
        b'data: {"choices":[{"delta":{}}],'
        b'"x_groq":{"usage":{"prompt_tokens":40,"completion_tokens":2}}}\n\n'
        b"data: [DONE]\n\n"
    ),
}

HOSTS = {
    "api.anthropic.com": "anthropic",
    "api.openai.com": "openai",
    "generativelanguage.googleapis.com": "gemini",
    "api.groq.com": "groq",
}


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in KEYS:
        monkeypatch.setenv(key, f"test-{key.lower()}")


def fake_network(
    delays: dict[str, float] | None = None,
    broken: set[str] | None = None,
) -> httpx.MockTransport:
    """A network where each provider can be given its own speed and its own bad day."""
    delays = delays or {}
    broken = broken or set()

    async def handler(request: httpx.Request) -> httpx.Response:
        name = HOSTS[request.url.host]
        await asyncio.sleep(delays.get(name, 0.0))
        if name in broken:
            return httpx.Response(500, text="upstream is having a moment")
        return httpx.Response(200, content=BODIES[name])

    return httpx.MockTransport(handler)


def test_every_provider_is_understood_by_the_fake_network() -> None:
    """Guards the tests below: a typo'd host would silently skip a provider."""
    assert set(HOSTS.values()) == set(BODIES) == {"anthropic", "openai", "gemini", "groq"}


def test_the_calls_actually_overlap() -> None:
    """The claim of this rung, measured rather than assumed.

    Four providers, a quarter of a second each. Run one at a time that is a second;
    run together it is a quarter. The threshold is deliberately loose because this
    is wall-clock timing on a machine doing other things, and a test that fails when
    something else is compiling is worse than no test.
    """
    transport = fake_network(delays=dict.fromkeys(BODIES, 0.25))

    started = time.perf_counter()
    results = asyncio.run(run_many(sorted(BODIES), "hi", transport=transport))
    elapsed = time.perf_counter() - started

    assert len(results) == 4
    assert all(result.ok for result in results)
    assert elapsed < 0.6, f"took {elapsed:.2f}s, so the calls were not concurrent"


def test_a_failing_provider_does_not_take_down_the_others() -> None:
    """One provider having a bad day is a row in the table, not the end of the run."""
    transport = fake_network(broken={"groq"})
    results = asyncio.run(run_many(sorted(BODIES), "hi", transport=transport))

    by_name = {result.provider: result for result in results}
    assert not by_name["groq"].ok
    assert "500" in str(by_name["groq"].error)
    assert [name for name, result in by_name.items() if result.ok] == [
        "anthropic",
        "gemini",
        "openai",
    ]


def test_results_come_back_in_the_order_asked_for() -> None:
    """Otherwise the fastest model sorts itself to the top of every table."""
    transport = fake_network(delays={"gemini": 0.25, "anthropic": 0.0})
    results = asyncio.run(run_many(["gemini", "anthropic"], "hi", transport=transport))

    assert [result.provider for result in results] == ["gemini", "anthropic"]


def test_each_provider_is_parsed_with_its_own_rules() -> None:
    """End to end through the real parsers, so a shared shortcut would show up here."""
    transport = fake_network()
    results = asyncio.run(run_many(sorted(BODIES), "hi", transport=transport))
    usage = {result.provider: result.usage for result in results}

    assert all(result.text == "Blue" for result in results)
    assert usage["anthropic"].input_tokens == 10  # halves merged from two events
    assert usage["openai"].output_tokens == 3  # one final usage chunk
    assert usage["gemini"].output_tokens == 6  # candidates + thoughts
    assert usage["groq"].output_tokens == 2  # dug out of the x_groq envelope


def test_a_typo_in_a_provider_name_fails_before_anything_is_called() -> None:
    """Loud and immediate beats one puzzling row among three good ones."""
    with pytest.raises(UnknownProvider):
        asyncio.run(run_many(["anthropic", "gemmini"], "hi", transport=fake_network()))
