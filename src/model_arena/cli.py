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
from datetime import date

from model_arena.arena import Result, run_many
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
    args = parser.parse_args()

    references = args.models or sorted(PROVIDERS)
    prompt = " ".join(args.prompt) or "In two sentences, what is a Server-Sent Event?"

    print(f"> {prompt}\n")
    results = asyncio.run(run_many(references, prompt, max_tokens=args.max_tokens))
    report(results, date.today())


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

    spends = {result.label: estimate(result.model, result.usage, on) for result in answered}
    unpriced = sorted(label for label, spend in spends.items() if spend is None)
    total = sum(spend for spend in spends.values() if spend is not None)

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
