"""End-to-end tests on a synthetic world: catalog -> image server -> fetch -> index -> recognize."""

import json
import shutil
import sqlite3

import cv2
import numpy as np
import pytest

from binderswap import demo
from binderswap.images import fetch
from binderswap.images.index import ReferenceIndex
from binderswap.recognition import ocr
from binderswap.recognition.eval import evaluate, summarize
from binderswap.recognition.page import guess_layout, locate_page
from binderswap.recognition.recognizer import CatalogView, Recognizer, SetMode, Settings
from binderswap.synthetic import PageSpec, make_card, make_page


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    out = tmp_path_factory.mktemp("world")
    info = demo.build_world(out, missing={"en/swsh9/020"})
    demo.make_labelled_pages(out)
    return out, info


def test_fetch_records_ok_and_missing_and_is_resumable(world):
    out, info = world
    assert info["fetch"] == {"ok": 79, "missing": 1, "error": 0}
    m = sqlite3.connect(out / "images" / "manifest.sqlite")
    assert m.execute("SELECT status FROM images WHERE card_id='en/swsh9/020'").fetchone() == ("missing",)
    (sha,) = m.execute("SELECT sha256 FROM images WHERE card_id='en/sv03/001'").fetchone()
    assert len(sha) == 64
    # Rerun: nothing left to do (the catalog still points at the dead test server).
    assert fetch.run(out / "catalog.sqlite", out / "images", langs=["en"], rate=0, progress=False) == \
        {"ok": 0, "missing": 0, "error": 0}


def test_candidates_carry_the_set_and_number_the_picker_prints(world):
    """The picker has to be decidable on sight.

    Reprints share an illustration, so the visual score cannot separate them --
    in the real EN index ~4% of cards have a near-identical twin. What tells
    them apart is the set name and the printed number, so every candidate must
    carry both without the caller going back to the catalog.
    """
    out, _ = world
    cat = CatalogView(out / "catalog.sqlite", langs=["en"])
    rec = Recognizer(ReferenceIndex.load(out / "index" / "en.npz"), cat)
    photo = cv2.imread(str(out / "pages" / "trade_mixed.jpg"), cv2.IMREAD_COLOR)
    result, _, _ = rec.recognize(photo, (3, 3))

    slots = [s for s in result.slots if s.candidates]
    assert slots, "no candidates produced"
    for slot in slots:
        assert len(slot.candidates) <= 4          # four options, per the picker
        for c in slot.candidates:
            assert c.set_name, f"{c.card_id} has no set name"
            assert c.number_label, f"{c.card_id} has no printed number"
            assert c.set_id


def test_common_layouts_cover_both_orientations_and_exclude_the_degenerate_one():
    """Binders come in several pocket layouts, and pages get photographed both ways up.

    A layout present in one orientation but not the other silently cannot be
    detected on half the photos. (1, 1) is excluded on purpose: a single cell has
    no interior gutter, so it is scored on brightness alone and beats every real
    grid.
    """
    from binderswap.recognition.page import COMMON_LAYOUTS
    layouts = set(COMMON_LAYOUTS)
    assert (1, 1) not in layouts
    for rows, cols in layouts:
        assert (cols, rows) in layouts, f"{(rows, cols)} has no {(cols, rows)} counterpart"
    for expected in [(3, 3), (2, 2), (3, 4), (4, 3), (2, 3), (3, 2), (2, 4), (4, 2)]:
        assert expected in layouts, f"{expected} is a real binder and is missing"


def test_number_label_matches_what_is_printed_on_the_card():
    from binderswap.recognition.recognizer import number_label
    assert number_label("136", 189) == "136/189"
    assert number_label("SV001", 198) == "SV001/198"
    assert number_label("12", None) == "12"       # promos have no printed total
    assert number_label(None, 189) == ""


def test_plan_refetches_when_the_manifest_says_ok_but_the_files_are_not_there(world, tmp_path):
    """A manifest is not evidence that the images exist.

    Restoring a manifest from a CI artifact, clearing build/, or rerunning with
    a different --ext all leave rows saying "ok" with no file behind them. If
    plan() trusts the row, the fetcher skips every card and reports success
    having downloaded nothing.
    """
    out, _ = world
    images = tmp_path / "images"
    shutil.copytree(out / "images", images)
    m = sqlite3.connect(images / "manifest.sqlite")

    def planned(ext=None):
        return fetch.plan(out / "catalog.sqlite", images, "high", ["en"], None, m, False, ext)

    assert planned() == []                                  # files present: nothing to do

    # Same extension, files gone. The one "missing" card stays skipped: the
    # server has no image for it, so there is nothing on disk to look for.
    pngs = sorted(images.rglob("*.png"))
    assert len(pngs) == 79
    for f in pngs:
        f.unlink()
    assert len(planned()) == 79

    # A truncated file is not a usable one either.
    shutil.rmtree(images)
    shutil.copytree(out / "images", images)
    victim = sorted(images.rglob("*.png"))[0]
    victim.write_bytes(victim.read_bytes()[:10])
    assert len(planned()) == 1

    # Files present, but under a different extension than the one asked for.
    assert len(planned(ext="webp")) == 79


