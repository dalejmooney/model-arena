# Model Arena

Run the same prompt across every model and compare the answers side by side, with what each one cost.

Picking a model from a leaderboard tells you how it performs on somebody else's task. This runs your prompt, on the models you actually have access to, and puts the answers next to each other along with tokens and cost.

## Status

Early. Four providers stream behind one interface. Built in the open as I go.

## What it does so far

- Anthropic, OpenAI, Gemini and Groq, all through one `Provider` interface
- Asks them all at once, so adding a model costs no extra wall-clock time
- Streams over raw HTTP rather than four vendor SDKs
- Normalised token counts, whichever of the four ways a provider reports them
- Cost per call, with an unknown price reported as unknown rather than as zero
- Every run saved to SQLite, storing tokens rather than money so history can be repriced
- A web view of past runs, repriced at today's rates every time you load it
- One provider failing is a row in the table, not the end of the run

## What it will do

- Ship free on the site

## Providers

```bash
model-arena "why is the sky blue?"                        # all four at once
model-arena --model anthropic --model groq "why is..."    # pick a subset
model-arena --model openai:gpt-5 "why is the sky blue?"   # pin a model
```

`--model` takes `provider` or `provider:model`. A bare provider name uses its
default model, so trying a new one does not mean looking up its current model ids
first. Each provider reads its own key from the environment:

