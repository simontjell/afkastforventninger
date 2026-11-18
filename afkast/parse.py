"""Læser rådets regneark og returnerer én ensartet datastruktur pr. halvår.

Regnearkene skifter layout over tid (faner flytter, kolonner kommer til,
overskrifter får fodnotetegn, tabeller rykker et par rækker). Derfor bruges der
ingen faste celleadresser. I stedet:

  * faner genkendes på deres navn ("1-5 år", "Inflation", ...),
  * kolonner genkendes på deres overskrift ("Afkast", "Fees i fonde", ...),
  * rækker genkendes på aktivklassens navn.

Alt, der ikke kan genkendes, giver en ParseError frem for et gæt. Hellere et
fejlet byg end et forkert tal i API'et.
"""
from __future__ import annotations

import re
from pathlib import Path

import openpyxl

DEFAULT_HORIZON = "1-10"
HORIZONS = ("1-5", "6-10", "1-10", "11-plus")

# Kendte aktivklasser. Venstre side er slug af navnet i regnearket, højre side
# er den slug, API'et bruger. Omdøber rådet en aktivklasse, tilføjes det nye
# navn her, så URL'erne forbliver stabile.
ASSETS = {
    "stats-og-realkreditobligationer": "stats-og-realkreditobligationer",
    "investment-grade-obligationer": "investment-grade-obligationer",
    "high-yield-obligationer": "high-yield-obligationer",
    "emerging-markets-statsobligationer": "emerging-markets-statsobligationer",
    "globale-aktier-developed-markets": "globale-aktier-developed-markets",
    "emerging-markets-aktier": "emerging-markets-aktier",
    "private-equity": "private-equity",
    "infrastruktur": "infrastruktur",
    "ejendomme": "ejendomme",
    "hedgefonde": "hedgefonde",
    # 11+ år
    "obligationer": "obligationer",
    "aktier": "aktier",
    "illikvide-aktiver": "illikvide-aktiver",
}

# Kolonneoverskrift (slug) -> nøgletal i API'et.
METRICS = {
    "afkast": "afkast",
    "standardafvigelse": "standardafvigelse",
    "fees-i-fonde": "fees-i-fonde",
    "afkast-unhedged": "afkast-unhedged",
    "loebende-afkast": "loebende-afkast",
    "kursaendring": "kursaendring",
    "investerings-omkostninger": "investeringsomkostninger",
    "investeringsomkostninger": "investeringsomkostninger",
}


class ParseError(Exception):
    pass


