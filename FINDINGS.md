# What I found building this

Every number here came off a real call made on 3 August 2026. Nothing is estimated
from documentation, and where something has not been verified I have said so.

The short version: **a per-token price is not a price.** What a model costs depends
on how much it thinks before answering, that varies per call, and at least two of
the four providers will quietly not tell you unless you know which field to read.

---

## 1. The same answer, at fifty-one times the price

All four were asked to explain an API rate limit in one sentence. All four produced
roughly thirty words of about equal quality.

| Provider | Model | In | Out | Cost |
|---|---|---:|---:|---:|
| groq | llama-3.3-70b-versatile | 46 | 50 | $0.000067 |
| anthropic | claude-sonnet-5 | 21 | 55 | $0.000592 |
| openai | gpt-5 | 17 | 107 | $0.001091 |
| gemini | gemini-3.6-flash | 11 | 452 | $0.003406 |

Gemini charged **fifty-one times** what Groq did for the same sentence. Almost all
of that gap is reasoning: thinking the model does before replying, billed as output,
never shown to you.

It is not a big-model effect either. `gpt-5-nano`, the cheapest model OpenAI sells,
spent **203 output tokens answering "Blue."** Two hundred of those were reasoning,
on a one-word question.

---

## 2. The bug I nearly shipped

Gemini reports its token usage in a field called `candidatesTokenCount`. That is the
obvious field, it is the one every tutorial reads, and on one call it said **1**.

The call was billed for **169**.

The other 168 were in a separate field called `thoughtsTokenCount`, because Google
counts reasoning separately from the answer. Their pricing page settles it outright:
output is billed *"including thinking tokens"*.

So a cost tracker written the obvious way reports one output token, the response
looks completely healthy, nothing errors, and the figure is wrong by a factor of a
hundred and sixty nine.

That is the failure mode this whole project keeps running into. Not a crash. Not an
error. A confident number that happens to be wrong, with nothing about it looking
wrong.

The fix is one line — `candidates + thoughts` — and there is a test pinned to those
exact real figures so nobody simplifies it back.

---

## 3. Most provider diversity is one wire format with dialects

Four providers, and the transport turned out to be identical every time: open a
streaming POST, check the status, read Server-Sent Events line by line. Only three
things actually vary, which is why they are the whole interface: where to send it,
what the body looks like, and how to read a chunk.

What genuinely differs is worth writing down.

**Anthropic** names its stream events, so a `content_block_delta` carrying no text is
broken and should raise. It also reports input and output tokens at opposite ends of
the stream, so neither event alone tells you what a call cost.

**OpenAI** sends one chunk shape with everything optional, so a delta without content
is *normal* rather than broken, and the opposite validation rule applies. Token counts
are opt-in: without `stream_options`, a stream reports nothing at all and the call
silently costs an unknown amount. `max_tokens` is deprecated in favour of
`max_completion_tokens`, which covers hidden reasoning as well as the answer, so a
small budget can return no visible text whatsoever. I hit exactly that: a 32-token
budget produced an empty string.

**Groq** is the OpenAI API on different hardware, which is the finding in itself. The
whole provider is four constants and one override. Its dialect is putting token counts
in an `x_groq` envelope, so a client that only knows OpenAI streams from Groq quite
happily and never learns what anything cost.

**Gemini** shares almost no assumptions. The model goes in the URL rather than the
body. The response is only Server-Sent Events because `?alt=sse` asks for it; the
default streams a growing JSON array you cannot read a line at a time. Text is nested
two lists deep. Usage is a running total repeated on every chunk rather than reported
once.

That last one drove a design decision. Summing usage as it arrives is correct for
Anthropic and OpenAI, and would multiply Gemini's number by the chunk count. The rule
that works for all four is **take the newest value**, which is why it lives in
`events.py` rather than in any one provider.

---

## 4. Asking them all at once

```
4/4 answered in 5.1s
one at a time would have taken 14.4s
```

Waiting is almost all of what this program does. It sends a few hundred bytes, then
sits there while somebody else's server thinks, so the waiting may as well overlap.

