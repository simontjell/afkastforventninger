import json
from pathlib import Path

import openpyxl
import pytest

from afkast.build import endpoints, fmt
from afkast.parse import ParseError, parse_workbook, period_from_name

SOURCES = Path(__file__).resolve().parent.parent / "kilder"
MANIFEST = json.loads((SOURCES / "manifest.json").read_text())
GA = "globale-aktier-developed-markets"

# Globale aktier: (1-5, 6-10, 1-10) aflæst manuelt i regnearkene.
EXPECTED = {
    "2021-h1": (0.056, 0.062, 0.059),
    "2022-h1": (0.056, 0.058, 0.057),
    "2022-h2": (0.050, 0.059, 0.055),
    "2023-h1": (0.061, 0.063, 0.062),
    "2023-h2": (0.074, 0.075, 0.074),
    "2024-h1": (0.069, 0.074, 0.071),
    "2024-h2": (0.065, 0.071, 0.068),
    "2025-h1": (0.068, 0.072, 0.070),
    "2025-h2": (0.062, 0.074, 0.068),
    "2026-h1": (0.061, 0.073, 0.067),
    "2026-h2": (0.067, 0.077, 0.072),
    "2027-h1": (0.066, 0.077, 0.071),
}


def load(key):
    return parse_workbook(SOURCES / MANIFEST[key]["fil"], int(key[:4]), int(key[-1]))


@pytest.mark.parametrize("key", sorted(MANIFEST))
def test_every_source_parses(key):
    d = load(key)
    assert len(d["horisonter"]["1-10"]["aktivklasser"]) == 10
    assert endpoints(d)  # ingen stikonflikter


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_known_values(key):
    d = load(key)
    got = tuple(d["horisonter"][h]["aktivklasser"][GA]["afkast"] for h in ("1-5", "6-10", "1-10"))
    assert got == EXPECTED[key]


def test_old_and_new_layout_give_same_shape():
    old, new = load("2021-h1"), load("2027-h1")
    # 2021: standardafvigelse og korrelationer står på hver horisontfane.
    # 2027: de står på en fælles fane.
    for d in (old, new):
        a = d["horisonter"]["1-5"]["aktivklasser"][GA]
        assert {"afkast", "standardafvigelse", "afkast-unhedged", "investeringsomkostninger"} <= set(a)
        assert d["horisonter"]["1-5"]["korrelationer"][GA]["hedgefonde"] > 0
    assert old["horisontafkast"] is None and new["horisontafkast"] == 0.0312
    assert "illikvide-aktiver" in new["horisonter"]["11-plus"]["aktivklasser"]


def _rearranged(tmp_path, mutate=None):
    """Kopi af nyeste regneark, hvor alt er flyttet 3 rækker ned og 2 kolonner
    til højre, fanerne står i omvendt rækkefølge, og overskrifterne har fået
    fodnotetegn."""
    wb = openpyxl.load_workbook(SOURCES / MANIFEST["2027-h1"]["fil"], data_only=True)
    for ws in wb.worksheets:
        for rng in list(ws.merged_cells.ranges):  # flytter ikke med ved insert
            ws.unmerge_cells(str(rng))
        ws.insert_rows(1, 3)
        ws.insert_cols(1, 2)
        for row in ws.iter_rows():
            for c in row:
                if c.value == "Afkast":
                    c.value = " Afkast* "
    wb._sheets.reverse()
    if mutate:
        mutate(wb)
    path = tmp_path / "afkastforventninger-2-halvaar-2031.xlsx"
    wb.save(path)
    return path


def test_survives_moved_tables(tmp_path):
    d = parse_workbook(_rearranged(tmp_path))
    ref = load("2027-h1")
    assert (d["aar"], d["halvaar"]) == (2031, 2)
    assert d["horisonter"] == ref["horisonter"]
    assert d["inflation"] == ref["inflation"]


def test_unknown_asset_class_fails_loudly(tmp_path):
    def rename(wb):
        for row in wb["1-5 år"].iter_rows():
            for c in row:
                if c.value == "Hedgefonde":
                    c.value = "Kryptoaktiver"
    with pytest.raises(ParseError, match="ukendt aktivklasse"):
        parse_workbook(_rearranged(tmp_path, rename))


def test_percent_instead_of_fraction_fails_loudly(tmp_path):
    def percent(wb):
        for row in wb["1-10 år"].iter_rows():
            for c in row:
                if isinstance(c.value, float):
                    c.value *= 100
    with pytest.raises(ParseError, match="uden for"):
        parse_workbook(_rearranged(tmp_path, percent))


@pytest.mark.parametrize("name,expected", [
    ("afkastforventninger-1-halvar-2021.xlsx", (2021, 1)),
    ("afkastforventninger-foerste-halvaar-2022.xlsx", (2022, 1)),
    ("afkastforventninger-2-halvar-2021-fejlrettet.xlsx", (2021, 2)),
    ("afkastforventninger-1-halvaar-2026-rettet.xlsx", (2026, 1)),
    ("Afkastforventninger 2. halvår 2028", (2028, 2)),
    ("afkast-2029-h1.xlsx", (2029, 1)),
    ("notat.xlsx", None),
])
def test_period_from_name(name, expected):
    assert period_from_name(name) == expected


def test_fmt():
    assert [fmt(v) for v in (0.066, 0.1, 0.0, -0.012, 0.0342)] == ["0.066", "0.1", "0", "-0.012", "0.0342"]
