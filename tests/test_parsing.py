"""Tests for the four wire formats.

Worth noticing that none of these touch the network. Splitting parsing out of the
HTTP call means the fiddly, breakable part can be tested against fixed input in
milliseconds, and the untestable part is reduced to "did the request go out".

The lines below are real, copied from actual streams rather than invented, so a
change in a provider's format shows up here as a failure.
"""

import pytest
from pydantic import ValidationError

from model_arena.events import StreamEvent, Usage, merge
from model_arena.providers import Provider, decode
from model_arena.providers.anthropic import Anthropic
from model_arena.providers.gemini import Gemini
from model_arena.providers.groq import Groq
from model_arena.providers.openai import OpenAI


def events(provider: Provider, line: str) -> list[StreamEvent]:
    """One raw SSE line, all the way through to typed events."""
    chunk = decode(line)
    return [] if chunk is None else list(provider.parse(chunk))


# ---- the shared decoder ------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "event: content_block_delta",  # field we do not need, the payload repeats it
        "data:",  # empty
        "data: not json at all",  # malformed
        'data: ["a", "list"]',  # valid json, wrong shape
        "data: [DONE]",  # how OpenAI and Groq say goodbye
        "",  # blank line between events
    ],
)
def test_lines_that_carry_no_payload_are_skipped(line: str) -> None:
    assert decode(line) is None


# ---- Anthropic ---------------------------------------------------------------

ANTHROPIC_TEXT = (
    'data: {"type": "content_block_delta", "index": 0, '
    '"delta": {"type": "text_delta", "text": "Hello"}}'
)
ANTHROPIC_START = (
    'data: {"type": "message_start", "message": {"model": "claude-sonnet-5", '
    '"usage": {"input_tokens": 14, "output_tokens": 0}}}'
)
ANTHROPIC_END = (
    'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, '
    '"usage": {"input_tokens": 14, "output_tokens": 11}}'
)


def test_anthropic_text_delta_yields_the_text() -> None:
    assert events(Anthropic(), ANTHROPIC_TEXT) == ["Hello"]


def test_anthropic_reports_its_two_token_counts_at_opposite_ends() -> None:
    assert events(Anthropic(), ANTHROPIC_START) == [Usage(input_tokens=14)]
    assert events(Anthropic(), ANTHROPIC_END) == [Usage(input_tokens=14, output_tokens=11)]


@pytest.mark.parametrize(
    "line",
    [
        'data: {"type": "ping"}',
        'data: {"type": "message_stop"}',
        'data: {"type": "some_event_shipped_after_this_was_written"}',
    ],
)
def test_anthropic_unknown_events_are_ignored_silently(line: str) -> None:
    """Unknown events must never be an error.

    Providers add event types over time. If a new one raised, the arena would break
    the day Anthropic shipped a feature we do not even use.
    """
    assert events(Anthropic(), line) == []


def test_an_event_we_claim_to_understand_but_cannot_parse_is_loud() -> None:
    """The other half of the rule above.

    Ignoring unknown events is correct. Ignoring a known event whose contents are
    wrong is not, because that is how text silently goes missing from an answer and
    nobody finds out. If content_block_delta arrives without text, we want to know.
    """
    with pytest.raises(ValidationError):
        events(Anthropic(), 'data: {"type": "content_block_delta", "delta": {}}')


# ---- OpenAI ------------------------------------------------------------------

OPENAI_TEXT = (
    'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", "choices": '
    '[{"index": 0, "delta": {"content": "Hello"}, "finish_reason": null}]}'
)
OPENAI_ROLE = (
    'data: {"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, '
    '"finish_reason": null}]}'
)
OPENAI_FINISH = 'data: {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}'
OPENAI_USAGE = (
    'data: {"choices": [], "usage": {"prompt_tokens": 14, "completion_tokens": 11, '
    '"total_tokens": 25}}'
)


def test_openai_text_chunk_yields_the_text() -> None:
    assert events(OpenAI(), OPENAI_TEXT) == ["Hello"]


