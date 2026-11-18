"""Bygger det statiske API i _site/ ud fra regnearkene i kilder/.

Hvert tal skrives som <sti>.json, hver mappe som <sti>.json (alt under den)
og <sti>/index.html (oversigt med links), så .../api/2026/h1/globale-aktier-developed-markets.json svarer med 0.067.
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
API = SITE / "api"   # alle data ligger under /api/


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


PAGE_CSS = """
:root{--bg:#fbfbfa;--fg:#1c1c1a;--muted:#6f6f6a;--line:#e6e5e1;--hover:#f1f0ec;--link:#0b57a4;--pill:#eeede9}
@media(prefers-color-scheme:dark){:root{--bg:#141414;--fg:#e8e6e1;--muted:#9a9891;--line:#2a2a28;--hover:#1e1e1c;--link:#8ab4f8;--pill:#262624}}
*{box-sizing:border-box}
body{font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;max-width:44rem;margin:0 auto;padding:2.5rem 1rem 4rem;color:var(--fg);background:var(--bg)}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
.crumbs{font:600 1.35rem/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;margin:0 0 .35rem}
.crumbs a,.crumbs .here{white-space:nowrap}
.crumbs .sep{color:var(--muted);font-weight:400;margin:0 .3em}
.crumbs .here{color:var(--fg)}
.sub{color:var(--muted);font-size:.9rem;margin:0 0 1.75rem}
.list{list-style:none;margin:0;padding:0;border-top:1px solid var(--line)}
.list li{display:flex;align-items:center;gap:.75rem;border-bottom:1px solid var(--line)}
.list li:hover{background:var(--hover)}
.list .main{flex:1;min-width:0;display:flex;align-items:baseline;gap:.75rem;padding:.7rem .5rem;color:inherit}
.list .main:hover{text-decoration:none}
.list .name{font:500 .95rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--link);white-space:nowrap}
.list .label{color:var(--muted);font-size:.85rem;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.list .val{font:600 .95rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;white-space:nowrap}
.list .pct{color:var(--muted);font-size:.8rem;font-variant-numeric:tabular-nums;white-space:nowrap;width:4.2em;text-align:right}
.list .go{color:var(--muted)}
.list .json{font:.72rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--muted);background:var(--pill);border-radius:999px;padding:.15rem .55rem;margin-right:.5rem}
.list .json:hover{color:var(--link);text-decoration:none}
@media(max-width:34rem){body{padding-top:1.5rem}.crumbs{font-size:1.1rem}.list .main{flex-wrap:wrap;gap:.1rem .75rem}.list .name{flex:1;min-width:0;white-space:normal;overflow-wrap:break-word}.list .label{flex-basis:100%;order:3;white-space:normal}.list .pct{display:none}}
"""

# Læsbare navne til oversigtssiderne. Aktivklassernes navne fyldes på fra regnearkene i main().
LABELS: dict[str, str] = {
    "api": "alle halvår",
    "latest": "nyeste offentliggjorte halvår",
    "current": "halvåret, der gælder i dag",
    "h1": "1. halvår",
    "h2": "2. halvår",
    "1-5": "år 1-5",
    "6-10": "år 6-10",
    "1-10": "år 1-10",
    "11-plus": "år 11 og frem",
    "afkast": "forventet afkast",
    "standardafvigelse": "standardafvigelse",
    "investeringsomkostninger": "investeringsomkostninger",
    "fees-i-fonde": "fees i fonde",
    "afkast-unhedged": "afkast uden valutaafdækning",
    "loebende-afkast": "løbende afkast",
    "kursaendring": "kursændring",
    "inflation": "inflationsforventning",
    "horisontafkast": "horisontafkast",
}


def listing_html(folder: Path, node: dict) -> str:
    """Oversigtsside for en mappe: brødkrummesti og derunder en lodret liste
    med alt, der ligger direkte under mappen."""
    e = html.escape
    parts = folder.relative_to(SITE).parts
    sep = "<span class=sep>/</span>"
    crumbs = [f"<a href='{'../' * len(parts)}'>afkastforventninger</a>"]
    for i, part in enumerate(parts[:-1]):
        crumbs.append(f"<a href='{'../' * (len(parts) - 1 - i)}'>{e(part)}</a>")
    crumbs.append(f"<span class=here>{e(parts[-1])}</span>")

    # mapper først (horisonter i naturlig rækkefølge, resten alfabetisk), derefter tallene
    hz = {"1-5": 0, "6-10": 1, "1-10": 2, "11-plus": 3}
    top = {"latest": 0, "current": 1}
    folders = [k for k, v in node.items() if isinstance(v, dict)]
    if parts == ("api",):
        folders.sort(key=lambda k: (top.get(k, 2), -int(k) if k.isdigit() else 0))
    else:
        folders.sort(key=lambda k: (hz.get(k, 9), k))
    values = [k for k, v in node.items() if not isinstance(v, dict)]

    rows = []
    for name in folders + values:
        child = node[name]
        label = f"<span class=label>{e(LABELS.get(name, ''))}</span>"
        if isinstance(child, dict):
            body = (f"<a class=main href='{e(name)}/'><span class=name>{e(name)}/</span>"
                    f"{label}<span class=go>›</span></a>")
        else:
            pct = f"{child * 100:.2f}".rstrip("0").rstrip(".").replace(".", ",")
            body = (f"<a class=main href='{e(name)}.json'><span class=name>{e(name)}.json</span>"
                    f"{label}<span class=val>{fmt(child)}</span><span class=pct>{pct} %</span></a>")
        pill = f"<a class=json href='{e(name)}.json'>.json</a>" if isinstance(child, dict) else ""
        rows.append(f"<li>{body}{pill}</li>")

    path = "/".join(("afkastforventninger",) + parts)
    return (
        f"<!doctype html>\n<html lang=\"da\"><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        f"<title>{e(path)}</title>\n"
        f"<link rel=\"icon\" href=\"{'../' * len(parts)}favicon.svg\" type=\"image/svg+xml\">\n"
        f"<style>{PAGE_CSS}</style>\n"
        f"<h1 class=crumbs>{sep.join(crumbs)}</h1>\n"
        f"<p class=sub>{e(LABELS.get(parts[-1], parts[-1]))} · alt herunder som JSON: "
        f"<a href='../{e(parts[-1])}.json'>{e(parts[-1])}.json</a></p>\n"
        f"<ul class=list>{''.join(rows)}</ul>\n</html>\n")


TREE_CSS = """
.tools{display:flex;gap:.5rem;margin:0 0 1rem}
.tools button{font:inherit;font-size:.8rem;color:var(--muted);background:var(--pill);border:0;border-radius:999px;padding:.25rem .8rem;cursor:pointer}
.tools button:hover{color:var(--link)}
.tree,.tree ul{list-style:none;margin:0;padding:0}
.tree{border-top:1px solid var(--line)}
.tree ul{margin-left:.6rem;padding-left:.9rem;border-left:1px solid var(--line)}
.tree>li{border-bottom:1px solid var(--line)}
.tree .row{display:flex;align-items:baseline;gap:.75rem;padding:.38rem .4rem;border-radius:3px}
.tree .row:hover{background:var(--hover)}
.tree summary{list-style:none;cursor:pointer}
.tree summary::-webkit-details-marker{display:none}
.tree summary::before{content:"\\25B8";color:var(--muted);width:.9em;flex:none;display:inline-block;text-align:center;line-height:1;align-self:center;transition:transform .12s}
.tree details[open]>summary::before{transform:rotate(90deg)}
.tree li>.row:not(summary){padding-left:calc(.4rem + .9em + .75rem)}
.tree .name{font:500 .9rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap}
.tree .label{color:var(--muted);font-size:.82rem;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tree .val{font:600 .9rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;white-space:nowrap}
.tree .pct{color:var(--muted);font-size:.78rem;font-variant-numeric:tabular-nums;white-space:nowrap;width:4.2em;text-align:right}
@media(max-width:34rem){.tree ul{margin-left:.25rem;padding-left:.5rem}.tree .label,.tree .pct{display:none}.tree .name{white-space:normal;overflow-wrap:break-word;min-width:0;flex:1}}
"""

TREE_JS = """
document.querySelectorAll('.tools button').forEach(function (b) {
  b.onclick = function () {
    var open = b.dataset.open === '1';
    document.querySelectorAll('.tree details').forEach(function (d) { d.open = open; });
  };
});
"""


def ordered(node: dict, top_level: bool = False) -> list[str]:
    """Mapper først (horisonter i naturlig rækkefølge), derefter tallene."""
    hz = {"1-5": 0, "6-10": 1, "1-10": 2, "11-plus": 3}
    top = {"latest": 0, "current": 1}
    folders = [k for k, v in node.items() if isinstance(v, dict)]
    if top_level:
        folders.sort(key=lambda k: (top.get(k, 2), -int(k) if k.isdigit() else 0))
    else:
        folders.sort(key=lambda k: (hz.get(k, 9), k))
    return folders + [k for k, v in node.items() if not isinstance(v, dict)]


def tree_html(tree: dict) -> str:
    """Siden /api/: hele API'et som ét træ, hvor hver knude linker til sin .json."""
    e = html.escape

    def render(node: dict, prefix: str, depth: int) -> str:
        out = []
        for name in ordered(node, top_level=depth == 0):
            child = node[name]
            href = f"{prefix}{name}.json"
            link = f"<a class=name href='{e(href)}'>{e(name)}.json</a>"
            label = f"<span class=label>{e(LABELS.get(name, ''))}</span>"
            if isinstance(child, dict):
                is_open = " open" if (depth == 0 and name == "current") else ""
                out.append(f"<li><details{is_open}><summary class=row>{link}{label}</summary>"
                           f"<ul>{render(child, f'{prefix}{name}/', depth + 1)}</ul></details></li>")
            else:
                p = f"{child * 100:.2f}".rstrip("0").rstrip(".").replace(".", ",")
                out.append(f"<li><div class=row>{link}{label}<span class=val>{fmt(child)}</span>"
                           f"<span class=pct>{p} %</span></div></li>")
        return "".join(out)

    return (
        "<!doctype html>\n<html lang=\"da\"><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        "<title>afkastforventninger/api</title>\n"
        "<link rel=\"icon\" href=\"../favicon.svg\" type=\"image/svg+xml\">\n"
        f"<style>{PAGE_CSS}{TREE_CSS}</style>\n"
        "<h1 class=crumbs><a href='../'>afkastforventninger</a><span class=sep>/</span>"
        "<span class=here>api</span></h1>\n"
        "<p class=sub>Hele API'et som træ. Hver knude linker til sin JSON.</p>\n"
        "<div class=tools><button data-open=1>Fold alt ud</button><button data-open=0>Fold alt ind</button></div>\n"
        "<ul class=tree><li><details open><summary class=row>"
        "<a class=name href='../api.json'>api.json</a><span class=label>alle halvår</span></summary>"
        f"<ul>{render(tree, '', 0)}</ul></details></li></ul>\n"
        f"<script>{TREE_JS}</script>\n</html>\n")


def write_tree(folder: Path, node: dict, own_json: bool = True) -> None:
    """Det generelle mønster for en mappe X:

      X/        HTML-side med links til det, der ligger direkte under X
      X.json    alle tal under X som JSON (application/json)
      X/navn.json  et enkelt tal
    """
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(listing_html(folder, node))
    if own_json:
        folder.with_name(folder.name + ".json").write_text(
            json.dumps(node, indent=2, ensure_ascii=False) + "\n")
    for name, child in node.items():
        if isinstance(child, dict):
            write_tree(folder / name, child)
        else:
            (folder / f"{name}.json").write_text(fmt(child) + "\n")


def write_period(base: Path, d: dict) -> dict:
    eps = endpoints(d)
    tree: dict = {}
    for rel, v in eps.items():
        node = tree
        *dirs, leaf = rel.split("/")
        for seg in dirs:
            node = node.setdefault(seg, {})
        node[leaf] = v
    # Halvårets egen .json er den fulde udgave med navne og korrelationer.
    write_tree(base, tree, own_json=False)
    base.with_name(base.name + ".json").write_text(
        json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return tree


def current_period(periods: list[str], today: dt.date) -> str:
    now = f"{today.year}-h{1 if today.month <= 6 else 2}"
    return max((p for p in periods if p <= now), default=periods[0])


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
                "content": {"application/json": {"schema": {"type": "number"}, "example": 0.067}}},
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
        ("/api/{aar}/h{halvaar}", "", "", ["aar", "halvaar"]),
        ("/api/latest", "Latest", f" Nyeste offentliggjorte halvår (p.t. {index['latest']}).", []),
        ("/api/current", "Current", f" Halvåret, der gælder i dag (p.t. {index['current']}).", []),
    ]
    paths: dict = {
        "/api.json": {"get": {
            "operationId": "getAlt", "summary": "Roden i træet: alle halvår samt latest og current.",
            "responses": obj("latest, current og hvert år -> halvår -> hele halvåret.")}},
        "/api/{aar}.json": {"get": {
            "operationId": "getAar", "summary": "Begge halvår for et år.",
            "parameters": [ref("aar")], "responses": obj("h1/h2 -> hele halvåret.")}},
    }
    numbers = {"type": "object", "additionalProperties": {"type": "number"}}
    nested = {"type": "object", "additionalProperties": {"oneOf": [{"type": "number"}, numbers]}}

    def folder(desc: str, schema: dict) -> dict:
        return {"200": {"description": desc, "content": {"application/json": {"schema": schema}}},
                "404": {"description": "Findes ikke."}}
    for prefix, op, note, pp in prefixes:
        paths[f"{prefix}.json"] = {"get": {
            "operationId": f"get{op or 'Halvaar'}" + ("" if not op else "Halvaar"),
            "summary": "Alt for halvåret, inkl. korrelationer." + note,
            "parameters": [ref(x) for x in pp], "responses": obj("Hele halvåret.")}}
        paths[f"{prefix}/inflation.json"] = {"get": {
            "operationId": f"get{op}InflationAlle",
            "summary": "Inflationsforventning for alle horisonter." + note
                       + " Alle mapper svarer på samme måde: mappens navn + .json giver tallene under den.",
            "parameters": [ref(x) for x in pp],
            "responses": {"200": {"description": "Horisont -> inflation.", "content": {"application/json": {
                "schema": {"type": "object", "additionalProperties": {"type": "number"}},
                "example": {"1-5": 0.018, "6-10": 0.018, "1-10": 0.018, "11-plus": 0.02}}}}}}}
        # Mapperne som .json. Horisonter og nøgletal står som faste stier, fordi de ellers
        # ville være tvetydige med {aktivklasse} på samme niveau.
        for hz in index["horisonter"]:
            hz_id = hz.replace("-", " ").title().replace(" ", "")
            paths[f"{prefix}/{hz}.json"] = {"get": {
                "operationId": f"get{op}Horisont{hz_id}",
                "summary": f"Alt på horisonten {hz}: afkast pr. aktivklasse og hvert nøgletal." + note,
                "parameters": [ref(x) for x in pp],
                "responses": folder("Aktivklasse -> afkast, og nøgletal -> aktivklasse -> værdi.", nested)}}
        for metric in index["noegletal"]:
            m_id = metric.replace("-", " ").title().replace(" ", "")
            paths[f"{prefix}/{{horisont}}/{metric}.json"] = {"get": {
                "operationId": f"get{op}Alle{m_id}",
                "summary": f"{LABELS.get(metric, metric).capitalize()} for alle aktivklasser på en horisont." + note,
                "parameters": [ref(x) for x in pp + ["horisont"]],
                "responses": folder("Aktivklasse -> værdi.", numbers)}}
        for tail, name, summary, tp in values:
            paths[f"{prefix}/{tail}.json"] = {"get": {
                "operationId": f"get{op}{name}", "summary": summary + note,
                "parameters": [ref(x) for x in pp + tp], "responses": number}}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Afkastforventninger",
            "version": index["latest"],
            "description": (
                "Uofficielt, statisk API med tallene fra Rådet for Afkastforventninger "
"(https://afkastforventninger.dk/afkastforventninger). API'et er et træ: hver knude har "
                "en .json-adresse. Et blad svarer med ét decimaltal (fx 0.067 = 6,7 %), en mappe med alt "
                "under sig. Hele træet kan ses på /api/. Content-Type er application/json. Kun GET."),
        },
        "servers": [{"url": BASE_URL}],
        "paths": paths,
        "components": {"parameters": params},
    }


