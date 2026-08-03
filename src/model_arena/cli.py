"""One prompt, every model, answers side by side with what each one cost.

Nothing is streamed to the terminal, and that is a deliberate trade. Four streams
interleaved into one terminal is unreadable, so the text is collected and printed
in blocks. The streaming underneath still matters: it is what lets a slow model be
slow without blocking anyone else, and it is what the web view in a later rung will
surface.
"""

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime

from model_arena import storage
from model_arena.arena import Result, price, run_many
from model_arena.pricing import CHECKED, CURRENCY, estimate
from model_arena.providers import PROVIDERS

RULE = "=" * 74


def main() -> None:
    # On Windows, stdout defaults to the system codepage (cp1252 here), which cannot
    # represent arrows, CJK, emoji or most mathematical notation. Printing one raises
    # UnicodeEncodeError and kills the process partway through. Model output is
    # arbitrary text from anywhere, so this is not an edge case, it is Tuesday.
    #
    # Deliberately no errors="replace". That would stop the crash by silently swapping
    # characters for question marks, which turns a loud failure into a quiet corruption.
    # If a terminal genuinely cannot render something, better to hear about it.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="model-arena", description=__doc__)
    parser.add_argument("prompt", nargs="*", default=[])
    parser.add_argument(
        "-m",
        "--model",
        action="append",
        dest="models",
        metavar="PROVIDER[:MODEL]",
        help=(
            f"repeatable. One of {', '.join(sorted(PROVIDERS))}, optionally with a "
            "model id. Defaults to every provider."
        ),
    )
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--history", action="store_true", help="list recent saved runs")
    parser.add_argument("--show", type=int, metavar="ID", help="reprint a saved run")
    parser.add_argument("--no-save", action="store_true", help="do not record this run")
    parser.add_argument("--serve", action="store_true", help="browse saved runs in a browser")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    today = date.today()

    if args.serve:
        from model_arena.web import serve

        print(f"http://127.0.0.1:{args.port}")
        serve(port=args.port)
        return

    if args.history:
        show_history()
        return

    if args.show is not None:
        show_run(args.show, today)
        return

    references = args.models or sorted(PROVIDERS)
    prompt = " ".join(args.prompt) or "In two sentences, what is a Server-Sent Event?"

    print(f"> {prompt}\n")
    started_at = datetime.now(UTC)
    results = asyncio.run(run_many(references, prompt, max_tokens=args.max_tokens))
    report(results, today)

    if not args.no_save:
        record(prompt, args.max_tokens, results, started_at)


def record(prompt: str, max_tokens: int, results: list[Result], started_at: datetime) -> None:
    """Save the run, but never lose it to a failure to save it.

    The answers have already been paid for by the time we get here. Letting a locked
    database or a full disk take them down with it would be a poor trade, so the
    failure is reported and the results stay on screen.
    """
    try:
        run_id = storage.save(prompt, max_tokens, results, started_at)
    except OSError as error:
        print(f"\nnot saved: {error}")
        return
    print(f"saved as run {run_id}")


def money(amount: float) -> str:
    """Six decimal places because a single cheap call rounds to zero at two.

    Showing $0.00 for something that cost money is the same lie as showing $0.00
    for something whose price we do not know, and this program is largely about
    not telling that particular lie.
    """
    return f"${amount:.6f}"


def report(results: list[Result], on: date) -> None:
    for result in results:
        print(f"{RULE}\n{result.label}  ({result.seconds:.1f}s)\n{RULE}")
        if not result.ok:
            print(f"FAILED  {result.error}\n")
            continue
        spend = estimate(result.model, result.usage, on)
        priced = money(spend) if spend is not None else "price unknown"
        print(
            f"in={result.usage.input_tokens} "
            f"out={result.usage.output_tokens}  {priced}\n\n{result.text.strip()}\n"
        )

    summary(results, on)


def summary(results: list[Result], on: date) -> None:
    answered = [result for result in results if result.ok]
    slowest = max((result.seconds for result in results), default=0.0)
    sequential = sum(result.seconds for result in results)
    _, total, unpriced = price(results, on)

    print(RULE)
    print(f"{len(answered)}/{len(results)} answered in {slowest:.1f}s")
    if sequential > 0:
        print(f"one at a time would have taken {sequential:.1f}s")

    print(f"total {money(total)} {CURRENCY}, prices checked {CHECKED}")
    # The total is only the sum of what could be priced, so anything left out has
    # to be named. A total that silently omits a row is a wrong total, and the
    # reader has no way to tell from the number itself.
    if unpriced:
        print(f"excludes {len(unpriced)} unpriced: {', '.join(unpriced)}")


def show_history() -> None:
    runs = storage.recent()
    if not runs:
        print("no runs saved yet")
        return
    for run in runs:
        when = run.started_at.strftime("%Y-%m-%d %H:%M")
        prompt = run.prompt if len(run.prompt) <= 56 else run.prompt[:53] + "..."
        print(f"{run.id:>5}  {when}  {prompt}")


def show_run(run_id: int, on: date) -> None:
    run = storage.load(run_id)
    if run is None:
        print(f"no run {run_id}")
        return
    # Repriced at today's rates rather than whatever was shown on the day, which is
    # the entire reason usage is stored and cost is not. If a price has moved since,
    # this total moves with it instead of preserving a figure that stopped being true.
    print(f"run {run.id}  {run.started_at.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"> {run.prompt}\n")
    report(run.results, on)
