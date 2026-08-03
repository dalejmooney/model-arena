# Model Arena

Run the same prompt across every model and compare the answers side by side, with what each one cost.

Picking a model from a leaderboard tells you how it performs on somebody else's task. This runs your prompt, on the models you actually have access to, and puts the answers next to each other along with tokens and cost.

## Status

Early. The scaffolding is in place and the first provider is next. Built in the open as I go.

## What it will do

- One prompt, many models, answers side by side
- Concurrent calls, so adding a model does not add latency
- Token and cost accounting per call and per model
- Every run saved, so two models can be diffed on the same prompt later
- A web view worth actually looking at

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
src/model_arena/    the package
tests/              tests
pyproject.toml      project metadata and all tool config
uv.lock             exact resolved dependency versions
```

`src/` layout is deliberate: it means the tests import the installed package rather than the
directory sitting next to them, so a file missing from the build fails here instead of failing
for whoever installs it.

## Licence

MIT
