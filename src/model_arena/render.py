"""HTML for the web view.

Hand written rather than templated, for one reason worth being explicit about:
**everything on these pages came from a language model.** The answers, and often the
prompt, are arbitrary text from a system that will cheerfully produce a `<script>`
tag if the conversation goes that way. Escaping is therefore not a detail, it is the
main thing this module does, and putting it in plain sight beats trusting a template
engine's autoescaping to be on.

Every interpolation goes through `esc`. There are no exceptions, and there is a test
that puts a script tag in a model's answer and checks it comes back inert.
"""

from datetime import date, datetime
from html import escape

from model_arena.arena import Priced
from model_arena.pricing import CHECKED, CURRENCY
from model_arena.storage import Run

# One colour per provider, so a model is recognisable at a glance across pages.
PROVIDER_HUES = {
    "anthropic": "#B4531F",
    "openai": "#12796B",
    "gemini": "#6244A8",
    "groq": "#A32C5C",
}
FALLBACK_HUE = "#5B6B76"

CSS = """
:root {
  --ground:#F2F5F6; --surface:#FFF; --sunk:#E8EDEF; --ink:#121A20;
  --muted:#5B6B76; --faint:#8697A2; --line:#D8E1E5; --accent:#0B6E99; --bad:#A32B22;
  --mono:ui-monospace,"Cascadia Code","SF Mono","JetBrains Mono",Consolas,monospace;
  --sans:"Segoe UI Variable Text",-apple-system,"Segoe UI",system-ui,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --ground:#0E1418; --surface:#151D23; --sunk:#1B252C; --ink:#E4EDF2;
  --muted:#96A8B4; --faint:#6B7D89; --line:#263239; --accent:#4FB3DC; --bad:#E9827A;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
  line-height:1.6;-webkit-font-smoothing:antialiased}
.page{max-width:60rem;margin:0 auto;padding:2.5rem 1.25rem 5rem}
a{color:var(--accent)}
h1{font-family:var(--mono);font-size:1.6rem;letter-spacing:-.02em;margin:0 0 .25rem}
h1 a{text-decoration:none;color:inherit}
.sub{color:var(--muted);font-size:.9rem;margin:0 0 2rem}
.prompt{background:var(--sunk);border-left:3px solid var(--accent);border-radius:6px;
  padding:.9rem 1.1rem;margin:0 0 2rem;font-size:1.02rem}
table{border-collapse:collapse;width:100%;font-size:.92rem}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--surface)}
th,td{padding:.65rem .9rem;text-align:left;border-bottom:1px solid var(--line);
  white-space:nowrap}
tr:last-child td{border-bottom:none}
th{font-family:var(--mono);font-size:.68rem;text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted)}
td.num{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums}
td.p{white-space:normal}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;
  padding:1.15rem 1.3rem;margin:0 0 1rem}
.head{display:flex;flex-wrap:wrap;gap:.75rem;align-items:baseline;
  justify-content:space-between;margin-bottom:.5rem}
.who{font-family:var(--mono);font-size:.85rem;font-weight:700}
.dot{display:inline-block;width:.55rem;height:.55rem;border-radius:50%;
  margin-right:.45rem}
.meta{font-family:var(--mono);font-size:.76rem;color:var(--muted);
  font-variant-numeric:tabular-nums}
.bar{height:4px;background:var(--sunk);border-radius:2px;overflow:hidden;
  margin:.55rem 0 .9rem}
.bar span{display:block;height:100%;border-radius:2px}
.answer{white-space:pre-wrap;margin:0}
.unknown{color:var(--bad);font-weight:700}
.failed{color:var(--bad);font-family:var(--mono);font-size:.82rem;margin:0}
.foot{border-top:1px solid var(--line);margin-top:2rem;padding-top:1rem;
  font-family:var(--mono);font-size:.8rem;color:var(--muted)}
.foot .warn{color:var(--bad)}
.empty{color:var(--muted)}
"""


def esc(value: object) -> str:
    return escape(str(value), quote=True)


def money(amount: float) -> str:
    # Six decimals for the same reason as the terminal: at two, a real call reads
    # as $0.00, which is indistinguishable from a price we could not find.
    return f"${amount:.6f}"


def hue(provider: str) -> str:
    return PROVIDER_HUES.get(provider, FALLBACK_HUE)