def slugify(text: str) -> str:
    s = str(text).strip().lower()
    for a, b in (("æ", "ae"), ("ø", "oe"), ("å", "aa"), ("é", "e"), ("ü", "u")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def period_from_name(name: str) -> tuple[int, int] | None:
    """(år, halvår) ud fra fil- eller linknavn, fx
    'afkastforventninger-foerste-halvaar-2022.xlsx' -> (2022, 1)."""
    s = slugify(re.sub(r"\.xls\w?$", "", str(name).strip(), flags=re.I))
    words = {"1": 1, "2": 2, "foerste": 1, "andet": 2, "anden": 2, "h1": 1, "h2": 2}
    half = r"(1|2|foerste|andet|anden)-halv-?a{1,2}r"
    m = re.search(half + r"-(20\d\d)", s) or re.search(r"(h[12])-(20\d\d)", s)
    if m:
        return int(m.group(2)), words[m.group(1)]
    m = re.search(r"(20\d\d)-" + half, s) or re.search(r"(20\d\d)-(h[12])", s)
    if m:
        return int(m.group(1)), words[m.group(2)]
    return None


def _horizon(text: str) -> str | None:
    """'1-5 år', 'Kort sigt (år 1-5)', '11- år', 'Langt sigt (år 11-)' -> nøgle."""
    m = re.search(r"(\d+)\s*[-–]\s*(\d+)?", str(text))
    if not m:
        return None
    key = f"{m.group(1)}-{m.group(2)}" if m.group(2) else f"{m.group(1)}-plus"
    return key if key in HORIZONS else None


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return round(float(v), 6)


def _grid(ws) -> dict[tuple[int, int], object]:
    """Alle ikke-tomme celler som {(række, kolonne): værdi}."""
    out = {}
    for row in ws.iter_rows():
        for c in row:
            v = c.value
            if isinstance(v, str):
                v = v.strip()
                if not v:
                    continue
            if v is not None:
                out[(c.row, c.column)] = v
    return out


def _tables(grid) -> list[dict]:
    """Finder tabeller af formen

        (navn)   ...   Overskrift A   Overskrift B
        Række 1  ...   0.01           0.02

    og returnerer en liste af {række-navn: {nøgletal: værdi}} – én pr.
    overskriftsrække. Rækkens navn er første tekstcelle til venstre for den
    første genkendte overskrift.
    """
    headers: dict[int, dict[int, str]] = {}
    for (r, c), v in grid.items():
        if isinstance(v, str) and slugify(v) in METRICS:
            headers.setdefault(r, {})[c] = METRICS[slugify(v)]
    rows = sorted({r for r, _ in grid})
    tables = []
    hrows = sorted(headers)
    for i, hr in enumerate(hrows):
        end = hrows[i + 1] if i + 1 < len(hrows) else float("inf")
        cols = headers[hr]
        first = min(cols)
        table: dict[str, dict] = {}
        for r in rows:
            if not hr < r < end:
                continue
            label = next(
                (grid[(r, c)] for c in range(1, first)
                 if isinstance(grid.get((r, c)), str)), None)
            if label is None:
                continue
            vals = {m: _num(grid.get((r, c))) for c, m in cols.items()}
            vals = {m: v for m, v in vals.items() if v is not None}
            if vals:
                table[label] = vals
        if table:
            tables.append(table)
    return tables


def _asset(label: str, where: str) -> str:
    s = slugify(label)
    if s not in ASSETS:
        raise ParseError(
            f"{where}: ukendt aktivklasse {label!r} (slug {s!r}). "
            "Tilføj den til ASSETS i afkast/parse.py.")
    return ASSETS[s]


def _asset_table(tables, where) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for t in tables:
        for label, vals in t.items():
            slug = _asset(label, where)
            out.setdefault(slug, {"navn": label}).update(vals)
    return out


def _corr_matrix(grid, where) -> dict | None:
    """Øvre trekantsmatrix med nummererede rækker og kolonner (1..n)."""
    by_row: dict[int, dict[int, object]] = {}
    for (r, c), v in grid.items():
        by_row.setdefault(r, {})[c] = v
    for hr in sorted(by_row):
        cells = by_row[hr]
        cols = sorted(c for c, v in cells.items() if isinstance(v, int) and not isinstance(v, bool))
        # kolonnehoved: 1,2,3,... i sammenhængende celler
        run = []
        for c in cols:
            if cells[c] == len(run) + 1 and (not run or c == run[-1] + 1):
                run.append(c)
            elif cells[c] == 1:
                run = [c]
        if len(run) < 3:
            continue
        labels: dict[int, str] = {}
        values: dict[tuple[int, int], float] = {}
        for r in sorted(x for x in by_row if x > hr):
            row = by_row[r]
            idx = next((row[c] for c in sorted(row) if c < run[0]
                        and isinstance(row[c], int) and not isinstance(row[c], bool)), None)
            name = next((row[c] for c in sorted(row) if c < run[0]
                         and isinstance(row[c], str)), None)
            if idx is None or name is None or not 1 <= idx <= len(run):
                continue
            labels[idx] = _asset(name, where)
            for j, c in enumerate(run, start=1):
                v = _num(row.get(c))
                if v is not None:
                    values[(idx, j)] = v
        if len(labels) != len(run):
            continue
        out = {a: {} for a in labels.values()}
        for (i, j), v in values.items():
            out[labels[i]][labels[j]] = v
            out[labels[j]][labels[i]] = v
        for a in out:
            if out[a].get(a) != 1.0 or len(out[a]) != len(run):
                raise ParseError(f"{where}: korrelationsmatricen er ufuldstændig for {a!r}")
        return out
    return None


def _corr_long(grid, assets, where) -> dict | None:
    """Korrelationer på 11+ fanen: enten en matrix med aktivklassenavne som
    kolonneoverskrifter, eller (ældre filer) ét tal for aktier/obligationer."""
    for (r, c), v in grid.items():
        if isinstance(v, str) and slugify(v).startswith("korrelation-mellem"):
            val = next((_num(grid[(rr, c)]) for rr in range(r + 1, r + 6)
                        if _num(grid.get((rr, c))) is not None), None)
            if val is None:
                return None
            return {"aktier": {"aktier": 1.0, "obligationer": val},
                    "obligationer": {"obligationer": 1.0, "aktier": val}}
    for hr in sorted({r for r, _ in grid}):
        cols = {c: ASSETS[slugify(v)] for (r, c), v in grid.items()
                if r == hr and isinstance(v, str) and ASSETS.get(slugify(v)) in assets}
        if len(cols) < 2:
            continue
        out = {a: {} for a in cols.values()}
        for (r, c), v in grid.items():
            if r <= hr or not isinstance(v, str) or ASSETS.get(slugify(v)) not in out:
                continue
            a = ASSETS[slugify(v)]
            for cc, b in cols.items():
                if cc > c and _num(grid.get((r, cc))) is not None:
                    out[a][b] = out[b][a] = _num(grid[(r, cc)])
        # Enkelte ældre filer mangler et tal i matricen; behold det, der er.
        if any(b != a for a in out for b in out[a]):
            return out
    return None


def parse_workbook(path: str | Path, year: int | None = None, half: int | None = None) -> dict:
    path = Path(path)
    if year is None or half is None:
        p = period_from_name(path.name)
        if p is None:
            raise ParseError(f"{path.name}: kan ikke udlede år/halvår af filnavnet")
        year, half = p
    wb = openpyxl.load_workbook(path, data_only=True)

    horizons: dict[str, dict] = {}
    shared_std: dict[str, dict] = {}
    shared_corr = None
    costs: list[dict] = []
    inflation: dict[str, float] = {}
    horisontafkast = None
    ignored = []

    for ws in wb.worksheets:
        title = slugify(ws.title)
        where = f"{path.name} [{ws.title}]"
        grid = _grid(ws)
        hz = _horizon(ws.title)
        if hz and "aar" in title:
            assets = _asset_table(_tables(grid), where)
            if hz == "11-plus":
                corr = _corr_long(grid, set(assets), where)
            else:
                corr = _corr_matrix(grid, where)
            horizons[hz] = {"aktivklasser": assets, "korrelationer": corr}
        elif title.startswith("standardafv"):
            shared_std = _asset_table(_tables(grid), where)
            shared_corr = _corr_matrix(grid, where)
        elif title.startswith("inflation"):
            col = next((c for (r, c), v in sorted(grid.items())
                        if isinstance(v, str) and slugify(v) == "inflation"), None)
            for (r, c), v in sorted(grid.items()):
                if isinstance(v, str) and _horizon(v) and col and c < col:
                    n = _num(grid.get((r, col)))
                    if n is not None:
                        inflation[_horizon(v)] = n
        elif title.startswith("horisontafkast"):
            nums = [_num(v) for _, v in sorted(grid.items()) if _num(v) is not None]
            if len(nums) != 1:
                raise ParseError(f"{where}: forventede præcis ét tal, fandt {nums}")
            horisontafkast = nums[0]
        elif title.startswith("inv") and "omk" in title:
            costs = [_asset_table([t], where) for t in _tables(grid)]
        else:
            ignored.append(ws.title)

    # Fælles standardafvigelser/korrelationer ("alle perioder") og
    # investeringsomkostninger flettes ind på hver horisont.
    for hz, h in horizons.items():
        assets = h["aktivklasser"]
        if hz != "11-plus":
            for slug, vals in shared_std.items():
                if slug in assets and "standardafvigelse" in vals:
                    assets[slug].setdefault("standardafvigelse", vals["standardafvigelse"])
            if h["korrelationer"] is None:
                h["korrelationer"] = shared_corr
        for table in costs:
            if set(table) <= set(assets):
                for slug, vals in table.items():
                    if "investeringsomkostninger" in vals:
                        assets[slug]["investeringsomkostninger"] = vals["investeringsomkostninger"]

    result = {
        "periode": f"{year}-h{half}",
        "aar": year,
        "halvaar": half,
        "horisonter": {h: horizons[h] for h in HORIZONS if h in horizons},
        "inflation": {h: inflation[h] for h in HORIZONS if h in inflation},
        "horisontafkast": horisontafkast,
        "ignorerede_faner": ignored,
    }
    validate(result, path.name)
    return result


def validate(d: dict, name: str) -> None:
    def fail(msg):
        raise ParseError(f"{name}: {msg}")

    hs = d["horisonter"]
    missing = [h for h in HORIZONS if h not in hs]
    if missing:
        fail(f"mangler horisont(er) {missing}")
    base = set(hs["1-10"]["aktivklasser"])
    if len(base) < 8:
        fail(f"kun {len(base)} aktivklasser fundet på 1-10 år")
    for h in ("1-5", "6-10"):
        if set(hs[h]["aktivklasser"]) != base:
            fail(f"aktivklasserne på {h} år afviger fra 1-10 år")
    if not {"aktier", "obligationer"} <= set(hs["11-plus"]["aktivklasser"]):
        fail("11+ år mangler aktier/obligationer")
    for h, hd in hs.items():
        for slug, a in hd["aktivklasser"].items():
            if "afkast" not in a:
                fail(f"{h}/{slug}: mangler afkast")
            if "standardafvigelse" not in a:
                fail(f"{h}/{slug}: mangler standardafvigelse")
            for m, v in a.items():
                if m == "navn":
                    continue
                lo, hi = (0, 1) if m == "standardafvigelse" else (-0.25, 0.5)
                if not lo <= v <= hi:
                    fail(f"{h}/{slug}/{m}: {v} ligger uden for [{lo}, {hi}] – "
                         "er formatet ændret (fx procent i stedet for decimaltal)?")
        if hd["korrelationer"] is None:
            fail(f"{h}: ingen korrelationer fundet")
        if h != "11-plus" and set(hd["korrelationer"]) != base:
            fail(f"{h}: korrelationsmatricen dækker ikke alle aktivklasser")
    if set(d["inflation"]) != set(HORIZONS):
        fail(f"inflation fundet for {sorted(d['inflation'])}, forventede alle horisonter")
