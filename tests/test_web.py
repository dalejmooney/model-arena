"""Tests for the web view.

The important one is the escaping test. Everything rendered on these pages came out
of a language model, so it is arbitrary text from a system that will happily produce
a script tag if the conversation goes that way. That is not a hypothetical: "write
me some HTML" is a completely normal prompt, and its answer ends up on this page.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from model_arena import storage, web
from model_arena.arena import Result
from model_arena.events import Usage

WHEN = datetime(2026, 8, 3, 19, 30, tzinfo=UTC)

CHEAP = Result(
    provider="groq",
    model="llama-3.3-70b-versatile",
    text="Blue.",
    usage=Usage(input_tokens=46, output_tokens=50),
    seconds=1.0,
)
DEAR = Result(
    provider="gemini",
    model="gemini-3.6-flash",
    text="Blue.",
    usage=Usage(input_tokens=11, output_tokens=452),
    seconds=4.7,
)
UNPRICED = Result(
    provider="gemini",
    model="gemini-3.1-flash-lite",
    text="Blue.",
    usage=Usage(input_tokens=3, output_tokens=9),
    seconds=0.6,
)
BROKEN = Result(provider="openai", model="gpt-5", seconds=1.2, error="404 from openai")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(web, "DB", tmp_path / "runs.db")
    return TestClient(web.app)


def save(path: Path, results: list[Result], prompt: str = "name a colour") -> int:
    return storage.save(prompt, 512, results, WHEN, path=path)


def test_an_empty_database_says_so_rather_than_erroring(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "no runs yet" in response.text


def test_the_index_lists_saved_runs(client: TestClient) -> None:
    save(web.DB, [CHEAP, DEAR], prompt="why is the sky blue")
    response = client.get("/")
    assert "why is the sky blue" in response.text
    assert "/runs/1" in response.text


def test_a_run_page_shows_every_model(client: TestClient) -> None:
    run_id = save(web.DB, [CHEAP, DEAR])
    body = client.get(f"/runs/{run_id}").text
    assert "groq:llama-3.3-70b-versatile" in body
    assert "gemini:gemini-3.6-flash" in body
    assert "in 452" not in body  # tokens are labelled out, not in
    assert "out 452" in body


def test_a_missing_run_is_a_404_not_a_crash(client: TestClient) -> None:
    response = client.get("/runs/999")
    assert response.status_code == 404
    assert "no run 999" in response.text


def test_an_unknown_price_says_so_on_the_page_too(client: TestClient) -> None:
    """The rule has to hold on every surface, not just in the terminal."""
    run_id = save(web.DB, [CHEAP, UNPRICED])
    body = client.get(f"/runs/{run_id}").text
    assert "price unknown" in body
    assert "excludes 1 unpriced" in body
    assert "gemini:gemini-3.1-flash-lite" in body


def test_a_failed_provider_is_shown_as_failed(client: TestClient) -> None:
    run_id = save(web.DB, [CHEAP, BROKEN])
    body = client.get(f"/runs/{run_id}").text
    assert "FAILED" in body
    assert "404 from openai" in body


def test_model_output_cannot_inject_script(client: TestClient) -> None:
    """The one that would actually hurt.

    "Write me a hello world web page" is an ordinary prompt, and its answer contains
    real tags. Rendered unescaped, a model would be scripting the page that displays
    it, and the person who typed the prompt would be the one running it.
    """
    nasty = Result(
        provider="openai",
        model="gpt-5",
        text="<script>alert('xss')</script><img src=x onerror=alert(1)>",
        usage=Usage(input_tokens=1, output_tokens=1),
        seconds=0.1,
    )
    run_id = save(web.DB, [nasty], prompt="<script>alert('prompt')</script>")
    body = client.get(f"/runs/{run_id}").text

    # The property that matters is that no live element or attribute reaches the
    # document, not that the characters are absent. Escaped, the same text is
    # visible to the reader and inert to the browser, which is exactly the goal.
    assert "<script>alert" not in body
    assert "<img" not in body
    assert "&lt;script&gt;alert" in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body

    # And the same text on the index page, which renders the prompt separately.
    assert "<script>alert('prompt')</script>" not in client.get("/").text


def test_a_provider_name_cannot_break_out_of_the_style_attribute(client: TestClient) -> None:
    """Colours are interpolated into inline styles, so that path needs escaping too."""
    odd = Result(
        provider="'; alert(1); '",
        model="x",
        text="hi",
        usage=Usage(output_tokens=1),
        seconds=0.1,
    )
    run_id = save(web.DB, [odd])
    body = client.get(f"/runs/{run_id}").text
    assert "alert(1)" not in body or "&#x27;" in body


def test_the_dearest_answer_sets_the_bar_width(client: TestClient) -> None:
    """The bar is what makes a fiftyfold spread legible without reading digits."""
    run_id = save(web.DB, [CHEAP, DEAR])
    body = client.get(f"/runs/{run_id}").text
    assert "width:100.0%" in body
