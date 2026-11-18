"""Bygger det statiske API i _site/ ud fra regnearkene i kilder/.

Hvert tal skrives som én fil, <sti>.html, hvis indhold er tallet som JSON.
GitHub Pages serverer <sti>.html på adressen <sti> (uden endelse og uden
redirect), så .../2026/h1/globale-aktier-developed-markets svarer med 0.067.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
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
    base.with_name(base.name + ".json").write_text(
        json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return len(eps)


def current_period(periods: list[str], today: dt.date) -> str:
    now = f"{today.year}-h{1 if today.month <= 6 else 2}"
    return max((p for p in periods if p <= now), default=periods[0])


def patterns_html(index: dict) -> str:
    """Stimønstrene med kommentar over hver og simpel syntaksfarvning."""
    items = [
        (f"afkast, {DEFAULT_HORIZON} år", "/{år}/h{1|2}/{aktivklasse}"),
        ("afkast for en bestemt horisont", "/{år}/h{1|2}/{horisont}/{aktivklasse}"),
        ("et bestemt nøgletal", "/{år}/h{1|2}/{horisont}/{nøgletal}/{aktivklasse}"),
        ("inflationsforventning", "/{år}/h{1|2}/inflation/{horisont}"),
        ("horisontafkast", "/{år}/h{1|2}/horisontafkast"),
        ("alt for halvåret, inkl. korrelationer", "/{år}/h{1|2}.json"),
        (f"nyeste offentliggjorte ({index['latest']})", "/latest/…"),
        (f"gældende i dag ({index['current']})", "/current/…"),
        ("halvår, aktivklasser, horisonter og nøgletal", "/index.json"),
    ]
    out = []
    for comment, pattern in items:
        p = re.sub(
            r"(\{[^}]*\})|(/|…|\.json)",
            lambda m: f"<span class={'v' if m.group(1) else 'p'}>{html.escape(m.group(0))}</span>",
            pattern)
        out.append(f"<span class=c># {html.escape(comment)}</span>\n{p}")
    return "\n\n".join(out)



def examples_html(index: dict) -> str:
    """Punktliste med eksempler: beskrivelse efterfulgt af link, der viser adressen."""
    y, h = index["latest"].split("-")
    per = f"{y}/{h}"
    navn = f"{h[1]}. halvår {y}"
    items = [
        (f"Afkast på globale aktier, {DEFAULT_HORIZON} år, {navn}", f"{per}/globale-aktier-developed-markets"),
        (f"Samme, men på horisonten 1-5 år", f"{per}/1-5/globale-aktier-developed-markets"),
        (f"Standardafvigelse på hedgefonde, 6-10 år, {navn}", f"{per}/6-10/standardafvigelse/hedgefonde"),
        (f"Fees i fonde for private equity, 1-10 år, {navn}", f"{per}/1-10/fees-i-fonde/private-equity"),
        (f"Afkast på aktier fra år 11 og frem, {navn}", f"{per}/11-plus/aktier"),
        (f"Inflationsforventning, 1-5 år, {navn}", f"{per}/inflation/1-5"),
        (f"Horisontafkast, {navn}", f"{per}/horisontafkast"),
        ("Afkast på ejendomme i det nyeste offentliggjorte halvår", "latest/ejendomme"),
        ("Afkast på ejendomme i det halvår, der gælder i dag", "current/ejendomme"),
        (f"Alt for {navn}, inkl. korrelationer", f"{per}.json"),
        ("Oversigt over halvår, aktivklasser, horisonter og nøgletal", "index.json"),
        ("OpenAPI 3.1-skema", "openapi.json"),
    ]
    e = html.escape
    return "".join(
        f"<li>{e(text)}<br><a href='{e(path)}'>{e(BASE_URL)}/{e(path)}</a></li>"
        for text, path in items)


BASE_URL = "https://simontjell.github.io/afkastforventninger"


def openapi(index: dict) -> dict:
    """OpenAPI 3.1-beskrivelse af alle adresser."""
    years = sorted({p["aar"] for p in index["perioder"]})
    assets = list(index["aktivklasser"]) + list(index["aktivklasser_11_plus"])
    params = {
        "aar": {"name": "aar", "in": "path", "required": True,
                "description": "Året, forventningerne gælder for.",
                "schema": {"type": "integer", "enum": years}},
        "halvaar": {"name": "halvaar", "in": "path", "required": True,
                    "description": "Halvår (1 eller 2).",
                    "schema": {"type": "integer", "enum": [1, 2]}},
        "horisont": {"name": "horisont", "in": "path", "required": True,
                     "description": "Tidshorisont i år. 11-plus er år 11 og frem.",
                     "schema": {"type": "string", "enum": index["horisonter"]}},
        "aktivklasse": {"name": "aktivklasse", "in": "path", "required": True,
                        "description": "Aktivklasse. Horisonten 11-plus bruger kun "
                                       + ", ".join(index["aktivklasser_11_plus"]) + ".",
                        "schema": {"type": "string", "enum": assets}},
        "noegletal": {"name": "noegletal", "in": "path", "required": True,
                      "description": "Nøgletal. Ikke alle findes for alle aktivklasser.",
                      "schema": {"type": "string", "enum": index["noegletal"]}},
    }
    number = {
        "200": {"description": "Tallet som decimaltal (0.067 = 6,7 %).",
                # GitHub Pages sender text/html for adresser uden endelse; indholdet er JSON.
                "content": {"text/html": {"schema": {"type": "number"}, "example": 0.067}}},
        "404": {"description": "Kombinationen findes ikke."},
    }
    obj = lambda desc: {
        "200": {"description": desc, "content": {"application/json": {"schema": {"type": "object"}}}},
        "404": {"description": "Findes ikke."},
    }
    ref = lambda n: {"$ref": f"#/components/parameters/{n}"}
    values = [
        ("{aktivklasse}", "Afkast", f"Forventet afkast på horisonten {index['standardhorisont']} år.", ["aktivklasse"]),
        ("{horisont}/{aktivklasse}", "AfkastHorisont", "Forventet afkast på en bestemt horisont.", ["horisont", "aktivklasse"]),
        ("{horisont}/{noegletal}/{aktivklasse}", "Noegletal", "Et bestemt nøgletal.", ["horisont", "noegletal", "aktivklasse"]),
        ("inflation/{horisont}", "Inflation", "Inflationsforventning.", ["horisont"]),
        ("horisontafkast", "Horisontafkast", "Horisontafkast (findes fra 2021 h2).", []),
    ]
    prefixes = [
        ("/{aar}/h{halvaar}", "", "", ["aar", "halvaar"]),
        ("/latest", "Latest", f" Nyeste offentliggjorte halvår (p.t. {index['latest']}).", []),
        ("/current", "Current", f" Halvåret, der gælder i dag (p.t. {index['current']}).", []),
    ]
    paths: dict = {"/index.json": {"get": {
        "operationId": "getIndex", "summary": "Halvår, aktivklasser, horisonter og nøgletal.",
        "responses": obj("Oversigt.")}}}
    for prefix, op, note, pp in prefixes:
        paths[f"{prefix}.json"] = {"get": {
            "operationId": f"get{op or 'Halvaar'}" + ("" if not op else "Halvaar"),
            "summary": "Alt for halvåret, inkl. korrelationer." + note,
            "parameters": [ref(x) for x in pp], "responses": obj("Hele halvåret.")}}
        for tail, name, summary, tp in values:
            paths[f"{prefix}/{tail}"] = {"get": {
                "operationId": f"get{op}{name}", "summary": summary + note,
                "parameters": [ref(x) for x in pp + tp], "responses": number}}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Afkastforventninger",
            "version": index["latest"],
            "description": (
                "Uofficielt, statisk API med tallene fra Rådet for Afkastforventninger "
                "(https://afkastforventninger.dk/afkastforventninger). Hver adresse svarer med "
                "ét decimaltal som JSON (fx 0.067). Bemærk: GitHub Pages sender Content-Type "
                "text/html for disse adresser, selv om indholdet er JSON. Kun GET."),
        },
        "servers": [{"url": BASE_URL}],
        "paths": paths,
        "components": {"parameters": params},
    }


def index_html(index: dict) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td><a href='{p['aar']}/h{p['halvaar']}.json'>{p['aar']} h{p['halvaar']}</a></td>"
        f"<td><a href='{e(p['kilde'])}'>regneark</a></td></tr>" for p in reversed(index["perioder"]))
    assets = "".join(f"<li><code>{e(s)}</code> – {e(n)}</li>" for s, n in index["aktivklasser"].items())
    long_ = "".join(f"<li><code>{e(s)}</code> – {e(n)}</li>" for s, n in index["aktivklasser_11_plus"].items())
    metrics = "".join(f"<li><code>{e(m)}</code></li>" for m in index["noegletal"])
    examples = examples_html(index)
    patterns = patterns_html(index)
    return f"""<!doctype html>
