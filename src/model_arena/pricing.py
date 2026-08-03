"""Token cost arithmetic.

Deliberately the first real module: every model in the arena reports usage in
tokens, and comparing models on quality without comparing them on cost is how
you end up recommending something nobody can afford to run.
"""


def cost(tokens: int, per_million: float) -> float:
    """Cost of `tokens` at a price quoted per million tokens.

    Providers all quote per-million rates, so doing the division here once means
    no call site has to remember how many zeroes are in a million.
    """
    return tokens / 1_000_000 * per_million
