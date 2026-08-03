"""What a call cost, or an honest refusal to guess.

Token counts are facts the provider reported. Prices are not: they live on a web
page somebody else edits, they change without warning, and some of them are
promotional and expire on a date. So the two are kept apart. `events.Usage` is
measurement, this module is valuation, and the interesting design problem is
entirely in what happens when the valuation is not available.

The rule that shapes everything here: **an unknown price is never zero.** A model
missing from the table returns None and gets reported as unknown, because a
comparison table that quietly shows £0.00 for the one model nobody priced is worse
than one that shows nothing at all. That is the same failure this project keeps
running into, one layer up: a confident number that happens to be wrong, with
nothing about it looking wrong.

Prices below were read from each provider's own page on the date in `CHECKED`.
Do not edit them from memory. Go and look.
"""

from datetime import date

from pydantic import BaseModel

from model_arena.events import Usage

# When a human last opened all four pricing pages and compared them to this file.
CHECKED = date(2026, 8, 3)

# Every figure here is US dollars per million tokens.
CURRENCY = "USD"


def cost(tokens: int, per_million: float) -> float:
    """Cost of `tokens` at a price quoted per million tokens.

    Providers all quote per-million rates, so doing the division here once means
    no call site has to remember how many zeroes are in a million.
    """
    return tokens / 1_000_000 * per_million


class Price(BaseModel):
    """What one model costs, and how long that is known to be true for."""

    input_per_million: float
    output_per_million: float
    source: str

    # Promotional rates are real and they end. `expires` is not "the price rises
    # here", it is "past this date I no longer know what this costs". Letting it
    # lapse into unknown is deliberate: a stale price is indistinguishable from a
    # current one at the point you read the total, which is exactly too late.
    expires: date | None = None

    def known_on(self, day: date) -> bool:
        return self.expires is None or day <= self.expires

    def of(self, usage: Usage) -> float:
        return cost(usage.input_tokens, self.input_per_million) + cost(
            usage.output_tokens, self.output_per_million
        )


PRICES: dict[str, Price] = {
    # Anthropic. https://platform.claude.com/docs/en/pricing
    "claude-opus-5": Price(
        input_per_million=5.00, output_per_million=25.00, source="anthropic"
    ),
    # Introductory rate. Reverts to 3.00 / 15.00 after this date, but the table
    # says unknown rather than assuming the changeover happened as announced.
    "claude-sonnet-5": Price(
        input_per_million=2.00,
        output_per_million=10.00,
        source="anthropic",
        expires=date(2026, 8, 31),
    ),
    "claude-haiku-4-5": Price(
        input_per_million=1.00, output_per_million=5.00, source="anthropic"
    ),
    "claude-opus-4-8": Price(
        input_per_million=5.00, output_per_million=25.00, source="anthropic"
    ),
    # OpenAI. https://developers.openai.com/api/docs/pricing
    "gpt-5": Price(input_per_million=1.25, output_per_million=10.00, source="openai"),
    "gpt-5-mini": Price(input_per_million=0.25, output_per_million=2.00, source="openai"),
    "gpt-5-nano": Price(input_per_million=0.05, output_per_million=0.40, source="openai"),
    # Google. https://ai.google.dev/gemini-api/docs/pricing
    # Google's page says "output (including thinking tokens)", which is why the
    # Gemini parser adds thoughtsTokenCount to candidatesTokenCount. The billing
    # definition and the parsing decision have to agree or the total is fiction.
    "gemini-3.6-flash": Price(
        input_per_million=1.50, output_per_million=7.50, source="google"
    ),
    "gemini-3.5-flash": Price(
        input_per_million=1.50, output_per_million=9.00, source="google"
    ),
    "gemini-3.5-flash-lite": Price(
        input_per_million=0.30, output_per_million=2.50, source="google"
    ),
    # Groq. https://groq.com/pricing
    "llama-3.3-70b-versatile": Price(
        input_per_million=0.59, output_per_million=0.79, source="groq"
    ),
    "llama-3.1-8b-instant": Price(
        input_per_million=0.05, output_per_million=0.08, source="groq"
    ),
}


def price_for(model: str, on: date) -> Price | None:
    """The price of a model on a given day, or None if we do not know it."""
    price = PRICES.get(model)
    if price is None or not price.known_on(on):
        return None
    return price


def estimate(model: str, usage: Usage, on: date) -> float | None:
    """What this call cost, or None if the model is not priced.

    Called an estimate rather than a cost because it is arithmetic over a table
    somebody typed, not a figure from an invoice. Until it has been reconciled
    against a real bill it is a good guess, and saying so is cheaper than finding
    out later that it was not.
    """
    price = price_for(model, on)
    return None if price is None else price.of(usage)
