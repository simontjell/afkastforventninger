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


def patterns_html(index: dict) -> str:
    """Stimønstrene med kommentar over hver og simpel syntaksfarvning."""
    items = [
        (f"afkast, {DEFAULT_HORIZON} år", "/api/{år}/h{1|2}/{aktivklasse}.json"),
        ("afkast for en bestemt horisont", "/api/{år}/h{1|2}/{horisont}/{aktivklasse}.json"),
        ("et bestemt nøgletal", "/api/{år}/h{1|2}/{horisont}/{nøgletal}/{aktivklasse}.json"),
        ("inflationsforventning", "/api/{år}/h{1|2}/inflation/{horisont}.json"),
        ("alle tal under en mappe som JSON: mappens navn + .json", "/api/{år}/h{1|2}/inflation.json"),
        ("oversigt med links til det underliggende: afslut med /", "/api/{år}/h{1|2}/inflation/"),
        ("horisontafkast", "/api/{år}/h{1|2}/horisontafkast.json"),
        ("alt for halvåret, inkl. korrelationer", "/api/{år}/h{1|2}.json"),
        (f"nyeste offentliggjorte ({index['latest']})", "/api/latest/…"),
        (f"gældende i dag ({index['current']})", "/api/current/…"),
        ("start her og klik dig ned gennem det hele", "/api/"),
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
        ("Start her: oversigt med links til alle halvår", "api/"),
        (f"Afkast på globale aktier, {DEFAULT_HORIZON} år, {navn}", f"api/{per}/globale-aktier-developed-markets.json"),
        (f"Samme, men på horisonten 1-5 år", f"api/{per}/1-5/globale-aktier-developed-markets.json"),
        (f"Standardafvigelse på hedgefonde, 6-10 år, {navn}", f"api/{per}/6-10/standardafvigelse/hedgefonde.json"),
        (f"Fees i fonde for private equity, 1-10 år, {navn}", f"api/{per}/1-10/fees-i-fonde/private-equity.json"),
        (f"Afkast på aktier fra år 11 og frem, {navn}", f"api/{per}/11-plus/aktier.json"),
        (f"Inflationsforventning, 1-5 år, {navn}", f"api/{per}/inflation/1-5.json"),
        (f"Inflationsforventning for alle horisonter, {navn}", f"api/{per}/inflation.json"),
        (f"Afkast for alle aktivklasser, 1-5 år, {navn}", f"api/{per}/1-5/afkast.json"),
        ("Samme tal i det halvår, der gælder i dag", "api/current/1-5/afkast.json"),
        (f"Oversigt med links til alt under {navn}", f"api/{per}/"),
        (f"Horisontafkast, {navn}", f"api/{per}/horisontafkast.json"),
        ("Afkast på ejendomme i det nyeste offentliggjorte halvår", "api/latest/ejendomme.json"),
        ("Afkast på ejendomme i det halvår, der gælder i dag", "api/current/ejendomme.json"),
        (f"Alt for {navn}, inkl. korrelationer", f"api/{per}.json"),
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
    paths: dict = {"/index.json": {"get": {
        "operationId": "getIndex", "summary": "Halvår, aktivklasser, horisonter og nøgletal.",
        "responses": obj("Oversigt.")}}}
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
                "(https://afkastforventninger.dk/afkastforventninger). Hver adresse svarer med "
                "ét decimaltal (fx 0.067). Skemaet beskriver .json-adresserne, som har Content-Type "
                "application/json. En mappe afsluttet med / giver en HTML-oversigt med links. Kun GET."),
        },
        "servers": [{"url": BASE_URL}],
        "paths": paths,
        "components": {"parameters": params},
    }


