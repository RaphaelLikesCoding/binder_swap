"""Build the visual reference index from downloaded card images.

    python -m binderswap.images.index --images build/images --out build/index

Output per language: ``<out>/<lang>.npz`` (card ids + float16 vectors) and
``<out>/<lang>.json`` (embedder id, count, source manifest hash). The
recognizer refuses an index built by a different embedder than its own.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..recognition.features import Embedder, default_embedder


@dataclass
class ReferenceIndex:
    embedder_id: str
    ids: np.ndarray        # (N,) str
    vectors: np.ndarray    # (N, D) float32, L2-normalized
    paths: np.ndarray      # (N,) str, reference image paths (for verification)

    def search(self, query: np.ndarray, k: int = 20, mask: np.ndarray | None = None) -> list[tuple[str, float]]:
        sims = self.vectors @ query
        if mask is not None:
            sims = np.where(mask, sims, -np.inf)
        k = min(k, len(sims))
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        return [(str(self.ids[i]), float(sims[i])) for i in top if np.isfinite(sims[i])]

    def path_of(self, card_id: str) -> str | None:
        hit = np.nonzero(self.ids == card_id)[0]
        return str(self.paths[hit[0]]) if len(hit) else None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, ids=self.ids, vectors=self.vectors.astype(np.float16), paths=self.paths)
        path.with_suffix(".json").write_text(json.dumps(
            {"embedder": self.embedder_id, "count": int(len(self.ids)), "dim": int(self.vectors.shape[1])}))

    @classmethod
    def load(cls, path: Path) -> "ReferenceIndex":
        meta = json.loads(path.with_suffix(".json").read_text())
        z = np.load(path, allow_pickle=False)
        return cls(meta["embedder"], z["ids"], z["vectors"].astype(np.float32), z["paths"])

    @classmethod
    def merge(cls, parts: list["ReferenceIndex"]) -> "ReferenceIndex":
        ids = {p.embedder_id for p in parts}
        if len(ids) != 1:
            raise ValueError(f"cannot merge indexes from different embedders: {ids}")
        return cls(parts[0].embedder_id, np.concatenate([p.ids for p in parts]),
                   np.concatenate([p.vectors for p in parts]), np.concatenate([p.paths for p in parts]))


def build(images_dir: Path, embedder: Embedder | None = None, langs: list[str] | None = None,
          quality: str = "high") -> dict[str, ReferenceIndex]:
    embedder = embedder or default_embedder()
    manifest = sqlite3.connect(images_dir / "manifest.sqlite")
    rows = manifest.execute(
        "SELECT card_id, path FROM images WHERE status='ok' AND quality=? ORDER BY card_id", (quality,)).fetchall()
    by_lang: dict[str, tuple[list, list, list]] = {}
    for card_id, path in rows:
        lang = card_id.split("/", 1)[0]
        if langs and lang not in langs:
            continue
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            print(f"unreadable image, skipped: {path}", file=sys.stderr)
            continue
        ids, vecs, paths = by_lang.setdefault(lang, ([], [], []))
        ids.append(card_id)
        vecs.append(embedder.embed(img))
        paths.append(path)
    return {lang: ReferenceIndex(embedder.id, np.array(ids), np.stack(vecs), np.array(paths))
            for lang, (ids, vecs, paths) in by_lang.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", type=Path, default=Path("build/images"))
    ap.add_argument("--out", type=Path, default=Path("build/index"))
    ap.add_argument("--langs", default="en,ja")
    args = ap.parse_args(argv)
    for lang, index in build(args.images, langs=args.langs.split(",")).items():
        index.save(args.out / f"{lang}.npz")
        print(f"{lang}: {len(index.ids)} cards indexed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
