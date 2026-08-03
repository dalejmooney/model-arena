"""Tests for turning token counts into money.

The arithmetic is trivial and barely worth testing. What is worth testing is every
path where the answer is "I do not know", because those are the ones that fail by
producing a plausible number instead of an error.
"""

from datetime import date

import pytest

from model_arena.events import Usage
from model_arena.pricing import PRICES, Price, cost, estimate, price_for

TODAY = date(2026, 8, 3)


def test_cost_of_a_million_tokens_is_the_quoted_rate() -> None:
    assert cost(1_000_000, 0.14) == 0.14


def test_cost_is_zero_when_nothing_was_used() -> None:
    assert cost(0, 0.14) == 0.0


def test_a_call_is_priced_from_both_halves() -> None:
    """gpt-5 at 1.25 in and 10.00 out."""
    spend = estimate("gpt-5", Usage(input_tokens=1_000_000, output_tokens=1_000_000), TODAY)
    assert spend == pytest.approx(11.25)


def test_an_unpriced_model_is_unknown_and_never_zero() -> None:
    """The whole point of the module.

    A model missing from the table has to be distinguishable from one that cost
    nothing, because a comparison table showing 0.00 for the row nobody priced is
    the same confident-and-wrong failure this project keeps finding.
    """
    assert estimate("some-model-shipped-tomorrow", Usage(output_tokens=500), TODAY) is None


def test_a_promotional_price_lapses_into_unknown_rather_than_staying_wrong() -> None:
    """Claude Sonnet 5's introductory rate ends on 31 August 2026.

    After that the figure in the table is not the price any more. Reporting it
    anyway would be a stale number that looks exactly like a fresh one.
    """
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert estimate("claude-sonnet-5", usage, date(2026, 8, 31)) == pytest.approx(12.00)
    assert estimate("claude-sonnet-5", usage, date(2026, 9, 1)) is None


def test_a_price_with_no_expiry_is_known_on_any_day() -> None:
    assert price_for("gpt-5", date(2030, 1, 1)) is not None


def test_zero_usage_costs_zero_when_the_model_is_priced() -> None:
    """Genuinely free and unknown must not collapse into the same output."""
    assert estimate("gpt-5", Usage(), TODAY) == 0.0


@pytest.mark.parametrize("model", sorted(PRICES))
def test_every_price_names_where_it_came_from(model: str) -> None:
    """A rate with no provenance cannot be rechecked, so it rots in place."""
    assert PRICES[model].source


@pytest.mark.parametrize("model", sorted(PRICES))
def test_output_is_never_cheaper_than_input(model: str) -> None:
    """True of every provider we have met, so a violation means a typo.

    Cheap guard against transposing the two columns while copying a pricing page,
    which produces a table that looks entirely reasonable and is wrong everywhere.
    """
    price = PRICES[model]
    assert price.output_per_million >= price.input_per_million


def test_defaults_of_all_four_providers_are_priced() -> None:
    """If a default model is unpriced, the tool ships showing unknown out of the box."""
    from model_arena.providers import PROVIDERS

    for provider in PROVIDERS.values():
        assert price_for(provider.default_model, TODAY) is not None, provider.name


def test_known_on_is_inclusive_of_the_expiry_day() -> None:
    price = Price(
        input_per_million=1.0,
        output_per_million=1.0,
        source="test",
        expires=date(2026, 8, 31),
    )
    assert price.known_on(date(2026, 8, 31))
    assert not price.known_on(date(2026, 9, 1))
