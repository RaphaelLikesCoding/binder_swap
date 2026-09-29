"""Binder-page photos built from real card art, with exact ground truth.

    python -m binderswap.realpages --pages 40 --out build/realpages

Every page test in this repo runs on procedurally generated fake cards, which
share no property with a real card that matters: not the art, not the frame,
not the printed number. The recognition numbers they produce are therefore
about the generator, not about Pokemon cards.

This renders the same simulated photo -- plastic pockets, perspective, sleeve
glare, sensor noise -- around real downloaded card images, and writes a
``labels.json`` in the format ``recognition.eval`` already reads.

It is not a substitute for photographs of real binders (BLOCKERS #2): the
degradation model is ours, so it cannot tell us that the model is right. What
it does give, which no scraped image can, is ground truth -- for identity *and*
for page geometry -- over as many pages and layouts as we want.

Needs build/catalog and build/images.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

from .synthetic import PageSpec, make_page

# Layouts worth exercising, with how often to pick each.
LAYOUTS = [((3, 3), 0.6), ((2, 2), 0.2), ((3, 4), 0.1), ((4, 3), 0.1)]


def card_pool(catalog: Path, images: Path, langs: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Cards that have an image on disk, grouped by set, per language."""
    man = sqlite3.connect(images / "manifest.sqlite")
    have = {cid: p for cid, p in man.execute(
        "SELECT card_id, path FROM images WHERE status='ok'")}
    con = sqlite3.connect(catalog)
    pool: dict[str, list[tuple[str, str]]] = {}
    q = ("SELECT c.id, c.set_id FROM cards c WHERE c.lang IN (%s) ORDER BY c.set_id, c.number"
         % ",".join("?" * len(langs)))
    for cid, set_id in con.execute(q, langs):
        p = have.get(cid)
        if p and Path(p).exists():
            pool.setdefault(set_id, []).append((cid, p))
    con.close()
    return {k: v for k, v in pool.items() if len(v) >= 12}


def build(out: Path, catalog: Path, images: Path, n_pages: int, langs: list[str],
          seed: int = 0, empties: float = 0.12) -> list[dict]:
    pool = card_pool(catalog, images, langs)
    if not pool:
        raise SystemExit("no sets with enough downloaded images; run images.fetch first")
    rng = np.random.default_rng(seed)
    sets = sorted(pool)
    layouts = [l for l, _ in LAYOUTS]
    weights = np.array([w for _, w in LAYOUTS], dtype=float)
    weights /= weights.sum()
    (out / "pages").mkdir(parents=True, exist_ok=True)
    pages = []
    for i in range(n_pages):
        rows, cols = layouts[int(rng.choice(len(layouts), p=weights))]
        n = rows * cols
        # A Set binder page is one set in order; a Trade page is mixed. Both exist.
        if rng.random() < 0.5:
            sid = sets[int(rng.integers(len(sets)))]
            cards = pool[sid]
            start = int(rng.integers(0, max(1, len(cards) - n)))
            chosen = cards[start:start + n]
        else:
            chosen = []
            for _ in range(n):
                sid = sets[int(rng.integers(len(sets)))]
                chosen.append(pool[sid][int(rng.integers(len(pool[sid])))])
        while len(chosen) < n:
            chosen.append(chosen[-1])
        slots: list[str | None] = [c for c, _ in chosen]
        imgs: list[np.ndarray | None] = []
        for k, (cid, path) in enumerate(chosen):
            if rng.random() < empties:          # real binders have gaps
                slots[k] = None
                imgs.append(None)
                continue
            im = cv2.imread(path, cv2.IMREAD_COLOR)
            if im is None:
                slots[k] = None
                imgs.append(None)
            else:
                imgs.append(im)
        photo, _ = make_page(PageSpec(rows, cols, imgs), seed=seed * 1000 + i,
                             glare=bool(rng.random() < 0.7))
        name = f"real_{i:03d}.jpg"
        cv2.imwrite(str(out / "pages" / name), photo, [cv2.IMWRITE_JPEG_QUALITY, 88])
        pages.append({"name": f"real_{i:03d}", "photo": name,
                      "layout": [rows, cols], "slots": slots})
    (out / "pages" / "labels.json").write_text(json.dumps(pages, indent=1))
    return pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("build/realpages"))
    ap.add_argument("--catalog", type=Path, default=Path("build/catalog/catalog.sqlite"))
    ap.add_argument("--images", type=Path, default=Path("build/images"))
    ap.add_argument("--pages", type=int, default=40)
    ap.add_argument("--langs", default="en")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    pages = build(args.out, args.catalog, args.images, args.pages, args.langs.split(","), args.seed)
    cards = sum(1 for p in pages for s in p["slots"] if s)
    print(f"{len(pages)} pages, {cards} cards -> {args.out/'pages'/'labels.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
