"""What we expect to come back from a streaming provider.

A pydantic model is a description of a shape. You hand it whatever arrived off the
network and it either returns a properly typed object, or raises with a precise
account of what was wrong. That check happens at runtime, which is the thing plain
type hints cannot do: `x: int` is a note to a checker, `Usage(**data)` is a gate.

Only the events we actually use are modelled. Providers add event types over time and
an unknown one must never be an error, so parsing is "try these, otherwise ignore".
"""

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    """Shared base so every model below refuses silently-wrong data the same way.

    `extra="ignore"` means unknown fields are dropped rather than rejected. That is
    deliberate: a provider adding a field is normal and must not break us. What we
    are defending against is a field we DO rely on being missing or the wrong type.
    """

    model_config = ConfigDict(extra="ignore")


class Usage(_Strict):
    """Token counts. Anthropic reports input and output at different moments."""

    input_tokens: int = 0
    output_tokens: int = 0


class TextDelta(_Strict):
    text: str


class ContentBlockDelta(_Strict):
    """The event that actually carries generated text."""

    delta: TextDelta


class _MessageInfo(_Strict):
    usage: Usage


class MessageStart(_Strict):
    """Arrives first. Carries the prompt's input token count."""

    message: _MessageInfo


class MessageDelta(_Strict):
    """Arrives last. Carries the completion's output token count."""

    usage: Usage
