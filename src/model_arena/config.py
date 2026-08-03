"""Reading configuration from the environment.

Secrets come from the environment, never from the codebase. `load_dotenv()` reads
a local `.env` for convenience during development; in anything deployed, the same
variables are set by the platform and there is no `.env` at all. The code cannot
tell the difference, which is the point.
"""

import os

from dotenv import load_dotenv

load_dotenv()


class MissingConfig(RuntimeError):
    """A required environment variable is not set."""


def require_env(name: str) -> str:
    """Return an environment variable, or fail immediately with a useful message.

    `os.environ.get` returns `str | None`. If every call site handled that itself
    you would have a `None` check scattered through the codebase, or worse, people
    would reach for `os.environ[name]` and get a bare KeyError with no advice in it.

    Doing it once here means the return type is `str`, so nothing downstream has to
    think about it, and the failure happens at startup with an actionable message
    rather than three layers deep as an AttributeError on None.
    """
    value = os.environ.get(name)
    if not value:
        raise MissingConfig(
            f"{name} is not set. Add it to .env in the project root, "
            f"or export it in your shell. .env is gitignored."
        )
    return value
