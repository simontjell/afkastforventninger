"""Bygger det statiske API i _site/ ud fra regnearkene i kilder/.

Hvert tal skrives som tre filer: <sti>.html, <sti>.txt og <sti>.json.
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

from .parse import DEFAULT_HORIZON, HORIZONS, parse_workbook

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


def path_tree(data: dict, latest: str, current: str) -> dict:
    """Alle gyldige stier som et træ til URL-byggeren på forsiden.

    Bladene er None. Halvår med helt ens stier deler ét undertræ ("former"),
    som der henvises til med et indeks.
    """
    shapes: list[dict] = []
    keys: list[str] = []

    def order(item):
        name, child = item
        if name in HORIZONS:
            return (0, HORIZONS.index(name), name)
        return (1 if child is not None else 2, 0, name)

    def sort(node):
        return {k: (sort(v) if v is not None else None)
                for k, v in sorted(node.items(), key=order)}

    def shape(d: dict) -> int:
        tree: dict = {}
        for path in endpoints(d):
            node = tree
            *dirs, leaf = path.split("/")
            for seg in dirs:
                node = node.setdefault(seg, {})
            node[leaf] = None
        tree = {**sort(tree), ".json": None}
        key = json.dumps(tree, sort_keys=True)
        if key not in keys:
            keys.append(key)
            shapes.append(tree)
        return keys.index(key)

    root: dict = {"latest": shape(data[latest]), "current": shape(data[current])}
    for k in sorted(data, reverse=True):
        d = data[k]
        root.setdefault(str(d["aar"]), {})[f"h{d['halvaar']}"] = shape(d)
    for year in root.values():
        if isinstance(year, dict):
            year.update(sorted(year.items()))
    return {"rod": root, "former": shapes}


BUILDER_JS = r"""
(function () {
  var T = JSON.parse(document.getElementById('stier').textContent);
  var row = document.getElementById('byg'), out = document.getElementById('url'),
      val = document.getElementById('svar');
  var base = new URL('.', location.href).href;
  var want = ['latest', 'globale-aktier-developed-markets'], fmt = '';
  var labels = {'.json': 'alt (.json)'};
  function node(n) { return typeof n === 'number' ? T.former[n] : n; }
  function sel(options, value, onchange, plain) {
    var s = document.createElement('select');
    options.forEach(function (o) {
      var e = document.createElement('option');
      e.value = o; e.textContent = plain ? (o || '(ingen endelse)') : (labels[o] || o);
      s.appendChild(e);
    });
    s.value = value; s.onchange = onchange;
    return s;
  }
  function sep(t) {
    var e = document.createElement('span'); e.className = 'p'; e.textContent = t;
    return e;
  }
  function render() {
    row.textContent = '';
    var n = T.rod, path = [], depth = 0;
    while (n) {
      var keys = Object.keys(n);
      var pick = keys.indexOf(want[depth]) >= 0 ? want[depth]
               : keys.indexOf('globale-aktier-developed-markets') >= 0
                 ? 'globale-aktier-developed-markets' : keys[0];
      want[depth] = pick;
      if (pick !== '.json') row.appendChild(sep('/'));
      row.appendChild(sel(keys, pick, (function (d) {
        return function () { want[d] = this.value; render(); };
      })(depth)));
      path.push(pick);
      n = node(n[pick]); depth++;
    }
    want.length = depth;
    var whole = path[path.length - 1] === '.json';
    if (whole) path.pop();
    else row.appendChild(sel(['', '.txt', '.json'], fmt,
      function () { fmt = this.value; render(); }, true));
    var rel = path.join('/') + (whole ? '.json' : fmt);
    out.href = rel; out.textContent = base + rel;
    val.textContent = '';
    if (!whole) fetch(path.join('/') + '.txt').then(function (r) { return r.ok ? r.text() : ''; })
      .then(function (t) { if (out.getAttribute('href') === rel && t) val.textContent = '→ ' + t.trim(); })
      .catch(function () {});
  }
  render();
})();
"""


BASE_URL = "https://simontjell.github.io/afkastforventninger"


def openapi(index: dict) -> dict:
    """OpenAPI 3.1-beskrivelse af .json-udgaverne af alle adresser."""
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
                "ét decimaltal. Skemaet beskriver .json-udgaverne; uden endelse er svaret "
                "text/html, og med .txt er det text/plain. Kun GET."),
        },
        "servers": [{"url": BASE_URL}],
        "paths": paths,
        "components": {"parameters": params},
    }


def index_html(index: dict, tree: dict) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td><a href='{p['aar']}/h{p['halvaar']}.json'>{p['aar']} h{p['halvaar']}</a></td>"
        f"<td><a href='{e(p['kilde'])}'>regneark</a></td></tr>" for p in reversed(index["perioder"]))
    assets = "".join(f"<li><code>{e(s)}</code> – {e(n)}</li>" for s, n in index["aktivklasser"].items())
    long_ = "".join(f"<li><code>{e(s)}</code> – {e(n)}</li>" for s, n in index["aktivklasser_11_plus"].items())
    metrics = "".join(f"<li><code>{e(m)}</code></li>" for m in index["noegletal"])
    stier = json.dumps(tree, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    patterns = patterns_html(index)
    return f"""<!doctype html>
<html lang="da"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Afkastforventninger – API</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}}
code,pre{{background:#f3f3f3;padding:.1em .3em;border-radius:3px}}pre{{padding:.8em;overflow-x:auto;font-size:10px}}
.byg{{background:#f3f3f3;padding:.6em .8em;border-radius:3px;display:flex;flex-wrap:wrap;align-items:center;gap:.25em;font:13px ui-monospace,monospace}}
.byg select{{font:inherit;padding:.15em .2em;max-width:100%;color:inherit;background:#fff;border:1px solid #bbb;border-radius:3px}}
.res{{font:13px ui-monospace,monospace;overflow-wrap:anywhere}}#svar{{font-weight:600;white-space:nowrap}}
.c{{color:#6a737d;font-style:italic}}.v{{color:#0550ae}}.p{{color:#cf222e}}
td{{padding:.1em 1em .1em 0}}@media(prefers-color-scheme:dark){{body{{background:#161616;color:#ddd}}code,pre,.byg{{background:#262626}}.byg select{{background:#161616;border-color:#555}}a{{color:#8ab4f8}}.c{{color:#8b949e}}.v{{color:#79c0ff}}.p{{color:#ff7b72}}}}</style>
<h1>Afkastforventninger som API</h1>
<p>Tallene fra <a href="https://afkastforventninger.dk/afkastforventninger">Rådet for Afkastforventninger</a>
som decimaltal på faste adresser. Uofficielt; regnearkene hos rådet er kilden.</p>
<h2>Byg en adresse</h2>
<div id="byg" class="byg"></div>
<p class="res"><a id="url" href="."></a> <span id="svar"></span></p>
<p>Uden endelse er svaret <code>text/html</code>; <code>.txt</code> og <code>.json</code> giver en anden content-type.</p>
<script type="application/json" id="stier">{stier}</script>
<script>{BUILDER_JS}</script>
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
    (SITE / "index.html").write_text(index_html(index, path_tree(data, latest, current)))
    (SITE / "404.html").write_text(
        "<!doctype html><meta charset=utf-8><title>404</title>"
        "<p>Ukendt sti. Se <a href='/afkastforventninger/'>oversigten</a>.</p>\n")
    print(f"{len(data)} halvår, {n} tal skrevet til {SITE.name}/ "
          f"(latest={latest}, current={current})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
