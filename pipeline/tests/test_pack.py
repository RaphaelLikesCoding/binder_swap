"""The .bspk index pack: a format Python writes and Swift reads.

app/BinderSwapCore/Tests reads the same fixture and checks it against values
this side produced, so a divergence fails rather than ships.
"""

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from binderswap.images.pack import MAGIC, read_pack, write_pack

VECTORS = Path(__file__).resolve().parents[2] / "spec" / "vectors" / "packs"


def _unit(rng, n, d):
    v = rng.normal(size=(n, d)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_round_trip_preserves_ids_and_vectors(tmp_path):
    rng = np.random.default_rng(0)
    ids = np.array([f"en/set{i}/{i:03d}" for i in range(20)])
    vecs = _unit(rng, 20, 16)
    out = tmp_path / "x.bspk"
    header = write_pack(ids, vecs, "classic-v1", out)
    got_ids, got_vecs, got_header = read_pack(out)
    assert got_ids == list(ids)
    assert got_header == header
    # float16 on disk, so compare at that precision rather than exactly.
    assert np.allclose(got_vecs.astype(np.float32), vecs, atol=1e-3)


def test_ids_of_different_lengths_are_padded_not_truncated(tmp_path):
    ids = np.array(["a", "en/sv10.5w/144", "ja/SVLN/011"])
    out = tmp_path / "x.bspk"
    h = write_pack(ids, _unit(np.random.default_rng(1), 3, 4), "classic-v1", out)
    assert h["id_bytes"] == len("en/sv10.5w/144")
    assert read_pack(out)[0] == list(ids)


def test_a_mismatched_id_and_vector_count_is_refused(tmp_path):
    with pytest.raises(ValueError):
        write_pack(np.array(["a", "b"]), _unit(np.random.default_rng(2), 3, 4),
                   "classic-v1", tmp_path / "x.bspk")


def test_a_foreign_file_is_not_mistaken_for_a_pack(tmp_path):
    p = tmp_path / "x.bspk"
    p.write_bytes(b"hello there, not a pack")
    with pytest.raises(ValueError):
        read_pack(p)


def test_the_committed_fixture_still_matches_its_expected_values():
    """Swift is checked against this JSON; if the fixture drifts, Swift breaks
    and the failure would otherwise point at the wrong language."""
    pack, meta = VECTORS / "fixture.bspk", VECTORS / "fixture.json"
    want = json.loads(meta.read_text())
    ids, vecs, header = read_pack(pack)
    assert header == want["header"]
    assert ids == want["ids"]
    assert np.allclose(vecs[want["query_is_row"]].astype(np.float32),
                       np.array(want["row2"], dtype=np.float32), atol=1e-5)
    q = vecs[want["query_is_row"]].astype(np.float32)
    scores = vecs.astype(np.float32) @ q
    order = sorted(range(len(ids)), key=lambda i: (-scores[i], ids[i]))
    assert [ids[i] for i in order] == [r[0] for r in want["search"]]


def test_header_is_little_endian_length_prefixed():
    data = (VECTORS / "fixture.bspk").read_bytes()
    assert data[:8] == MAGIC
    (n,) = struct.unpack_from("<I", data, 8)
    assert json.loads(data[12:12 + n])["dtype"] == "float16"
