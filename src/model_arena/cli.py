"""One prompt, every model, answers side by side.

Nothing is streamed to the terminal any more, and that is a deliberate trade. Four
streams interleaved into one terminal is unreadable, so the text is collected and
printed in blocks. The streaming underneath still matters: it is what lets a slow
model be slow without blocking anyone else, and it is what the web view in a later
rung will actually surface.
"""

import argparse
import asyncio
import sys

from model_arena.arena import Result, run_many
from model_arena.providers import PROVIDERS


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
    report(results)


def report(results: list[Result]) -> None:
    for result in results:
        print(f"{'=' * 70}\n{result.label}  ({result.seconds:.1f}s)\n{'=' * 70}")
        if result.ok:
            tokens = f"in={result.usage.input_tokens} out={result.usage.output_tokens}"
            print(f"{tokens}\n\n{result.text.strip()}\n")
        else:
            print(f"FAILED  {result.error}\n")

    answered = [result for result in results if result.ok]
    slowest = max((result.seconds for result in results), default=0.0)
    total = sum(result.seconds for result in results)

    print("=" * 70)
    print(f"{len(answered)}/{len(results)} answered in {slowest:.1f}s")
    # The saving is the entire point of the rung, so it gets printed every run.
    if total > 0:
        print(f"one at a time would have taken {total:.1f}s")