That is the honest case for asyncio rather than threads: no CPU work to speak of,
just four sockets idle most of the time. **Only the transport is async.** Building a
request and parsing a chunk stayed ordinary functions, because neither waits for
anything. Make everything `async def` and the keyword stops carrying information;
kept narrow, every `await` in the codebase marks something that genuinely blocks, and
there is exactly one.

The claim is measured rather than asserted. `tests/test_arena.py` uses
`httpx.MockTransport` to build a fake network with per-provider delays, so the test
would actually fail if the calls stopped overlapping, and it never touches the
network.

---

## 5. Four rules that fell out of the above

Each of these is the same idea in different clothing: **keep the measurement, derive
the valuation, and never let a derived number harden into a fact.**

**An unknown price is never zero.** A model missing from the price table reports
`price unknown`, and the run total names what it excluded:

```
total $0.000287 USD, prices checked 2026-08-03
excludes 1 unpriced: gemini:gemini-3.1-flash-lite
```

A table quietly showing $0.00 for the one row nobody priced is worse than showing
nothing, because the reader cannot tell from the number that anything is missing.

**Promotional prices lapse into unknown rather than staying wrong.** Claude Sonnet 5's
introductory rate ends on 31 August 2026, so its entry carries that date and stops
answering after it. The successor rate is deliberately not encoded. A stale price is
indistinguishable from a current one at the moment you read the total, which is
exactly too late.

**The database has no cost column, and a test asserts it.** Tokens are what the
provider reported and they never change. A price is a number on a page somebody else
edits. Store the money and last month's history quietly becomes figures that were true
once, with nothing marking which. Store the tokens and any run can be repriced, which
is what `--show` does. A comment can be deleted by someone being helpful; a failing
test cannot.

**Failed providers are saved too.** "Groq was down on Tuesday" is a fact about Groq.
Keeping only the successes rewrites history into one where everything always worked,
which is the least useful history to own.

---

## 6. The security bit

Everything on the web view came out of a language model. "Write me a hello world web
page" is an ordinary prompt, and its answer contains real tags. Rendered raw, a model
would be scripting the page that displays it, and the person who typed the prompt
would be the one running it.

So the HTML is hand written with explicit escaping rather than templated, deliberately,
to keep that in plain sight instead of trusting a template engine's autoescaping to be
switched on.

The test I wrote for it was wrong first time, which was instructive. It asserted the
string `onerror=alert` was absent from the page, and failed, because the *escaped* text
still contains those characters. The property that matters is not that the characters
are gone. It is that no live element or attribute reaches the document. Escaped, the
same text is visible to the reader and inert to the browser, which is exactly the goal.

---

## 7. What is still open

**None of these figures has been reconciled against an actual invoice.** They are
arithmetic over a price table I typed, read off each provider's own pricing page. That
is why the function is called `estimate` rather than `cost`. Until a counter is diffed
against a real bill it is a plausible number rather than a verified one, and plausible
is precisely the failure mode described in section 2.

**The mapping is not stable over time.** Reasoning tokens were once not a separate
field anywhere. A provider adding a new token category breaks nothing loudly; your
total just quietly gets smaller. So the reconciliation needs a canary of its own, or
you have moved the confidently wrong number one layer down rather than removed it.

Manish Bhaktisagar put the consequence better than I did, discussing this on LinkedIn:

> Token count is only a valid efficiency signal if you've verified you're reading the
> same accounting field the provider actually bills against. Otherwise you're measuring
> disclosure practices, not agent behavior.

**And even read correctly, the count answers the wrong question for evaluation.** It
tells you what you will be billed, not how well the model worked. Something that spends
400 tokens thinking and lands on the same answer is more expensive, but not obviously
less efficient at the task. Cost and path quality diverge, and tokens only measure the
first.

---

## Reproducing any of this

Clone it, add your own keys, run it. Everything above is one command:

```bash
model-arena "explain an API rate limit in one sentence"
```

See the [README](README.md) for setup.
