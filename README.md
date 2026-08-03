# Model Arena

Run one prompt across every model at once and compare the answers side by side, with
what each one actually cost.

Picking a model from a leaderboard tells you how it performs on somebody else's task.
This runs *your* prompt, on the models you have access to, and puts the answers next
to each other with tokens, timing and real money.

```
==========================================================================
groq:llama-3.3-70b-versatile  (1.0s)
==========================================================================
in=46 out=50  $0.000067

An API rate limit is a restriction on the number of requests that can be made...

==========================================================================
gemini:gemini-3.6-flash  (3.8s)
==========================================================================
in=11 out=452  $0.003406

An API rate limit is a restriction set by a service that caps the maximum...

==========================================================================
4/4 answered in 7.6s
one at a time would have taken 16.3s
total $0.005156 USD, prices checked 2026-08-03
```

Same sentence, fifty-one times the price. **[What I found building this →](FINDINGS.md)**

## Install

Requires [uv](https://docs.astral.sh/uv/), which handles the Python version, the
virtual environment and the dependencies.

```bash
git clone https://github.com/dalejmooney/model-arena
cd model-arena
uv sync
```

Then put whichever keys you have in a `.env` file in the project root. You do not
need all four; anything unset simply cannot be asked.

```
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
GEMINI_API_KEY=...
GROQ_API_KEY=...
```

| Provider | Key | Default model |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-5` |
| `openai` | `OPENAI_API_KEY` | `gpt-5` |
| `gemini` | `GEMINI_API_KEY` | `gemini-3.6-flash` |
| `groq` | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |

`.env` is gitignored. Nothing is sent anywhere except to the providers themselves.

## Use

```bash
model-arena "why is the sky blue?"                       # every provider at once
model-arena -m anthropic -m groq "why is the sky blue?"  # pick a subset
model-arena -m openai:gpt-5-mini "why is the sky blue?"  # pin a model
model-arena --max-tokens 2048 "write me a haiku"
```

`--model` takes `provider` or `provider:model`. A bare provider name uses its default,
so trying a new one does not mean looking up its current model ids first. **There is
no built-in model catalogue** — model ids date within weeks and the whole point is to
try things newer than this tool, so a model is just a string handed to the provider.

Every run is saved to SQLite at `~/.model-arena/runs.db`:

```bash
model-arena --history      # recent runs
model-arena --show 12      # reprint one, repriced at today's rates
model-arena --no-save ...  # don't record this one
model-arena --serve        # browse them at http://127.0.0.1:8000
```

The web view is read only and bound to localhost, because it is your own history.

## A note on prices

Prices are read off each provider's own pricing page by hand, carry the date they were
checked, and name their source. **A model that is not in the table reports `price
unknown` rather than $0.00**, and the run total says what it excluded.

The function is called `estimate`, not `cost`, because it is arithmetic over a typed
table rather than a figure from an invoice. Nothing here has been reconciled against a
real bill. If you rely on these numbers, check them.

## Development

```bash
uv run pytest          # 103 tests, none of which touch the network
uv run ruff check .    # lint
uv run mypy            # type check, strict
```

```
src/model_arena/
  providers/     one module per provider, plus the shared HTTP transport
  arena.py       the concurrent fan-out
  events.py      normalised tokens, shared by every provider
  pricing.py     the price table and the refusal to guess
  storage.py     saved runs
  web.py         the viewer
  render.py      HTML, and the escaping that matters
```

`src/` layout is deliberate: tests import the installed package rather than the
directory next to them, so a file missing from the build fails here instead of failing
for whoever installs it.

Adding a fifth provider means writing a request builder and a parser, and touching no
transport code at all. See [FINDINGS.md](FINDINGS.md) for why the seam is there.

## Licence

MIT. See [LICENSE](LICENSE).