INDEX_CSS = """
:root{--bg:#fbfbfa;--fg:#1c1c1a;--muted:#6f6f6a;--line:#e6e5e1;--hover:#f1f0ec;--link:#0b57a4;--pill:#eeede9;
--accent:#12325a;--code:#f3f2ee;--c:#7a7a74;--v:#0b57a4;--p:#a23b2a}
@media(prefers-color-scheme:dark){:root{--bg:#141414;--fg:#e8e6e1;--muted:#9a9891;--line:#2a2a28;--hover:#1e1e1c;--link:#8ab4f8;--pill:#262624;
--accent:#8ab4f8;--code:#1c1c1a;--c:#8b8a84;--v:#8ab4f8;--p:#e39a8c}}
*{box-sizing:border-box}
html{border-top:4px solid var(--accent)}
body{font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;max-width:52rem;margin:0 auto;padding:3rem 1rem 4rem;color:var(--fg);background:var(--bg)}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
header{padding-bottom:2rem;border-bottom:1px solid var(--line)}
.over{font-size:.75rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:0 0 .6rem}
h1{font:400 2.5rem/1.15 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;letter-spacing:-.01em;margin:0 0 1rem;color:var(--accent)}
.lead{max-width:40rem;margin:0 0 .5rem}
.by{color:var(--muted);font-size:.9rem;margin:0}
nav{display:flex;flex-wrap:wrap;gap:.5rem 1.5rem;margin-top:1.5rem;font-size:.95rem}
nav a{font-weight:600}
section{padding:2.25rem 0 0}
h2{font:400 1.45rem/1.25 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;margin:0 0 .25rem;color:var(--accent)}
.note{color:var(--muted);font-size:.9rem;margin:0 0 1rem;max-width:40rem}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.95rem}
th{font-size:.72rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);text-align:left;
padding:.5rem .75rem;border-bottom:1px solid var(--fg);white-space:nowrap}
td{padding:.5rem .75rem;border-bottom:1px solid var(--line);vertical-align:baseline}
th:first-child,td:first-child{padding-left:0}th:last-child,td:last-child{padding-right:0}
th.n,td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.n a{color:inherit}
tbody tr:hover{background:var(--hover)}
tfoot td{border-top:1px solid var(--fg);border-bottom:0;color:var(--muted)}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.85em}
code{background:var(--code);padding:.1em .35em;border-radius:3px}
td code{white-space:nowrap}
pre{background:var(--code);border:1px solid var(--line);border-radius:4px;padding:1rem;overflow-x:auto;font:10px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;margin:0}
.c{color:var(--c);font-style:italic}.v{color:var(--v)}.p{color:var(--p)}
.ex{list-style:none;margin:0;padding:0;border-top:1px solid var(--line)}
.ex li{padding:.6rem 0;border-bottom:1px solid var(--line)}
.ex br{display:none}
.ex a{display:block;font:.8rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow-wrap:anywhere;margin-top:.1rem}
.ref td:first-child{width:21rem}
@media(max-width:40rem){h1{font-size:2rem}body{padding-top:2rem}table{font-size:.82rem}th,td{padding:.45rem .22rem}th{letter-spacing:0;font-size:.62rem}.ref td:first-child{width:auto}}
h3{font-size:.72rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:1.5rem 0 0}
footer{margin-top:3rem;padding-top:1.25rem;border-top:1px solid var(--line);color:var(--muted);font-size:.85rem}
footer p{margin:0 0 .35rem;max-width:44rem}
"""


FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="12" fill="#12325a"/>
<path d="M13 46 L26 34 L35 40 L51 19" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="51" cy="19" r="4" fill="#fff"/>
</svg>
"""


def pct(v: float) -> str:
    return f"{v * 100:.1f}".replace(".", ",")


def index_html(index: dict, cur: dict) -> str:
    e = html.escape
    navn = f"{cur['halvaar']}. halvår {cur['aar']}"
    hs = cur["horisonter"]

    def cell(path: str, v) -> str:
        if v is None:
            return "<td class=n></td>"
        return f"<td class=n><a href='api/current/{e(path)}.json' title='{fmt(v)}'>{pct(v)}</a></td>"

    main_rows = "".join(
        f"<tr><td>{e(a['navn'])}</td>"
        + "".join(cell(f"{h}/{slug}", hs[h]["aktivklasser"][slug]["afkast"]) for h in ("1-5", "6-10", "1-10"))
        + cell(f"1-10/standardafvigelse/{slug}", a.get("standardafvigelse")) + "</tr>"
        for slug, a in hs["1-10"]["aktivklasser"].items())
    infl = cur["inflation"]
    infl_row = ("<tr><td>Inflation</td>"
                + "".join(cell(f"inflation/{h}", infl.get(h)) for h in ("1-5", "6-10", "1-10"))
                + "<td class=n></td></tr>")
    long_rows = "".join(
        f"<tr><td>{e(a['navn'])}</td>" + cell(f"11-plus/{slug}", a["afkast"])
        + cell(f"11-plus/standardafvigelse/{slug}", a.get("standardafvigelse")) + "</tr>"
        for slug, a in hs["11-plus"]["aktivklasser"].items())
    long_rows += f"<tr><td>Inflation</td>{cell('inflation/11-plus', infl.get('11-plus'))}<td class=n></td></tr>"

    def ref(items) -> str:
        return "".join(f"<tr><td><code>{e(s)}</code></td><td>{e(n)}</td></tr>" for s, n in items)

    assets = ref(list(index["aktivklasser"].items()) + list(index["aktivklasser_11_plus"].items()))
    horizons = ref((h, LABELS.get(h, h)) for h in index["horisonter"])
    metrics = ref((m, LABELS.get(m, m)) for m in index["noegletal"])
    periods = "".join(
        f"<tr><td>{p['halvaar']}. halvår {p['aar']}</td>"
        f"<td><a class=mono href='api/{p['aar']}/h{p['halvaar']}/'>api/{p['aar']}/h{p['halvaar']}/</a></td>"
        f"<td><a class=mono href='api/{p['aar']}/h{p['halvaar']}.json'>.json</a></td>"
        f"<td><a href='{e(p['kilde'])}'>Rådets regneark</a></td></tr>"
        for p in reversed(index["perioder"]))
    examples = examples_html(index)
    patterns = patterns_html(index)
    return f"""<!doctype html>