INDEX_CSS = """
:root{--bg:#fbfbfa;--fg:#1c1c1a;--muted:#6f6f6a;--line:#e6e5e1;--link:#0b57a4;--accent:#12325a;--on:#fff;--code:#f3f2ee}
@media(prefers-color-scheme:dark){:root{--bg:#141414;--fg:#e8e6e1;--muted:#9a9891;--line:#2a2a28;--link:#8ab4f8;--accent:#8ab4f8;--on:#141414;--code:#1c1c1a}}
*{box-sizing:border-box}
html{border-top:4px solid var(--accent)}
body{font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;max-width:40rem;margin:0 auto;padding:4.5rem 1rem 4rem;color:var(--fg);background:var(--bg)}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
.over{font-size:.75rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:0 0 .6rem}
h1{font:400 2.75rem/1.15 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;letter-spacing:-.01em;margin:0 0 1.25rem;color:var(--accent)}
.lead{margin:0 0 .5rem}
.by{color:var(--muted);font-size:.9rem;margin:0}
nav{display:flex;flex-wrap:wrap;align-items:center;gap:.75rem 1.5rem;margin:2.25rem 0 0;font-size:.95rem}
nav a{font-weight:600}
nav a.primary{background:var(--accent);color:var(--on);padding:.6rem 1.15rem;border-radius:4px}
nav a.primary:hover{text-decoration:none;opacity:.9}
.ex{margin:2.75rem 0 0;padding-top:1.5rem;border-top:1px solid var(--line)}
.ex p{margin:0 0 .4rem;color:var(--muted);font-size:.9rem}
.ex a{font:.85rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow-wrap:anywhere}
.ex code{font:600 .85rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--code);padding:.1em .4em;border-radius:3px;white-space:nowrap}
footer{margin-top:3.5rem;padding-top:1.25rem;border-top:1px solid var(--line);color:var(--muted);font-size:.85rem}
footer p{margin:0}
@media(max-width:34rem){h1{font-size:2.1rem}body{padding-top:2.5rem}}
"""

FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="12" fill="#12325a"/>
<path d="M13 46 L26 34 L35 40 L51 19" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="51" cy="19" r="4" fill="#fff"/>
</svg>
"""


def index_html(index: dict, cur: dict) -> str:
    """Forsiden: kort præsentation og vej ind til træet på /api/, som er dokumentationen."""
    e = html.escape
    slug = "globale-aktier-developed-markets"
    a = cur["horisonter"][DEFAULT_HORIZON]["aktivklasser"][slug]
    path = f"api/current/{slug}.json"
    return f"""<!doctype html>
<html lang="da"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Afkastforventninger – API</title>
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<style>{INDEX_CSS}</style>
<p class="over">Uofficielt API</p>
<h1>Afkastforventninger</h1>
<p class="lead">Tallene fra <a href="https://afkastforventninger.dk/afkastforventninger">Rådet for Afkastforventninger</a>
som decimaltal på faste adresser. Dette er et uofficielt API (uden lovning om korrekthed) lavet på baggrund af rådets Excel-ark (som stadig er den officielle kilde).</p>
<p class="by">Lavet af <a href="https://simplesystemer.dk">Simple Systemer</a>.</p>
<nav><a class="primary" href="api/">Åbn API-træet</a><a href="openapi.json">OpenAPI-skema</a>
<a href="https://github.com/simontjell/afkastforventninger">Kildekode</a></nav>
<div class="ex">
<p>Eksempel: {e(a['navn'])}, år {e(DEFAULT_HORIZON)}, {cur['halvaar']}. halvår {cur['aar']}</p>
<a href="{e(path)}">{e(BASE_URL)}/{e(path)}</a> → <code>{fmt(a['afkast'])}</code>
</div>
<footer><p>Data opdateres dagligt fra afkastforventninger.dk. Senest bygget {e(index['bygget'][:16].replace('T', ' '))} UTC.</p></footer>
</html>
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
    for d in data.values():
        for h in d["horisonter"].values():
            for slug, a in h["aktivklasser"].items():
                LABELS[slug] = a["navn"]
        LABELS[str(d["aar"])] = f"forventninger for {d['aar']}"
    trees = {key: write_period(API / str(d["aar"]) / f"h{d['halvaar']}", d) for key, d in data.items()}
    n = sum(len(endpoints(d)) for d in data.values())
    full: dict = {"latest": write_period(API / "latest", data[latest]),
                  "current": write_period(API / "current", data[current])}
    for key in sorted(data, reverse=True):
        full.setdefault(str(data[key]["aar"]), {})[f"h{data[key]['halvaar']}"] = trees[key]
    for value in full.values():
        if "h1" in value or "h2" in value:
            ordered_halves = dict(sorted(value.items()))
            value.clear(); value.update(ordered_halves)

    # Niveauerne over halvårene følger samme mønster: X/ er en oversigt, X.json er alt under X.
    def dump(path: Path, obj) -> None:
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")

    everything: dict = {"latest": data[latest], "current": data[current]}
    for year in sorted({d["aar"] for d in data.values()}, reverse=True):
        halves = {f"h{d['halvaar']}": d for d in data.values() if d["aar"] == year}
        halves = dict(sorted(halves.items()))
        everything[str(year)] = halves
        (API / str(year) / "index.html").write_text(
            listing_html(API / str(year), {h: {} for h in halves}))
        dump(API / f"{year}.json", halves)
    (API / "index.html").write_text(tree_html(full))
    dump(SITE / "api.json", everything)

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
    (SITE / "index.html").write_text(index_html(index, data[current]))
    (SITE / "favicon.svg").write_text(FAVICON)
    (SITE / "404.html").write_text(
        "<!doctype html><meta charset=utf-8><title>404</title>"
        "<p>Ukendt sti. Se <a href='/afkastforventninger/'>forsiden</a> eller <a href='/afkastforventninger/api/'>/api/</a>.</p>\n")
    print(f"{len(data)} halvår, {n} tal skrevet til {SITE.name}/ "
          f"(latest={latest}, current={current})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
