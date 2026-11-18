"""Bygger det statiske API i _site/ ud fra regnearkene i kilder/.

Hvert tal skrives som tre filer: <sti>.html, <sti>.txt og <sti>.json.
GitHub Pages serverer <sti>.html på adressen <sti> (uden endelse og uden
redirect), så .../2026/h1/globale-aktier-developed-markets svarer med 0.067.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import shutil
import sys
from pathlib import Path

from .parse import DEFAULT_HORIZON, parse_workbook

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "kilder"
SITE = ROOT / "_site"


def fmt(v: float) -> str:
    return f"{v:.6f}".rstrip("0").rstrip(".") if v else "0"


def endpoints(d: dict) -> dict[str, float]:
    """{relativ sti: værdi} for ét halvår."""
    out: dict[str, float] = {}
    for hz, h in d["horisonter"].items():
        for slug, a in h["aktivklasser"].items():
            out[f"{hz}/{slug}"] = a["afkast"]
            if hz == DEFAULT_HORIZON:
                out[slug] = a["afkast"]
            for metric, v in a.items():
                if metric != "navn":
                    out[f"{hz}/{metric}/{slug}"] = v
    for hz, v in d["inflation"].items():
        out[f"inflation/{hz}"] = v
    if d["horisontafkast"] is not None:
        out["horisontafkast"] = d["horisontafkast"]
    # En sti må ikke både være et tal og en mappe (fx hvis en aktivklasse en
    # dag kommer til at hedde det samme som et nøgletal).
    dirs = {p.rsplit("/", 1)[0] for p in out if "/" in p}
    dirs |= {d.split("/")[0] for d in dirs}
    clash = dirs & set(out)
    if clash:
        raise SystemExit(f"Stikonflikt i {d['periode']}: {sorted(clash)}")
    return out


def write_period(base: Path, d: dict) -> int:
    eps = endpoints(d)
    for rel, v in eps.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        s = fmt(v)
        p.with_name(p.name + ".html").write_text(s)
        p.with_name(p.name + ".txt").write_text(s + "\n")
        p.with_name(p.name + ".json").write_text(s + "\n")
    base.with_name(base.name + ".json").write_text(
        json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return len(eps)


def current_period(periods: list[str], today: dt.date) -> str:
    now = f"{today.year}-h{1 if today.month <= 6 else 2}"
    return max((p for p in periods if p <= now), default=periods[0])


def index_html(index: dict, example: dict) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td><a href='{p['aar']}/h{p['halvaar']}.json'>{p['aar']} h{p['halvaar']}</a></td>"
        f"<td><a href='{e(p['kilde'])}'>regneark</a></td></tr>" for p in reversed(index["perioder"]))
    assets = "".join(f"<li><code>{e(s)}</code> – {e(n)}</li>" for s, n in index["aktivklasser"].items())
    long_ = "".join(f"<li><code>{e(s)}</code> – {e(n)}</li>" for s, n in index["aktivklasser_11_plus"].items())
    metrics = "".join(f"<li><code>{e(m)}</code></li>" for m in index["noegletal"])
    y, h = example["aar"], example["halvaar"]
    v = fmt(example["horisonter"][DEFAULT_HORIZON]["aktivklasser"]["globale-aktier-developed-markets"]["afkast"])
    return f"""<!doctype html>
<html lang="da"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Afkastforventninger – API</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}}
code,pre{{background:#f3f3f3;padding:.1em .3em;border-radius:3px}}pre{{padding:.8em;overflow-x:auto}}
td{{padding:.1em 1em .1em 0}}@media(prefers-color-scheme:dark){{body{{background:#161616;color:#ddd}}code,pre{{background:#262626}}a{{color:#8ab4f8}}}}</style>
<h1>Afkastforventninger som API</h1>
<p>Tallene fra <a href="https://afkastforventninger.dk/afkastforventninger">Rådet for Afkastforventninger</a>
som decimaltal på faste adresser. Uofficielt; regnearkene hos rådet er kilden.</p>
<pre>/{{år}}/h{{1|2}}/{{aktivklasse}}                       afkast, {DEFAULT_HORIZON} år
/{{år}}/h{{1|2}}/{{horisont}}/{{aktivklasse}}            afkast
/{{år}}/h{{1|2}}/{{horisont}}/{{nøgletal}}/{{aktivklasse}}
/{{år}}/h{{1|2}}/inflation/{{horisont}}
/{{år}}/h{{1|2}}/horisontafkast
/{{år}}/h{{1|2}}.json                                alt for halvåret
/latest/…   nyeste offentliggjorte ({e(index['latest'])})
/current/…  gældende i dag ({e(index['current'])})
/index.json</pre>
<p>Eksempel: <a href="{y}/h{h}/globale-aktier-developed-markets"><code>{y}/h{h}/globale-aktier-developed-markets</code></a> → <code>{v}</code>.
Tilføj <code>.txt</code> eller <code>.json</code> for en anden content-type.</p>
<h2>Horisonter</h2><p><code>1-5</code>, <code>6-10</code>, <code>1-10</code>, <code>11-plus</code></p>
<h2>Aktivklasser</h2><ul>{assets}</ul><p>På <code>11-plus</code>:</p><ul>{long_}</ul>
<h2>Nøgletal</h2><ul>{metrics}</ul>
<h2>Halvår</h2><table>{rows}</table>
<p><small>Bygget {e(index['bygget'])}.</small></p></html>
"""


def main() -> int:
    manifest = json.loads((SOURCES / "manifest.json").read_text())
    data = {}
    for key, entry in sorted(manifest.items()):
        year, half = int(key[:4]), int(key[-1])
        d = parse_workbook(SOURCES / entry["fil"], year, half)
        d["kilde"] = entry["url"]
        data[key] = d
        if d["ignorerede_faner"]:
            print(f"{key}: ignorerer fane(r) {d['ignorerede_faner']}", file=sys.stderr)

    shutil.rmtree(SITE, ignore_errors=True)
    SITE.mkdir()
    (SITE / ".nojekyll").write_text("")
    periods = sorted(data)
    latest = periods[-1]
    current = current_period(periods, dt.date.today())
    n = 0
    for key, d in data.items():
        n += write_period(SITE / str(d["aar"]) / f"h{d['halvaar']}", d)
    write_period(SITE / "latest", data[latest])
    write_period(SITE / "current", data[current])

    names, long_names, metrics = {}, {}, []
    for d in data.values():
        for hz, h in d["horisonter"].items():
            for slug, a in h["aktivklasser"].items():
                (long_names if hz == "11-plus" else names)[slug] = a["navn"]
                metrics += [m for m in a if m != "navn" and m not in metrics]
    index = {
        "bygget": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "latest": latest,
        "current": current,
        "standardhorisont": DEFAULT_HORIZON,
        "horisonter": list(data[latest]["horisonter"]),
        "noegletal": metrics,
        "aktivklasser": names,
        "aktivklasser_11_plus": long_names,
        "perioder": [{"periode": k, "aar": d["aar"], "halvaar": d["halvaar"],
                      "kilde": d["kilde"]} for k, d in data.items()],
    }
    (SITE / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    (SITE / "index.html").write_text(index_html(index, data[latest]))
    (SITE / "404.html").write_text(
        "<!doctype html><meta charset=utf-8><title>404</title>"
        "<p>Ukendt sti. Se <a href='/afkastforventninger/'>oversigten</a>.</p>\n")
    print(f"{len(data)} halvår, {n} tal skrevet til {SITE.name}/ "
          f"(latest={latest}, current={current})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
