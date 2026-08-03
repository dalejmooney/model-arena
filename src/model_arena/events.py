"""What every provider has to give us, whatever shape it arrives in.

Each provider's own wire models live next to the parser that reads them, because a
shape only means anything to the code decoding it, and putting all four in one file
would suggest a family resemblance that does not exist. What is genuinely shared is
what comes out the other end: text, and token counts.

A pydantic model is a description of a shape. You hand it whatever arrived off the
network and it either returns a properly typed object, or raises with a precise
account of what was wrong. That check happens at runtime, which is the thing plain
type hints cannot do: `x: int` is a note to a checker, `Usage(**data)` is a gate.
"""

from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    """Shared base so every wire model refuses silently-wrong data the same way.

    `extra="ignore"` means unknown fields are dropped rather than rejected. That is
    deliberate: a provider adding a field is normal and must not break us. What we
    are defending against is a field we DO rely on being missing or the wrong type.
    """

    model_config = ConfigDict(extra="ignore")


class Usage(Strict):
    """Token counts, normalised.

    Every provider names these differently and reports them at a different moment.
    Anthropic splits input and output across two events, OpenAI sends both in one
    final chunk, Gemini repeats a running total on every chunk. Normalising here
    means the accounting code never has to know which it is talking to.
    """

    input_tokens: int = 0
    output_tokens: int = 0


# An event off the wire is either a piece of text or an update to the token counts.
StreamEvent = str | Usage


def merge(old: Usage, new: Usage) -> Usage:
    """Fold a usage update into what we have so far.

    Take the newer value when there is one, otherwise keep what we had. That single
    rule covers all three reporting styles above: Anthropic's halves each fill in a
    field the other left at zero, OpenAI's one-shot report overwrites nothing that
    mattered, and Gemini's running total is always the newest number.
    """
    return Usage(
        input_tokens=new.input_tokens or old.input_tokens,
        output_tokens=new.output_tokens or old.output_tokens,
    )
