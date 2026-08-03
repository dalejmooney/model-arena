"""Running the same prompt against every model at once.

This is the whole reason the project is called an arena. Asked one at a time, four
models cost the sum of four calls; asked together they cost the slowest one, and
since almost all of that time is spent waiting on somebody else's server rather
than doing anything, the waiting may as well overlap.

That is also the honest case for asyncio here. There is no CPU work to speak of,
just four sockets that are idle most of the time, which is exactly the shape of
problem async is for and exactly the shape threads would be heavier at.

Two decisions worth keeping:

  A failed model is a result, not an exception. If Groq is down, that is a fact
  about Groq worth showing in the table next to the models that answered. Letting
  it propagate would cancel the three calls that were working perfectly well, and
  a comparison tool that shows nothing whenever one competitor is having a bad day
  is not much of a comparison tool.

  Results come back in the order asked for, not the order they finished. The fast
  models would otherwise sort themselves to the top every run, which quietly turns
  a table you are trying to read into a leaderboard for the one axis that is
  easiest to measure.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import date

import httpx

from model_arena.events import Usage
from model_arena.pricing import estimate
from model_arena.providers import Provider, collect, resolve
from model_arena.providers.base import DEFAULT_MAX_TOKENS, DEFAULT_TIMEOUT


@dataclass(frozen=True)
class Result:
    """One model's answer, or its excuse."""

    provider: str
    model: str
    text: str = ""
    usage: Usage = field(default_factory=Usage)
    seconds: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class Priced:
    """A result and what it cost, where `spend` of None means the price is unknown."""

    result: Result
    spend: float | None


def price(results: list[Result], on: date) -> tuple[list[Priced], float, list[str]]:
    """Value a set of results, returning the rows, the total, and what was left out.

    Shared by the terminal and the web view rather than written twice, because the
    rule that an unknown price is never zero is only useful if every surface obeys
    it. Two implementations is one implementation and one future bug.
    """
    rows = [
        Priced(result, estimate(result.model, result.usage, on) if result.ok else None)
        for result in results
    ]
    total = sum(row.spend for row in rows if row.spend is not None)
    unpriced = sorted(row.result.label for row in rows if row.result.ok and row.spend is None)
    return rows, total, unpriced


async def run_one(
    provider: Provider,
    model: str,
    prompt: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Result:
    """Ask one model, and come back with a Result either way."""
    started = time.perf_counter()
    try:
        text, usage = await collect(provider, prompt, model, max_tokens, timeout, transport)
    except Exception as error:
        # Deliberately broad. Anything at all that goes wrong with one provider is
        # that provider's result, not the end of the run. The type name is kept
        # because "ReadTimeout" and "HTTPStatusError" mean very different things
        # when you are deciding whether to trust the rest of the table.
        return Result(
            provider=provider.name,
            model=model,
            seconds=time.perf_counter() - started,
            error=f"{type(error).__name__}: {error}",
        )
    return Result(
        provider=provider.name,
        model=model,
        text=text,
        usage=usage,
        seconds=time.perf_counter() - started,
    )


async def run_many(
    references: list[str],
    prompt: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[Result]:
    """Ask every model at once. Wall clock is the slowest one, not the sum."""
    # Resolved up front and outside the TaskGroup, so a typo in a provider name
    # fails immediately and loudly rather than turning into one odd row.
    targets = [resolve(reference) for reference in references]

    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(run_one(provider, model, prompt, max_tokens, timeout, transport))
            for provider, model in targets
        ]

    return [task.result() for task in tasks]
