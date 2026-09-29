"""Build a complete synthetic world: catalog, image server, images, index, labelled pages.

    python -m binderswap.demo --out build/demo

Used by the tests and as a smoke test of the whole pipeline without network
access or real card images. Pages are labelled in the same format ``eval.py``
uses for real photos.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import json
import threading
from pathlib import Path

import cv2

from .catalog.db import write_db
from .catalog.normalize import build_catalog
from .images import fetch
from .images.index import build as build_index
from .synthetic import PageSpec, make_card, make_page

SETS = {"sv03": ("Obsidian Flames", 30), "sv04": ("Paradox Rift", 30), "swsh9": ("Brilliant Stars", 20)}


def records():
    for set_id, (set_name, total) in SETS.items():
        for n in range(1, total + 1):
            yield {
                "source": {"repo": "synthetic", "path": f"{set_id}/{n}.ts"},
                "lang": "en", "localId": f"{n:03d}",
                "serie": {"id": "demo", "name": {"en": "Demo"}},
                "set": {"id": set_id, "name": {"en": set_name}, "cardCount": {"official": total},
                        "releaseDate": "2024-01-01"},
                "card": {"name": {"en": f"{set_name[:6]} #{n}"}, "rarity": "Common", "category": "Pokemon"},
            }


def card_image(card_id: str) -> "cv2.Mat":
    _, set_id, local = card_id.split("/")
    return make_card(card_id, f"{SETS[set_id][0][:6]} #{int(local)}", local, SETS[set_id][1])


@contextlib.contextmanager
def image_server(root: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def build_world(out: Path, missing: set[str] = frozenset()) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    cat = build_catalog(records())
    served = out / "served"
    for cid in cat.cards:
        if cid in missing:
            continue
        _, set_id, local = cid.split("/")
        dest = served / "en" / "demo" / set_id / local / "high.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(dest), card_image(cid))
    with image_server(served) as base:
        for c in cat.cards.values():
            c["image_base"] = c["image_base"].replace("https://assets.tcgdex.net", base)
        write_db(cat, out / "catalog.sqlite", {"source": "synthetic"})
        counts = fetch.run(out / "catalog.sqlite", out / "images", langs=["en"], rate=0, progress=False)
    index = build_index(out / "images", langs=["en"])["en"]
    index.save(out / "index" / "en.npz")
    return {"catalog": cat, "fetch": counts, "index": index}


def make_labelled_pages(out: Path) -> list[dict]:
    """A few pages that exercise the interesting cases."""
    pages = [
        # Set binder page 1 of sv03, with gaps at #5 and #9.
        {"name": "set_sv03_p1", "layout": [3, 3], "set_mode": {"set_id": "en/sv03", "page_index": 0},
         "slots": [f"en/sv03/{n:03d}" if n not in (5, 9) else None for n in range(1, 10)],
         "expected_wishes": ["en/sv03/005", "en/sv03/009"]},
        # Set binder page 2 of sv03, page index unknown (anchors must infer it).
        {"name": "set_sv03_p2", "layout": [3, 3], "set_mode": {"set_id": "en/sv03"},
         "slots": [f"en/sv03/{n:03d}" if n not in (12, 13) else None for n in range(10, 19)],
         "expected_wishes": ["en/sv03/012", "en/sv03/013"]},
        # Trade binder: mixed sets, one empty pocket.
        {"name": "trade_mixed", "layout": [3, 3],
         "slots": ["en/sv04/007", "en/swsh9/003", "en/sv03/021", None, "en/sv04/019",
                   "en/swsh9/015", "en/sv03/002", "en/sv04/001", "en/swsh9/020"]},
        # 4-pocket page.
        {"name": "four_pocket", "layout": [2, 2], "slots": ["en/sv04/010", "en/sv04/011", None, "en/sv04/013"]},
    ]
    (out / "pages").mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(pages):
        imgs = [card_image(c) if c else None for c in p["slots"]]
        photo, _ = make_page(PageSpec(p["layout"][0], p["layout"][1], imgs), seed=i + 10)
        p["photo"] = f"{p['name']}.jpg"
        cv2.imwrite(str(out / "pages" / p["photo"]), photo, [cv2.IMWRITE_JPEG_QUALITY, 88])
    (out / "pages" / "labels.json").write_text(json.dumps(pages, indent=1))
    return pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("build/demo"))
    args = ap.parse_args(argv)
    world = build_world(args.out)
    make_labelled_pages(args.out)
    print(f"catalog {len(world['catalog'].cards)} cards, fetch {world['fetch']}, "
          f"index {len(world['index'].ids)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
