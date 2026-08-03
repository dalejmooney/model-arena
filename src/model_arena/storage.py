"""Keeping every run, so a claim about last week can be checked rather than recalled.

SQLite because it is in the standard library, it is one file, and the web view in a
later rung wants something it can query rather than a directory of JSON.

The one decision that matters here: **usage is stored, cost is not.** Tokens are what
the provider reported and they never change. A price is a number off a web page that
somebody else edits, and Claude Sonnet 5's rate is already scheduled to move on 31
August. Store the money and last month's history quietly becomes a set of figures that
were true once, with nothing marking which ones. Store the tokens and any run can be
repriced correctly, at today's rates or at the rates of the day it ran.

That is the same rule as everywhere else in this project. Keep the measurement, derive
the valuation, and never let a derived number harden into a fact.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from model_arena.arena import Result
from model_arena.events import Usage

DEFAULT_DB = Path.home() / ".model-arena" / "runs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT    NOT NULL,
    prompt      TEXT    NOT NULL,
    max_tokens  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS result (
    id            INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES run(id) ON DELETE CASCADE,
    provider      TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    text          TEXT    NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    seconds       REAL    NOT NULL,
    error         TEXT
    -- Deliberately no cost column. See the module docstring.
);

CREATE INDEX IF NOT EXISTS result_run ON result(run_id);
CREATE INDEX IF NOT EXISTS result_model ON result(model);
"""


@dataclass(frozen=True)
class Run:
    """One prompt, asked once, of everything that was asked."""

    id: int
    started_at: datetime
    prompt: str
    max_tokens: int
    results: list[Result]


@contextmanager
def connect(path: Path = DEFAULT_DB) -> Iterator[sqlite3.Connection]:
    """Open the database, creating the file and the schema if this is the first run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        # SQLite has foreign keys but leaves them off by default, per connection.
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        yield connection


def save(
    prompt: str,
    max_tokens: int,
    results: list[Result],
    started_at: datetime,
    path: Path = DEFAULT_DB,
) -> int:
    """Record one run and everything it produced. Returns the run id."""
    with connect(path) as connection:
        cursor = connection.execute(
            "INSERT INTO run (started_at, prompt, max_tokens) VALUES (?, ?, ?)",
            (started_at.isoformat(), prompt, max_tokens),
        )
        run_id = int(cursor.lastrowid or 0)
        connection.executemany(
            "INSERT INTO result"
            " (run_id, provider, model, text, input_tokens, output_tokens, seconds, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    result.provider,
                    result.model,
                    result.text,
                    result.usage.input_tokens,
                    result.usage.output_tokens,
                    result.seconds,
                    result.error,
                )
                # A failed provider is saved too. "Groq was down on Tuesday" is a
                # fact about Groq, and dropping it would quietly rewrite history
                # into one where everything always worked.
                for result in results
            ],
        )
        connection.commit()
        return run_id


def _result(row: sqlite3.Row) -> Result:
    return Result(
        provider=row["provider"],
        model=row["model"],
        text=row["text"],
        usage=Usage(input_tokens=row["input_tokens"], output_tokens=row["output_tokens"]),
        seconds=row["seconds"],
        error=row["error"],
    )


def recent(limit: int = 20, path: Path = DEFAULT_DB) -> list[Run]:
    """The most recent runs, newest first, without their results loaded."""
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT id, started_at, prompt, max_tokens FROM run ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            Run(
                id=row["id"],
                started_at=datetime.fromisoformat(row["started_at"]),
                prompt=row["prompt"],
                max_tokens=row["max_tokens"],
                results=[],
            )
            for row in rows
        ]


def load(run_id: int, path: Path = DEFAULT_DB) -> Run | None:
    """One run with its results, in the order they were asked."""
    with connect(path) as connection:
        row = connection.execute(
            "SELECT id, started_at, prompt, max_tokens FROM run WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        results = connection.execute(
            "SELECT * FROM result WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return Run(
            id=row["id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            prompt=row["prompt"],
            max_tokens=row["max_tokens"],
            results=[_result(result) for result in results],
        )


def history(model: str, limit: int = 50, path: Path = DEFAULT_DB) -> list[tuple[Run, Result]]:
    """Every time one model answered, newest first.

    The point of keeping runs at all: watching one model across the same prompt over
    time is how you notice a provider changed something underneath you.
    """
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT r.*, u.started_at, u.prompt, u.max_tokens"
            " FROM result r JOIN run u ON u.id = r.run_id"
            " WHERE r.model = ? ORDER BY r.id DESC LIMIT ?",
            (model, limit),
        ).fetchall()
        return [
            (
                Run(
                    id=row["run_id"],
                    started_at=datetime.fromisoformat(row["started_at"]),
                    prompt=row["prompt"],
                    max_tokens=row["max_tokens"],
                    results=[],
                ),
                _result(row),
            )
            for row in rows
        ]
