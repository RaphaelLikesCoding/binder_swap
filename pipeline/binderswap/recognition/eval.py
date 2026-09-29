"""Measure recognition accuracy on labelled binder pages and pick the confirm threshold.

    python -m binderswap.recognition.eval --pages path/to/labels.json \
        --index build/index/en.npz --catalog build/catalog/catalog.sqlite [--out report.md]

``labels.json`` is a list of pages::

    {"photo": "IMG_0412.jpg",            # relative to labels.json
     "layout": [3, 3],                    # optional; omit to test layout detection too
     "set_mode": {"set_id": "en/sv03"},   # optional
     "slots": ["en/sv03/001", null, ...], # row-major; null = empty pocket;
                                          # "?" = card present but not in catalog
     "expected_wishes": ["en/sv03/002"]}  # set mode only: cards missing from this page

The metrics are the ones in spec §10: auto-confirm **precision** (how often a
✅ is right; target ≥ 99.5%) and **coverage** (share of cards auto-confirmed;
target ≥ 70%), plus top-1 / top-k accuracy of the picker, empty-pocket
accuracy and set-mode wish-list accuracy.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from ..images.index import ReferenceIndex
from .recognizer import CatalogView, Recognizer, SetMode, Settings


@dataclass
class SlotOutcome:
    page: str
    index: int
    truth: str | None
    top: str | None
    probability: float
    in_top_k: bool
    status: str
    state: str


@dataclass
class EvalResult:
    outcomes: list[SlotOutcome] = field(default_factory=list)
    layout_correct: int = 0
    pages: int = 0
    wish_expected: int = 0
    wish_correct: int = 0
    wish_spurious: int = 0
    seconds: float = 0.0


def evaluate(recognizer: Recognizer, labels_path: Path, use_layout: bool = True) -> EvalResult:
    pages = json.loads(labels_path.read_text())
    res = EvalResult()
    t0 = time.time()
    for p in pages:
        photo = cv2.imread(str(labels_path.parent / p["photo"]))
        if photo is None:
            print(f"cannot read {p['photo']}", file=sys.stderr)
            continue
        layout = tuple(p["layout"]) if use_layout and p.get("layout") else None
        mode = SetMode(**p["set_mode"]) if p.get("set_mode") else None
        result, _, _ = recognizer.recognize(photo, layout, mode)
        res.pages += 1
        if p.get("layout") and list(result.layout) == list(p["layout"]):
            res.layout_correct += 1
        for slot, truth in zip(result.slots, p["slots"]):
            top = slot.top
            res.outcomes.append(SlotOutcome(
                p["photo"], slot.index, truth, top.card_id if top else None,
                top.probability if top else 0.0,
                any(c.card_id == truth for c in slot.candidates), slot.status, slot.state))
        # Set-mode truth: the cards that belong in the page's empty pockets.
        if mode and "expected_wishes" in p:
            truth_wishes, got = set(p["expected_wishes"]), set(result.wishlist_additions)
            res.wish_expected += len(truth_wishes)
            res.wish_correct += len(got & truth_wishes)
            res.wish_spurious += len(got - truth_wishes)
    res.seconds = time.time() - t0
    return res


def summarize(res: EvalResult, thresholds=(0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99)) -> dict:
    cards = [o for o in res.outcomes if o.truth not in (None, "?")]
    empties = [o for o in res.outcomes if o.truth is None]
    out = {
        "pages": res.pages,
        "pockets": len(res.outcomes),
        "cards": len(cards),
        "layout_accuracy": res.layout_correct / res.pages if res.pages else None,
        "top1_accuracy": sum(o.top == o.truth for o in cards) / len(cards) if cards else None,
        "topk_accuracy": sum(o.in_top_k for o in cards) / len(cards) if cards else None,
        "empty_accuracy": sum(o.state == "empty" for o in empties) / len(empties) if empties else None,
        "false_empty": sum(o.state == "empty" for o in cards),
        "seconds_per_page": res.seconds / res.pages if res.pages else None,
        "thresholds": [],
    }
    confirmable = [o for o in res.outcomes if o.truth is not None]  # cards incl. out-of-catalog
    for t in thresholds:
        auto = [o for o in confirmable if o.probability >= t]
        right = sum(o.top == o.truth for o in auto)
        out["thresholds"].append({
            "threshold": t,
            "auto_confirmed": len(auto),
            "precision": right / len(auto) if auto else None,
            "coverage": len(auto) / len(confirmable) if confirmable else None,
        })
    ok = [r for r in out["thresholds"] if r["precision"] is not None and r["precision"] >= 0.995]
    out["recommended_threshold"] = min((r["threshold"] for r in ok), default=None)
    if res.wish_expected:
        out["wishlist_recall"] = res.wish_correct / res.wish_expected
        out["wishlist_spurious"] = res.wish_spurious
    return out


def render(summary: dict, res: EvalResult) -> str:
    pct = lambda v: "n/a" if v is None else f"{100 * v:.1f}%"  # noqa: E731
    lines = [
        "# Recognition evaluation", "",
        f"- Pages: {summary['pages']}, pockets: {summary['pockets']}, cards: {summary['cards']}",
        f"- Layout detection: {pct(summary['layout_accuracy'])}",
        f"- Top-1 accuracy: **{pct(summary['top1_accuracy'])}**, correct card in picker (top-k): "
        f"{pct(summary['topk_accuracy'])}",
        f"- Empty pockets detected: {pct(summary['empty_accuracy'])}; cards wrongly called empty: "
        f"{summary['false_empty']}",
        f"- Time per page: {summary['seconds_per_page']:.2f}s" if summary["seconds_per_page"] else "",
    ]
    if "wishlist_recall" in summary:
        lines.append(f"- Set-mode wish list: {pct(summary['wishlist_recall'])} of missing cards found, "
                     f"{summary['wishlist_spurious']} spurious")
    lines += ["", "## Auto-confirm threshold sweep (target: precision ≥ 99.5%, coverage ≥ 70%)", "",
              "| Threshold | Auto-confirmed | Precision | Coverage |", "|---|---|---|---|"]
    for r in summary["thresholds"]:
        lines.append(f"| {r['threshold']} | {r['auto_confirmed']} | {pct(r['precision'])} | {pct(r['coverage'])} |")
    lines += ["", f"Recommended threshold: **{summary['recommended_threshold']}**", "",
              "## Misses", "", "| Photo | Pocket | Truth | Top guess | p | Status |", "|---|---|---|---|---|---|"]
    for o in res.outcomes:
        if o.truth != o.top and not (o.truth is None and o.state == "empty"):
            lines.append(f"| {o.page} | {o.index} | {o.truth} | {o.top} | {o.probability:.2f} | {o.status} |")
    return "\n".join(line for line in lines if line is not None) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", type=Path, required=True, help="labels.json")
    ap.add_argument("--index", type=Path, nargs="+", default=[Path("build/index/en.npz")])
    ap.add_argument("--catalog", type=Path, default=Path("build/catalog/catalog.sqlite"))
    ap.add_argument("--detect-layout", action="store_true", help="ignore labelled layouts")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    index = ReferenceIndex.merge([ReferenceIndex.load(p) for p in args.index])
    rec = Recognizer(index, CatalogView(args.catalog), Settings(use_ocr=not args.no_ocr))
    res = evaluate(rec, args.pages, use_layout=not args.detect_layout)
    summary = summarize(res)
    report = render(summary, res)
    if args.out:
        args.out.write_text(report)
        args.out.with_suffix(".json").write_text(json.dumps(summary, indent=1))
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
