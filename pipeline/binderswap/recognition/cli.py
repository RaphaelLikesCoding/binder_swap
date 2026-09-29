"""Recognize one binder page photo and write the result + a debug overlay.

    python -m binderswap.recognition.cli photo.jpg --index build/index/en.npz \
        --catalog build/catalog/catalog.sqlite [--layout 3x3] [--set en/sv03 [--page 0]] \
        [--json out.json] [--overlay out.jpg]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

from ..images.index import ReferenceIndex
from .recognizer import CatalogView, Recognizer, SetMode, draw_overlay


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", type=Path)
    ap.add_argument("--index", type=Path, nargs="+", default=[Path("build/index/en.npz")])
    ap.add_argument("--catalog", type=Path, default=Path("build/catalog/catalog.sqlite"))
    ap.add_argument("--layout", help="rows x cols, e.g. 3x3 (default: detect)")
    ap.add_argument("--set", dest="set_id", help="Set binder: catalog set id, e.g. en/sv03")
    ap.add_argument("--page", type=int, help="Set binder: 0-based page index (default: infer)")
    ap.add_argument("--start", type=int, default=1, help="Set binder: first number in the binder")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--overlay", type=Path)
    args = ap.parse_args(argv)

    photo = cv2.imread(str(args.photo))
    if photo is None:
        print(f"cannot read {args.photo}", file=sys.stderr)
        return 2
    layout = tuple(int(x) for x in args.layout.lower().split("x")) if args.layout else None
    mode = SetMode(args.set_id, args.start, args.page) if args.set_id else None
    index = ReferenceIndex.merge([ReferenceIndex.load(p) for p in args.index])
    rec = Recognizer(index, CatalogView(args.catalog))
    result, page, slots = rec.recognize(photo, layout, mode)

    marks = {"confirmed": "✅", "review": "❓", "empty": "⬜"}
    print(f"layout {result.layout[0]}x{result.layout[1]}, page found: {result.page_found}, "
          f"dominant set: {result.dominant_set}")
    for s in result.slots:
        line = f"{marks[s.status]} r{s.row + 1}c{s.col + 1} "
        if s.top:
            line += f"{s.top.card_id} {s.top.name!r} p={s.top.probability:.2f}"
            if s.status == "review":
                line += "  alternatives: " + ", ".join(c.card_id for c in s.candidates[1:4])
        elif s.expected_card_id:
            line += f"missing {s.expected_card_id} -> wish list"
        if s.flags:
            line += f"  [{', '.join(s.flags)}]"
        print(line)
    if args.json:
        args.json.write_text(json.dumps(result.to_dict(), indent=1, ensure_ascii=False))
    if args.overlay:
        cv2.imwrite(str(args.overlay), draw_overlay(page, slots, result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
