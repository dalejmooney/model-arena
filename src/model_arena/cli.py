"""Smallest possible way to see the stream actually working."""

import sys

from model_arena.anthropic import stream_text


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

    prompt = " ".join(sys.argv[1:]) or "In two sentences, what is a Server-Sent Event?"
    print(f"> {prompt}\n")

    for chunk in stream_text(prompt):
        # end="" because the chunks are fragments of one sentence, not lines.
        # flush=True because stdout buffers when it is not a terminal, and without
        # it the whole point of streaming disappears the moment you pipe the output.
        print(chunk, end="", flush=True)

    print()