| Provider | Key |
|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` |
| `gemini` | `GEMINI_API_KEY` |
| `groq` | `GROQ_API_KEY` |

### What differs between them

Adding the second, third and fourth was the point of the exercise. The transport
turned out to be the same every time, so `providers/base.py` does it once and a
provider supplies only three things: where to send it, what the body looks like,
and how to read a chunk.

What actually differs is worth writing down:

- **Anthropic** names its stream events, so a `content_block_delta` without text is
  broken and should raise. It also reports input and output tokens at opposite ends
  of the stream, so neither event alone tells you what a call cost.
- **OpenAI** sends one chunk shape with everything optional, so a delta without
  content is normal rather than broken, and the opposite validation rule applies.
  Token counts are opt-in: without `stream_options`, a stream reports nothing and
  the call silently costs an unknown amount. `max_tokens` is also deprecated in
  favour of `max_completion_tokens`, and covers hidden reasoning as well as the
  answer, so a small budget can return no visible text at all.
- **Groq** is the OpenAI API on other hardware, which is the finding in itself:
  most apparent provider diversity is one wire format with local dialects. Its
  dialect is putting token counts in an `x_groq` envelope, so an OpenAI-only client
  streams from Groq happily and never learns what anything cost.
- **Gemini** shares almost no assumptions. The model goes in the URL, the response
  is only Server-Sent Events because `?alt=sse` asks for it, text is nested two
  lists deep, usage is a running total repeated on every chunk rather than reported
  once, and thinking models bill reasoning as output while leaving it out of the
  obvious field.

That last one drove a design decision. Summing usage as it arrives is right for
Anthropic and OpenAI and would triple-count Gemini, so the merge rule is "take the
newest value" and lives in `events.py` rather than in any one provider.

### Hidden reasoning makes cheap-looking answers expensive

All four were asked to name one colour in one word. All four answered "Blue". The
output token counts were not close:

| Provider | Model | In | Out |
|---|---|---:|---:|
| anthropic | claude-sonnet-5 | 15 | 5 |
| openai | gpt-5 | 13 | 74 |
| gemini | gemini-3.6-flash | 7 | 127 |
| groq | llama-3.3-70b-versatile | 42 | 2 |

Same four-letter answer, twenty-five times the output cost between the cheapest and
the dearest, entirely because of reasoning nobody asked for and nobody sees.

Gemini reports that split, and reporting it is the trap. One call came back with
`candidatesTokenCount: 1` and `thoughtsTokenCount: 168`. A cost tracker reading the
obvious field would have recorded one output token for a call billed at a hundred
and sixty nine, and nothing in the response would have looked wrong. So the reading
is deliberately `candidates + thoughts`, and there is a test pinning it to those
real numbers.

The general point, which is why this project exists: a per-token price is not a
price. What a model actually costs depends on how much it thinks before answering,
that varies per call, and at least two of these four will quietly not tell you.

It gets worse with a real question. Asked to explain Server-Sent Events in one
sentence, every model produced roughly thirty words, and Gemini spent **476 output
tokens** getting there against Groq's 57. The answers were about equally good.

### Asking them all at once

Waiting is almost all of what this program does, so the waiting overlaps:

```
4/4 answered in 5.1s
one at a time would have taken 14.4s
```

That is the honest case for asyncio here rather than threads: there is no CPU work
to speak of, just four sockets idle most of the time. Only the transport is async.
`request()` and `parse()` stay ordinary functions because neither waits for
anything, and the useful discipline of async is being able to point at every place
that actually blocks.

Two behaviours are pinned by tests because they are easy to get wrong and hard to
notice:

- **A failed provider is a result, not an exception.** If Groq is down that belongs
  in the table next to the models that answered. Letting it propagate would cancel
  three calls that were working, and a comparison tool that shows nothing whenever
  one competitor has a bad day is not much of a comparison tool.
- **Results come back in the order asked for**, not the order they finished, or the
  fast models quietly sort themselves to the top of every run and the table becomes
  a leaderboard for the one axis that is easiest to measure.

The concurrency claim is measured, not assumed: `tests/test_arena.py` uses
`httpx.MockTransport` to build a fake network with per-provider delays, so it can
prove the calls really do overlap without ever leaving the machine.

### Putting a price on it

The same one-sentence question, asked of all four:

| Provider | Model | In | Out | Cost |
|---|---|---:|---:|---:|
| groq | llama-3.3-70b-versatile | 46 | 50 | $0.000067 |
| anthropic | claude-sonnet-5 | 21 | 55 | $0.000592 |
| openai | gpt-5 | 17 | 107 | $0.001091 |
| gemini | gemini-3.6-flash | 11 | 452 | $0.003406 |

**Fifty-one times the price for the same sentence.** Four equally good answers,
and the spread is almost entirely reasoning you pay for and never see. Google's
pricing page is explicit that output is billed "including thinking tokens", which
is why the Gemini parser adds `thoughtsTokenCount` to `candidatesTokenCount`. The
billing definition and the parsing decision have to agree or the total is fiction.

**An unknown price is never zero.** A model missing from the table reports `price
unknown`, and the run total names what it left out:

```
total $0.000287 USD, prices checked 2026-08-03
excludes 1 unpriced: gemini:gemini-3.1-flash-lite
```

A comparison table that quietly shows $0.00 for the one model nobody priced is
worse than one that shows nothing, because the reader cannot tell from the number
that anything is missing. Same failure as the token bug, one layer up.

Promotional rates get the same treatment. Claude Sonnet 5's introductory price
ends on 31 August 2026, so the entry carries that date and **lapses into unknown
rather than staying wrong**. A stale price is indistinguishable from a current one
at the moment you read the total, which is exactly too late.

Two honesty notes. The function is called `estimate`, not `cost`, because it is
arithmetic over a table somebody typed rather than a figure from an invoice.
Nothing here has been reconciled against a real bill yet. And money is printed to
six decimal places, because at two a real call rounds to $0.00, which is the same
lie in different clothing.

### Keeping runs

Every run is saved to SQLite at `~/.model-arena/runs.db`.

```bash
model-arena --history      # recent runs
model-arena --show 12      # reprint one, repriced at today's rates
model-arena --no-save ...  # don't record this one
```

**The schema stores tokens and deliberately has no cost column**, and there is a
test asserting that rather than just a comment. Tokens are what the provider
reported and they never change. A price is a number off a web page somebody else
edits, and Sonnet 5's rate is already scheduled to move on 31 August. Store the
money and last month's history quietly becomes a set of figures that were true
once, with nothing marking which. Store the tokens and any run can be repriced,
which is exactly what `--show` does.

Same rule as everywhere else here: keep the measurement, derive the valuation, and
never let a derived number harden into a fact.

Failed providers are saved too. "Groq was down on Tuesday" is a fact about Groq,
and keeping only the successes rewrites history into one where everything always
worked, which is the least useful history to have.

### Looking at it

```bash
model-arena --serve        # http://127.0.0.1:8000
```

FastAPI, read only, bound to localhost because it is somebody's own history. The
terminal runs comparisons; this reads what they produced. A "run it now" button
would mean holding four streams open across a request, which is a different problem
from displaying a result.

Each answer gets a bar sized against the dearest one in the run, which is what makes
a fiftyfold spread legible at a glance rather than something you work out from
digits. Pages are priced at request time from stored tokens, so they move when
prices move. That is the whole reason the database has no cost column.

**Everything on those pages came out of a language model**, so escaping is the main
thing `render.py` does. "Write me a hello world page" is an ordinary prompt and its
answer contains real tags; rendered raw, a model would be scripting the page that
displays it, and the person who typed the prompt would be the one running it. The
HTML is hand written rather than templated specifically to keep that in plain sight
instead of trusting a template engine's autoescaping to be switched on, and there is
a test that feeds a script tag through a model answer and checks it comes back
inert.

## Running it

Requires [uv](https://docs.astral.sh/uv/). It handles the Python version, the virtual environment and the dependencies.

```bash
uv sync                # create the environment from the lockfile
uv run pytest          # tests
uv run ruff check .    # lint
uv run mypy            # type check
```

## Layout

```
src/model_arena/            the package
src/model_arena/providers/  one module per provider, plus the shared transport
tests/                      tests
pyproject.toml              project metadata and all tool config
uv.lock                     exact resolved dependency versions
```

`src/` layout is deliberate: it means the tests import the installed package rather than the
directory sitting next to them, so a file missing from the build fails here instead of failing
for whoever installs it.

## Licence

MIT