<html lang="da"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Afkastforventninger – API</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}}
code,pre{{background:#f3f3f3;padding:.1em .3em;border-radius:3px}}pre{{padding:.8em;overflow-x:auto;font-size:10px}}
.ex{{padding-left:1.2em}}.ex li{{margin:.5em 0}}.ex a{{font:12px ui-monospace,monospace;overflow-wrap:anywhere}}
.c{{color:#6a737d;font-style:italic}}.v{{color:#0550ae}}.p{{color:#cf222e}}
td{{padding:.1em 1em .1em 0}}@media(prefers-color-scheme:dark){{body{{background:#161616;color:#ddd}}code,pre{{background:#262626}}a{{color:#8ab4f8}}.c{{color:#8b949e}}.v{{color:#79c0ff}}.p{{color:#ff7b72}}}}</style>
<h1>Afkastforventninger som API</h1>
<p>Tallene fra <a href="https://afkastforventninger.dk/afkastforventninger">Rådet for Afkastforventninger</a>
som decimaltal på faste adresser. Dette er et uofficielt API (uden lovning om korrekthed) lavet på baggrund af rådets Excel-ark (som stadig er den officielle kilde).</p>
<p>Lavet af <a href="https://simplesystemer.dk">Simple Systemer</a>.</p>
<h2>Eksempler</h2>
<ul class="ex">{examples}</ul>
<p>Svaret er tallet alene (<code>0.067</code> = 6,7 %). Indholdet er gyldig JSON.</p>
<h2>Mønstre</h2>
<pre>{patterns}</pre>
<p>Maskinlæsbar beskrivelse: <a href="openapi.json">openapi.json</a> (OpenAPI 3.1).</p>
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
    (SITE / "openapi.json").write_text(json.dumps(openapi(index), indent=2, ensure_ascii=False) + "\n")
    (SITE / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    (SITE / "index.html").write_text(index_html(index))
    (SITE / "404.html").write_text(
        "<!doctype html><meta charset=utf-8><title>404</title>"
        "<p>Ukendt sti. Se <a href='/afkastforventninger/'>oversigten</a>.</p>\n")
    print(f"{len(data)} halvår, {n} tal skrevet til {SITE.name}/ "
          f"(latest={latest}, current={current})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
