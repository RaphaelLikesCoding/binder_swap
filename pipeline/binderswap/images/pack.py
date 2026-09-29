"""A portable index pack the app can read (SPEC 9: "index packs per set").

    python -m binderswap.images.pack --index build/index/en.npz --out build/packs/en.bspk

The reference index is a numpy ``.npz``. Swift has no numpy, so the app cannot
read it, and a format that only one side can parse is a contract waiting to
break. This writes a flat little-endian file designed to be memory-mapped and
used without a parse step:

    magic     8 bytes   "BSPK\\0\\0\\0\\1"
    header    JSON, u32 length-prefixed: embedder, count, dim, dtype, id_bytes
    ids       count * id_bytes, UTF-8, NUL-padded, fixed width so row i is at
                                a known offset
    vectors   count * dim float16, L2-normalised, row-major

Vectors stay float16 because that is what the index already stores and what a
phone wants to hold: 19,724 x 1024 is 40 MB, versus 80 at float32.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

MAGIC = b"BSPK\0\0\0\1"


def write_pack(ids: np.ndarray, vectors: np.ndarray, embedder: str, out: Path) -> dict:
    ids = np.asarray(ids).astype(str)
    if len(ids) != len(vectors):
        raise ValueError(f"{len(ids)} ids but {len(vectors)} vectors")
    encoded = [str(i).encode("utf-8") for i in ids]
    id_bytes = max((len(e) for e in encoded), default=1)
    vecs = np.asarray(vectors, dtype=np.float16)
    header = {"embedder": embedder, "count": int(len(ids)), "dim": int(vecs.shape[1]),
              "dtype": "float16", "id_bytes": int(id_bytes)}
    blob = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<I", len(blob)))
        f.write(blob)
        for e in encoded:
            f.write(e.ljust(id_bytes, b"\0"))
        f.write(vecs.tobytes(order="C"))
    return header


def read_pack(path: Path) -> tuple[list[str], np.ndarray, dict]:
    """Reference reader, so the Swift one has something to be wrong against."""
    data = path.read_bytes()
    if data[:8] != MAGIC:
        raise ValueError("not a BSPK pack")
    (n,) = struct.unpack_from("<I", data, 8)
    header = json.loads(data[12:12 + n])
    off = 12 + n
    w, count, dim = header["id_bytes"], header["count"], header["dim"]
    ids = [data[off + i * w: off + (i + 1) * w].rstrip(b"\0").decode("utf-8") for i in range(count)]
    off += count * w
    vecs = np.frombuffer(data, dtype=np.float16, count=count * dim, offset=off).reshape(count, dim)
    return ids, vecs, header


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", type=Path, default=Path("build/index/en.npz"))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    from .index import ReferenceIndex
    idx = ReferenceIndex.load(args.index)
    out = args.out or args.index.with_suffix(".bspk")
    h = write_pack(idx.ids, idx.vectors, idx.embedder_id, out)
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB): {h}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
