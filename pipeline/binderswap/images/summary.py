"""Summarize an image manifest as Markdown: counts per language, and sets with missing images.

    python -m binderswap.images.summary [--images build/images] [--catalog build/catalog/catalog.sqlite]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def render(images: Path, catalog: Path | None, top: int = 25) -> str:
    con = sqlite3.connect(images / "manifest.sqlite")
    lines = ["## Card images", "", "| Language | Downloaded | Missing upstream (404) | Errors |", "|---|---|---|---|"]
    rows = con.execute("SELECT substr(card_id, 1, instr(card_id, '/') - 1) AS lang, "
                       "sum(status='ok'), sum(status='missing'), sum(status='error') FROM images GROUP BY lang")
    for lang, ok, missing, err in rows:
        lines.append(f"| {lang} | {ok} | {missing} | {err} |")
    names = {}
    if catalog and catalog.exists():
        names = dict(sqlite3.connect(catalog).execute("SELECT id, name FROM sets"))
    counts: dict[str, list[int]] = {}
    for card_id, status in con.execute("SELECT card_id, status FROM images"):
        c = counts.setdefault(card_id.rsplit("/", 1)[0], [0, 0])
        c[0] += status == "missing"
        c[1] += 1
    by_set = sorted(((sid, m, t) for sid, (m, t) in counts.items() if m), key=lambda r: (-r[1], r[0]))[:top]
    if by_set:
        lines += ["", f"### Sets with the most missing images (top {top})", "",
                  "| Set | Name | Missing | Cards |", "|---|---|---|---|"]
        lines += [f"| `{sid}` | {names.get(sid, '')} | {m} | {t} |" for sid, m, t in by_set]
    errors = con.execute("SELECT card_id, error FROM images WHERE status='error' LIMIT 10").fetchall()
    if errors:
        lines += ["", "### Errors (first 10)", "", "| Card | Error |", "|---|---|"]
        lines += [f"| `{cid}` | {err} |" for cid, err in errors]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", type=Path, default=Path("build/images"))
    ap.add_argument("--catalog", type=Path, default=Path("build/catalog/catalog.sqlite"))
    args = ap.parse_args(argv)
    print(render(args.images, args.catalog))
    return 0


if __name__ == "__main__":
    sys.exit(main())
