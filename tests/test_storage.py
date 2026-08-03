"""Tests for keeping runs.

Every one of these uses a temporary database, so they never touch the real one in
the home directory. The interesting assertions are not "does a row come back", they
are about what the schema deliberately refuses to store.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from model_arena import storage
from model_arena.arena import Result
from model_arena.events import Usage

WHEN = datetime(2026, 8, 3, 19, 30, tzinfo=UTC)

ANSWERED = [
    Result(
        provider="groq",
        model="llama-3.3-70b-versatile",
        text="Blue.",
        usage=Usage(input_tokens=46, output_tokens=50),
        seconds=1.0,
    ),
    Result(
        provider="gemini",
        model="gemini-3.6-flash",
        text="Blue.",
        usage=Usage(input_tokens=11, output_tokens=452),
        seconds=4.7,
    ),
]

FAILED = Result(
    provider="openai",
    model="gpt-5",
    seconds=1.2,
    error="HTTPStatusError: 404 from openai",
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "runs.db"


def test_a_run_comes_back_with_everything_it_went_in_with(db: Path) -> None:
    run_id = storage.save("name a colour", 512, ANSWERED, WHEN, path=db)
    run = storage.load(run_id, path=db)

    assert run is not None
    assert run.prompt == "name a colour"
    assert run.max_tokens == 512
    assert run.started_at == WHEN
    assert [result.model for result in run.results] == [
        "llama-3.3-70b-versatile",
        "gemini-3.6-flash",
    ]
    assert run.results[1].usage == Usage(input_tokens=11, output_tokens=452)


def test_results_keep_the_order_they_were_asked_in(db: Path) -> None:
    """Same rule as the live run. Ordering by speed would rewrite the table."""
    run_id = storage.save("hi", 64, ANSWERED, WHEN, path=db)
    run = storage.load(run_id, path=db)
    assert run is not None
    assert [result.provider for result in run.results] == ["groq", "gemini"]


def test_a_failed_provider_is_saved_rather_than_dropped(db: Path) -> None:
    """"Groq was down on Tuesday" is a fact about Groq.

    Storing only the successes would quietly rewrite history into one where
    everything always worked, which is the least useful history to keep.
    """
    run_id = storage.save("hi", 64, [*ANSWERED, FAILED], WHEN, path=db)
    run = storage.load(run_id, path=db)

    assert run is not None
    failed = [result for result in run.results if not result.ok]
    assert len(failed) == 1
    assert failed[0].error is not None
    assert "404" in failed[0].error


def test_the_schema_stores_no_cost(db: Path) -> None:
    """The design decision of this rung, asserted rather than just commented.

    Prices move. Claude Sonnet 5's rate is already scheduled to change on 31 August.
    A stored cost silently becomes a figure that was true once, with nothing marking
    which rows are stale. Stored tokens can always be repriced.
    """
    storage.save("hi", 64, ANSWERED, WHEN, path=db)
    with storage.connect(db) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(result)")}

    assert "input_tokens" in columns
    assert "output_tokens" in columns
    assert not {column for column in columns if "cost" in column or "price" in column}


def test_recent_is_newest_first(db: Path) -> None:
    for index in range(3):
        storage.save(f"prompt {index}", 64, ANSWERED, WHEN, path=db)

    assert [run.prompt for run in storage.recent(path=db)] == [
        "prompt 2",
        "prompt 1",
        "prompt 0",
    ]


def test_recent_respects_its_limit(db: Path) -> None:
    for index in range(5):
        storage.save(f"prompt {index}", 64, ANSWERED, WHEN, path=db)
    assert len(storage.recent(limit=2, path=db)) == 2


def test_history_follows_one_model_across_runs(db: Path) -> None:
    """Why runs are kept at all: watching a model over time is how drift shows up."""
    for _ in range(3):
        storage.save("same prompt", 64, ANSWERED, WHEN, path=db)

    seen = storage.history("gemini-3.6-flash", path=db)
    assert len(seen) == 3
    assert all(result.model == "gemini-3.6-flash" for _, result in seen)
    assert all(run.prompt == "same prompt" for run, _ in seen)


def test_loading_a_run_that_does_not_exist_is_none_not_an_error(db: Path) -> None:
    assert storage.load(999, path=db) is None


def test_the_database_is_created_on_first_use(tmp_path: Path) -> None:
    """Including the directory, so a fresh machine does not need setup."""
    nested = tmp_path / "does" / "not" / "exist" / "runs.db"
    storage.save("hi", 64, ANSWERED, WHEN, path=nested)
    assert nested.exists()
