"""Smallest possible way to see one provider's stream actually working.

Still one model at a time. Running four at once is the next step and wants asyncio,
which is a different problem from talking to four APIs correctly.
"""

import argparse
import sys

from model_arena.providers import PROVIDERS, resolve, stream_events


def main() -> None:
    # On Windows, stdout defaults to the system codepage (cp1252 here), which cannot
    # represent arrows, CJK, emoji or most mathematical notation. Printing one raises
    # UnicodeEncodeError and kills the process partway through the stream. Model output
    # is arbitrary text from anywhere, so this is not an edge case, it is Tuesday.
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
        default="anthropic",
        metavar="PROVIDER[:MODEL]",
        help=f"one of {', '.join(sorted(PROVIDERS))}, optionally with a model id",
    )
    args = parser.parse_args()

    provider, model = resolve(args.model)
    prompt = " ".join(args.prompt) or "In two sentences, what is a Server-Sent Event?"
    print(f"[{provider.name} {model}]\n> {prompt}\n")

    for chunk in stream_events(provider, prompt, model):
        if isinstance(chunk, str):
            # end="" because the chunks are fragments of one sentence, not lines.
            # flush=True because stdout buffers when it is not a terminal, and without
            # it the whole point of streaming disappears the moment you pipe the output.
            print(chunk, end="", flush=True)

    print()