@pytest.mark.parametrize("line", [OPENAI_ROLE, OPENAI_FINISH])
def test_openai_chunks_without_content_are_not_a_failure(line: str) -> None:
    """The opposite of the Anthropic rule, and deliberately so.

    Anthropic names its events, so an event called content_block_delta with no text
    in it is broken. OpenAI sends one shape for everything, so a delta with no
    content is just the chunk announcing the role, or the one carrying finish_reason.
    """
    assert events(OpenAI(), line) == []


def test_openai_reports_both_token_counts_in_one_final_chunk() -> None:
    assert events(OpenAI(), OPENAI_USAGE) == [Usage(input_tokens=14, output_tokens=11)]


# ---- Groq --------------------------------------------------------------------

GROQ_TEXT = 'data: {"choices": [{"index": 0, "delta": {"content": "Hello"}}]}'
GROQ_USAGE = (
    'data: {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], '
    '"x_groq": {"id": "req_1", "usage": {"prompt_tokens": 9, "completion_tokens": 21}}}'
)


def test_groq_parses_openai_shaped_text_with_no_extra_code() -> None:
    assert events(Groq(), GROQ_TEXT) == ["Hello"]


def test_groq_hides_its_token_counts_somewhere_else() -> None:
    """The one place the clone is not a clone.

    A client that only knows the OpenAI shape streams from Groq perfectly happily
    and silently never learns what anything cost, which is the failure this whole
    project exists to notice.
    """
    assert events(Groq(), GROQ_USAGE) == [Usage(input_tokens=9, output_tokens=21)]
    assert events(OpenAI(), GROQ_USAGE) == []


# ---- Gemini ------------------------------------------------------------------

GEMINI_TEXT = (
    'data: {"candidates": [{"content": {"parts": [{"text": "Hello"}], "role": "model"}, '
    '"index": 0}], "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 1, '
    '"totalTokenCount": 9}, "modelVersion": "gemini-2.5-flash"}'
)
GEMINI_FINISH = (
    'data: {"candidates": [{"finishReason": "STOP", "index": 0}], '
    '"usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 12, '
    '"totalTokenCount": 20}}'
)
# Real, from a gemini-3.6-flash call whose entire answer was the word "Blue".
GEMINI_THINKING = (
    'data: {"usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 1, '
    '"thoughtsTokenCount": 168, "totalTokenCount": 176, "serviceTier": "standard"}}'
)


def test_gemini_text_is_nested_two_lists_deep_and_arrives_with_a_running_total() -> None:
    assert events(Gemini(), GEMINI_TEXT) == ["Hello", Usage(input_tokens=8, output_tokens=1)]


def test_gemini_candidate_with_no_content_is_not_a_failure() -> None:
    assert events(Gemini(), GEMINI_FINISH) == [Usage(input_tokens=8, output_tokens=12)]


def test_gemini_reasoning_tokens_count_as_output() -> None:
    """They are billed as output but left out of candidatesTokenCount.

    These are real numbers off a real call, and they are the reason this test
    exists: the visible answer was one word, so the obvious field says 1, while
    the call was actually billed for 169. Reading the obvious field would have
    under-reported the cost of a thinking model by more than a hundredfold, and
    nothing about the response would have looked wrong.
    """
    assert events(Gemini(), GEMINI_THINKING) == [Usage(input_tokens=7, output_tokens=169)]


# ---- putting the halves together ---------------------------------------------


def test_merge_fills_in_counts_reported_separately() -> None:
    """Anthropic's style: each event supplies a number the other left at zero."""
    usage = merge(Usage(), Usage(input_tokens=14))
    assert merge(usage, Usage(output_tokens=11)) == Usage(input_tokens=14, output_tokens=11)


def test_merge_takes_the_newest_running_total_rather_than_adding_it_up() -> None:
    """Gemini's style: summing these would count every chunk again."""
    usage = merge(Usage(), Usage(input_tokens=8, output_tokens=1))
    usage = merge(usage, Usage(input_tokens=8, output_tokens=7))
    assert merge(usage, Usage(input_tokens=8, output_tokens=12)) == Usage(
        input_tokens=8, output_tokens=12
    )
