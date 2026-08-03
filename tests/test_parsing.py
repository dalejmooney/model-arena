"""Tests for the SSE parser.

Worth noticing that none of these touch the network. Splitting parsing out of the
HTTP call means the fiddly, breakable part can be tested against fixed input in
milliseconds, and the untestable part is reduced to "did the request go out".

The lines below are real, copied from an actual Anthropic stream rather than
invented, so a change in their format shows up here as a failure.
"""

import pytest
from pydantic import ValidationError

from model_arena.anthropic import _parse_sse_line
from model_arena.events import Usage

TEXT_DELTA = (
    'data: {"type": "content_block_delta", "index": 0, '
    '"delta": {"type": "text_delta", "text": "Hello"}}'
)
MESSAGE_START = (
    'data: {"type": "message_start", "message": {"model": "claude-sonnet-5", '
    '"usage": {"input_tokens": 14, "output_tokens": 0}}}'
)
MESSAGE_DELTA = (
    'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, '
    '"usage": {"input_tokens": 14, "output_tokens": 11}}'
)


def test_text_delta_yields_the_text() -> None:
    assert list(_parse_sse_line(TEXT_DELTA)) == ["Hello"]


def test_message_start_yields_input_tokens() -> None:
    assert list(_parse_sse_line(MESSAGE_START)) == [Usage(input_tokens=14, output_tokens=0)]


def test_message_delta_yields_output_tokens() -> None:
    assert list(_parse_sse_line(MESSAGE_DELTA)) == [Usage(input_tokens=14, output_tokens=11)]


@pytest.mark.parametrize(
    "line",
    [
        'event: content_block_delta',          # not a data line
        'data:',                                # empty
        'data: {"type": "ping"}',               # event we do not care about
        'data: {"type": "message_stop"}',       # ditto
        'data: not json at all',                # malformed
        'data: ["a", "list"]',                  # valid json, wrong shape
    ],
)
def test_uninteresting_lines_are_ignored_silently(line: str) -> None:
    """Unknown events must never be an error.

    Providers add event types over time. If a new one raised, the arena would break
    the day Anthropic shipped a feature we do not even use.
    """
    assert list(_parse_sse_line(line)) == []


def test_an_event_we_claim_to_understand_but_cannot_parse_is_loud() -> None:
    """The other half of the rule above.

    Ignoring unknown events is correct. Ignoring a known event whose contents are
    wrong is not, because that is how text silently goes missing from an answer and
    nobody finds out. If content_block_delta arrives without text, we want to know.
    """
    broken = 'data: {"type": "content_block_delta", "delta": {}}'
    with pytest.raises(ValidationError):
        list(_parse_sse_line(broken))
