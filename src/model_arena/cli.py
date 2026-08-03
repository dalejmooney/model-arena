"""Smallest possible way to see the stream actually working."""

import sys

from model_arena.anthropic import stream_text


def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "In two sentences, what is a Server-Sent Event?"
    print(f"> {prompt}\n")

    for chunk in stream_text(prompt):
        # end="" because the chunks are fragments of one sentence, not lines.
        # flush=True because stdout buffers when it is not a terminal, and without
        # it the whole point of streaming disappears the moment you pipe the output.
        print(chunk, end="", flush=True)

    print()