<html lang="da"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Afkastforventninger – API</title>
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<style>{INDEX_CSS}</style>
<header>
<p class="over">Uofficielt API</p>
<h1>Afkastforventninger</h1>
<p class="lead">Tallene fra <a href="https://afkastforventninger.dk/afkastforventninger">Rådet for Afkastforventninger</a>
som decimaltal på faste adresser. Dette er et uofficielt API (uden lovning om korrekthed) lavet på baggrund af rådets Excel-ark (som stadig er den officielle kilde).</p>
<p class="by">Lavet af <a href="https://simplesystemer.dk">Simple Systemer</a>.</p>
<nav><a href="api/">API-oversigt</a><a href="openapi.json">OpenAPI-skema</a><a href="index.json">index.json</a>
<a href="https://github.com/simontjell/afkastforventninger">Kildekode</a></nav>
</header>

<section>
<h2>Gældende forventninger</h2>
<p class="note">{e(navn)}. Forventet årligt afkast og standardafvigelse i pct. Hvert tal linker til sin adresse i API'et.</p>
<div class="scroll"><table>
<thead><tr><th>Aktivklasse</th><th class=n>År 1-5</th><th class=n>År 6-10</th><th class=n>År 1-10</th><th class=n>Std.afv.</th></tr></thead>
<tbody>{main_rows}</tbody>
<tfoot>{infl_row}</tfoot>
</table></div>
<h3>År 11 og frem</h3>
<div class="scroll"><table>
<thead><tr><th>Aktivklasse</th><th class=n>Afkast</th><th class=n>Std.afv.</th></tr></thead>
<tbody>{long_rows}</tbody>
</table></div>
</section>

<section>
<h2>Adresser</h2>
<p class="note">Svaret er tallet alene (<code>0.067</code> = 6,7 %). Alle data er JSON med <code>application/json</code>. En mappe afsluttet med <code>/</code> viser links til det, der ligger under den.</p>
<pre>{patterns}</pre>
</section>

<section>
<h2>Eksempler</h2>
<ul class="ex">{examples}</ul>
</section>

<section>
<h2>Reference</h2>
<div class="ref">
<h3>Aktivklasser</h3><div class="scroll"><table><tbody>{assets}</tbody></table></div>
<h3>Horisonter</h3><div class="scroll"><table><tbody>{horizons}</tbody></table></div>
<h3>Nøgletal</h3><div class="scroll"><table><tbody>{metrics}</tbody></table></div>
</div>
</section>

<section>
<h2>Halvår</h2>
<div class="scroll"><table>
<thead><tr><th>Halvår</th><th>Oversigt</th><th>Alt</th><th>Kilde</th></tr></thead>
<tbody>{periods}</tbody>
</table></div>
</section>

<footer>
<p>Uofficielt API uden lovning om korrekthed. Rådets regneark er den officielle kilde.</p>
<p>Data opdateres dagligt fra afkastforventninger.dk. Senest bygget {e(index['bygget'][:16].replace('T', ' '))} UTC.</p>
</footer>
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
    (SITE / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
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
