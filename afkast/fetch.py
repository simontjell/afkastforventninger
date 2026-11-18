"""Henter nye regneark fra afkastforventninger.dk til kilder/.

kilder/manifest.json holder styr på, hvilken fil der hører til hvilket halvår,
og hvilken URL den kom fra. Erstatter rådet en fil med en rettet udgave (ny
URL for samme halvår), hentes den nye, og den gamle slettes.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .parse import period_from_name

PAGE = "https://afkastforventninger.dk/afkastforventninger"
ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "kilder"
MANIFEST = SOURCES / "manifest.json"
EXTENSIONS = (".xlsx", ".xlsm")
CORRECTED = ("rettet", "korrigeret", "revideret")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._text = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._text)))
            self._href = None


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; python-urllib)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def discover(html: str) -> dict[str, str]:
    """{periode: url} for alle regneark på siden."""
    p = _Links()
    p.feed(html)
    found: dict[str, str] = {}
    for href, text in p.links:
        url = urljoin(PAGE, href)
        name = Path(urlparse(url).path).name
        if not name.lower().endswith(EXTENSIONS):
            continue
        period = period_from_name(name) or period_from_name(text)
        if period is None:
            raise SystemExit(f"Kan ikke udlede halvår for {url} ({text!r})")
        key = f"{period[0]}-h{period[1]}"
        old = found.get(key)
        # Flere filer for samme halvår: foretræk den rettede udgave.
        if old is None or (any(w in name for w in CORRECTED)
                           and not any(w in old for w in CORRECTED)):
            found[key] = url
    return found


def main() -> int:
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    found = discover(_get(PAGE).decode("utf-8", "replace"))
    if not found:
        raise SystemExit("Ingen regneark fundet på siden – er den lavet om?")
    changed = 0
    for key, url in sorted(found.items()):
        if manifest.get(key, {}).get("url") == url:
            continue
        name = f"{key}{Path(urlparse(url).path).suffix.lower()}"
        data = _get(url)
        if not data.startswith(b"PK"):
            raise SystemExit(f"{url} er ikke et xlsx-regneark")
        old = manifest.get(key, {}).get("fil")
        if old and old != name:
            (SOURCES / old).unlink(missing_ok=True)
        (SOURCES / name).write_bytes(data)
        manifest[key] = {"fil": name, "url": url,
                         "original": Path(urlparse(url).path).name}
        print(f"hentet {key}: {url}")
        changed += 1
    MANIFEST.write_text(json.dumps(dict(sorted(manifest.items())), indent=2,
                                   ensure_ascii=False) + "\n")
    print(f"{changed} ny(e) fil(er), {len(manifest)} halvår i alt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
