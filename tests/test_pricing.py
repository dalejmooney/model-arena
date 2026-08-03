from model_arena.pricing import cost


def test_cost_of_a_million_tokens_is_the_quoted_rate() -> None:
    assert cost(1_000_000, 0.14) == 0.14


def test_cost_is_zero_when_nothing_was_used() -> None:
    assert cost(0, 0.14) == 0.0