def page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)}</title><style>{CSS}</style></head>"
        f"<body><div class='page'>{body}</div></body></html>"
    )


def header(subtitle: str) -> str:
    return (
        "<h1><a href='/'>model arena</a></h1>"
        f"<p class='sub'>{esc(subtitle)}</p>"
    )


def runs_page(rows: list[tuple[Run, int, float, int]]) -> str:
    """rows are (run, model count, total spend, unpriced count)."""
    if not rows:
        body = header("no runs yet") + (
            "<p class='empty'>Run <code>model-arena \"your prompt\"</code> and refresh.</p>"
        )
        return page("model arena", body)

    cells = []
    for run, models, spend, unpriced in rows:
        when = run.started_at.strftime("%Y-%m-%d %H:%M")
        cost = money(spend) + ("<span class='unknown'> +?</span>" if unpriced else "")
        cells.append(
            f"<tr><td class='num'><a href='/runs/{run.id}'>{run.id}</a></td>"
            f"<td class='meta'>{esc(when)}</td>"
            f"<td class='p'>{esc(run.prompt)}</td>"
            f"<td class='num'>{models}</td>"
            f"<td class='num'>{cost}</td></tr>"
        )

    body = (
        header(f"{len(rows)} recent runs")
        + "<div class='wrap'><table><thead><tr><th>Run</th><th>When</th>"
        "<th>Prompt</th><th>Models</th><th>Cost</th></tr></thead>"
        f"<tbody>{''.join(cells)}</tbody></table></div>"
        + footer(0, [], totals=False)
    )
    return page("model arena", body)


def run_page(run: Run, rows: list[Priced], total: float, unpriced: list[str], on: date) -> str:
    biggest = max((row.spend or 0.0 for row in rows), default=0.0)
    cards = [card(row, biggest) for row in rows]
    answered = sum(1 for row in rows if row.result.ok)
    slowest = max((row.result.seconds for row in rows), default=0.0)

    body = (
        header(f"run {run.id} · {stamp(run.started_at)} · {answered}/{len(rows)} answered "
               f"in {slowest:.1f}s")
        + f"<p class='prompt'>{esc(run.prompt)}</p>"
        + "".join(cards)
        + footer(total, unpriced, on=on)
    )
    return page(f"run {run.id} · model arena", body)


def card(row: Priced, biggest: float) -> str:
    result = row.result
    if not result.ok:
        return (
            f"<div class='card'><div class='head'><span class='who'>"
            f"<span class='dot' style='background:{esc(hue(result.provider))}'></span>"
            f"{esc(result.label)}</span>"
            f"<span class='meta'>{result.seconds:.1f}s</span></div>"
            f"<p class='failed'>FAILED {esc(result.error)}</p></div>"
        )

    unknown = "<span class='unknown'>price unknown</span>"
    priced = money(row.spend) if row.spend is not None else unknown
    # Relative to the dearest answer in the run, which is what makes a fiftyfold
    # spread legible at a glance instead of something you work out from digits.
    width = (row.spend / biggest * 100) if row.spend and biggest else 0
    return (
        f"<div class='card'><div class='head'><span class='who'>"
        f"<span class='dot' style='background:{esc(hue(result.provider))}'></span>"
        f"{esc(result.label)}</span>"
        f"<span class='meta'>in {result.usage.input_tokens} · "
        f"out {result.usage.output_tokens} · {result.seconds:.1f}s · {priced}</span></div>"
        f"<div class='bar'><span style='width:{width:.1f}%;"
        f"background:{esc(hue(result.provider))}'></span></div>"
        f"<p class='answer'>{esc(result.text.strip())}</p></div>"
    )


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def footer(total: float, unpriced: list[str], on: date | None = None, totals: bool = True) -> str:
    parts = []
    if totals:
        parts.append(f"total {money(total)} {CURRENCY}")
    parts.append(f"prices checked {CHECKED}")
    if on is not None:
        parts.append(f"priced as at {on}")
    line = " · ".join(esc(part) for part in parts)
    # Naming what the total excludes, on every surface. A total that silently drops
    # a row is a wrong total and nothing about the figure says so.
    if unpriced:
        line += (
            f"<br><span class='warn'>excludes {len(unpriced)} unpriced: "
            f"{esc(', '.join(unpriced))}</span>"
        )
    return f"<div class='foot'>{line}</div>"