def test_index_roundtrip_and_self_match(world):
    out, _ = world
    index = ReferenceIndex.load(out / "index" / "en.npz")
    assert len(index.ids) == 79 and index.embedder_id == "classic-v1"
    from binderswap.recognition.features import default_embedder
    img = demo.card_image("en/sv04/012")
    # Simulate a phone photo of the card: blur, colour cast, noise.
    photo = cv2.GaussianBlur(img, (5, 5), 0).astype(np.int16) + np.int16([10, -5, 15])
    photo = np.clip(photo + np.random.default_rng(0).normal(0, 6, photo.shape), 0, 255).astype(np.uint8)
    top = index.search(default_embedder().embed(photo), k=3)
    assert top[0][0] == "en/sv04/012"


@pytest.mark.skipif(not ocr.available(), reason="tesseract not installed")
def test_ocr_reads_collector_number():
    card = make_card("x", "Test", "045", 198)
    read = ocr.read_number(card)
    assert (read.number, read.total) == (45, 198)
    assert ocr.parse("TG05/TG30").prefix == "TG"


@pytest.mark.parametrize("layout", [(3, 3), (2, 2), (3, 4)])
def test_layout_detection_with_empty_pockets(layout):
    rows, cols = layout
    cards = [make_card(f"c{i}", f"C{i}", f"{i:03d}", 99) if i % 4 != 1 else None for i in range(rows * cols)]
    photo, _ = make_page(PageSpec(rows, cols, cards), seed=rows * 10 + cols)
    _, page, found = locate_page(photo)
    assert found
    assert guess_layout(page) == layout


def test_recognize_labelled_pages(world):
    out, _ = world
    index = ReferenceIndex.load(out / "index" / "en.npz")
    rec = Recognizer(index, CatalogView(out / "catalog.sqlite"))
    res = evaluate(rec, out / "pages" / "labels.json", use_layout=False)
    s = summarize(res)
    # en/swsh9/020 has no reference image (missing upstream): it must not be
    # auto-confirmed as something else.
    wrong_confirmed = [o for o in res.outcomes if o.status == "confirmed" and o.top != o.truth]
    assert wrong_confirmed == []
    assert s["layout_accuracy"] == 1.0
    assert s["empty_accuracy"] == 1.0 and s["false_empty"] == 0
    assert s["wishlist_recall"] == 1.0 and s["wishlist_spurious"] == 0
    in_index = [o for o in res.outcomes if o.truth not in (None, "en/swsh9/020")]
    assert sum(o.top == o.truth for o in in_index) == len(in_index)


def test_set_mode_flags_out_of_order_card(world):
    out, _ = world
    rec = Recognizer(ReferenceIndex.load(out / "index" / "en.npz"), CatalogView(out / "catalog.sqlite"))
    # Page 1 of a set binder, but pocket 3 holds #25 instead of #3.
    ids = [f"en/sv03/{n:03d}" for n in (1, 2, 25, 4, 5, 6, 7, 8, 9)]
    photo, _ = make_page(PageSpec(3, 3, [demo.card_image(c) for c in ids]), seed=3, glare=False)
    result, _, _ = rec.recognize(photo, (3, 3), SetMode("en/sv03", page_index=0))
    slot = result.slots[2]
    assert slot.top.card_id == "en/sv03/025"
    assert "out_of_order" in slot.flags and slot.expected_card_id == "en/sv03/003"
    assert result.wishlist_additions == []


def test_embedder_mismatch_is_rejected(world):
    out, _ = world
    index = ReferenceIndex.load(out / "index" / "en.npz")
    index.embedder_id = "some-other-model"
    with pytest.raises(ValueError):
        Recognizer(index, CatalogView(out / "catalog.sqlite"))


def test_result_is_json_serializable(world):
    out, _ = world
    rec = Recognizer(ReferenceIndex.load(out / "index" / "en.npz"), CatalogView(out / "catalog.sqlite"),
                     Settings(use_orb=False))
    photo = cv2.imread(str(out / "pages" / "four_pocket.jpg"))
    result, _, _ = rec.recognize(photo, (2, 2))
    assert json.loads(json.dumps(result.to_dict()))["layout"] == [2, 2]


def test_image_summary_reports_missing_by_set(world):
    from binderswap.images.summary import render
    out, _ = world
    md = render(out / "images", out / "catalog.sqlite")
    assert "| en | 79 | 1 | 0 |" in md
    assert "| `en/swsh9` | Brilliant Stars | 1 | 20 |" in md


def test_fetch_exit_code_tolerates_small_error_rate(world, tmp_path, monkeypatch):
    out, _ = world
    calls = {}

    def fake_run(*a, **k):
        return calls["counts"]
    monkeypatch.setattr(fetch, "run", fake_run)
    calls["counts"] = {"ok": 995, "missing": 100, "error": 5}
    assert fetch.main(["--catalog", str(out / "catalog.sqlite"), "--out", str(tmp_path)]) == 0
    calls["counts"] = {"ok": 900, "missing": 0, "error": 100}
    assert fetch.main(["--catalog", str(out / "catalog.sqlite"), "--out", str(tmp_path)]) == 1
