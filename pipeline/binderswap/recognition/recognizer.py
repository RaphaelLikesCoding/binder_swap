"""Recognize every pocket on a binder page photo.

Pipeline (spec §5.2–5.4):

1. find + flatten the page, find the pocket grid (``page.py``)
2. per pocket: empty / card / unknown; crop the card
3. per card: visual candidates from the reference index + OCR'd collector number
4. fuse evidence into a probability per candidate (log-linear model + softmax)
5. page priors: the page's dominant set, then set-mode position (sequence) prior
6. decide: ✅ confirmed (p >= threshold) / ❓ review (top-k picker) / ⬜ empty;
   set mode turns empty pockets into specific missing cards for the wish list.

Fusion weights are hand-set starting points. ``eval.py`` measures precision and
coverage on labelled real photos and picks the auto-confirm threshold; weights
should be re-fitted once there are enough labelled pages.
"""

from __future__ import annotations

import collections
import math
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

from ..images.index import ReferenceIndex
from . import ocr
from .features import Embedder, OrbVerifier, default_embedder
from .page import crop_card, guess_layout, locate_page, pocket_is_empty, slots_for


@dataclass
class Weights:
    visual: float = 14.0        # x cosine similarity
    number: float = 3.0         # OCR number == card number
    total: float = 1.5          # OCR total == set printed total
    set_prior: float = 2.0      # card is in the page's dominant set
    sequence: float = 3.5       # set mode: card number == pocket's expected number
    orb: float = 0.08           # x RANSAC inliers (capped)
    orb_cap: int = 50
    temperature: float = 1.0


@dataclass
class Settings:
    top_k: int = 4                   # candidates shown in the picker (§5.5)
    visual_k: int = 30               # candidates pulled from the index
    verify_k: int = 5                # candidates re-ranked with ORB
    confirm_threshold: float = 0.90  # tuned by eval.py (§5.4 target: <1 in 200 wrong)
    min_visual: float = 0.55         # below this the card is probably not in the index
    use_ocr: bool = True
    use_orb: bool = True
    weights: Weights = field(default_factory=Weights)


@dataclass
class SetMode:
    """A Set binder (§4.1): pockets hold one set in collector-number order."""
    set_id: str                       # catalog set id, e.g. en/sv03
    start_number: int = 1             # number in page 1, pocket 1
    page_index: int | None = None     # 0-based page in the binder; None = infer from anchors
    slot_order: str = "row-major"     # or column-major


class CatalogView:
    """The slice of the catalog the recognizer needs, loaded once."""

    def __init__(self, path: Path, langs: list[str] | None = None):
        con = sqlite3.connect(path)
        q = ("SELECT c.id, c.set_id, c.number, c.number_prefix, c.name, c.local_id, s.printed_total, "
             "s.number_prefix, s.name, s.abbreviation FROM cards c JOIN sets s ON s.id = c.set_id")
        if langs:
            q += " WHERE c.lang IN (%s)" % ",".join("?" * len(langs))
        self.cards: dict[str, dict] = {}
        self.by_number: dict[tuple[int, int], list[str]] = collections.defaultdict(list)
        self.by_set_number: dict[tuple[str, int], str] = {}
        for (cid, set_id, number, prefix, name, local_id, total, set_prefix,
             set_name, set_abbr) in con.execute(q, langs or []):
            self.cards[cid] = {"set_id": set_id, "number": number, "prefix": prefix, "name": name,
                               "local_id": local_id, "printed_total": total,
                               "set_name": set_name, "set_abbreviation": set_abbr,
                               "number_label": number_label(local_id, total)}
            if number is not None and total:
                self.by_number[(number, total)].append(cid)
            if number is not None and prefix == set_prefix:
                self.by_set_number.setdefault((set_id, number), cid)
        con.close()


def number_label(local_id: str | None, printed_total: int | None) -> str:
    """What is actually printed on the card: "136/189", or just "136" if the
    set has no printed total (promos, and sets TCGdex has no count for)."""
    if not local_id:
        return ""
    return f"{local_id}/{printed_total}" if printed_total else str(local_id)


@dataclass
class Candidate:
    card_id: str
    name: str
    probability: float
    visual: float
    evidence: dict
    # Shown in the picker next to the image, so a swipe is decided on sight.
    # These are what separate cards the art alone cannot: reprints share an
    # illustration but never a set, and rarely a number.
    set_id: str = ""
    set_name: str = ""
    number_label: str = ""


@dataclass
class SlotResult:
    index: int
    row: int
    col: int
    state: str                         # card | empty | unknown
    status: str                        # confirmed | review | empty
    candidates: list[Candidate] = field(default_factory=list)
    ocr: dict | None = None
    expected_card_id: str | None = None  # set mode
    flags: list[str] = field(default_factory=list)

    @property
    def top(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None


@dataclass
class PageResult:
    layout: tuple[int, int]
    page_found: bool
    dominant_set: str | None
    slots: list[SlotResult]
    set_mode: dict | None = None
    wishlist_additions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class Recognizer:
    def __init__(self, index: ReferenceIndex, catalog: CatalogView, settings: Settings | None = None,
                 embedder: Embedder | None = None):
        self.index, self.catalog = index, catalog
        self.settings = settings or Settings()
        self.embedder = embedder or default_embedder()
        if self.embedder.id != index.embedder_id:
            raise ValueError(f"index built with {index.embedder_id!r}, recognizer uses {self.embedder.id!r}")
        self.orb = OrbVerifier()
        self._ref_desc: dict[str, tuple] = {}
        self._pos = {cid: i for i, cid in enumerate(index.ids)}

    # -- evidence -------------------------------------------------------------

    def _ref_descriptor(self, card_id: str):
        if card_id not in self._ref_desc:
            path = self.index.path_of(card_id)
            img = cv2.imread(path) if path else None
            self._ref_desc[card_id] = self.orb.describe(img) if img is not None else (None, None)
        return self._ref_desc[card_id]

    def _evidence(self, crop: np.ndarray) -> dict:
        vec = self.embedder.embed(crop)
        visual = dict(self.index.search(vec, self.settings.visual_k))
        read = ocr.read_number(crop) if self.settings.use_ocr else ocr.NumberRead("")
        cands = set(visual)
        if read.ok and read.total:
            cands |= set(self.catalog.by_number.get((read.number, read.total), []))
        # Cosine similarity for OCR-only candidates, so every candidate is scored alike.
        for cid in cands - set(visual):
            if cid in self._pos:
                visual[cid] = float(self.index.vectors[self._pos[cid]] @ vec)
        return {"crop": crop, "visual": visual, "ocr": read, "candidates": cands}

    def _score(self, ev: dict, dominant_set: str | None, expected: int | None, set_id: str | None,
               orb_scores: dict[str, int] | None = None) -> list[Candidate]:
        w = self.settings.weights
        read: ocr.NumberRead = ev["ocr"]
        rows = []
        for cid in ev["candidates"]:
            info = self.catalog.cards.get(cid)
            if info is None:
                continue
            vis = ev["visual"].get(cid, 0.0)
            e = {"visual": round(vis, 4)}
            s = w.visual * vis
            if read.ok:
                if info["number"] == read.number:
                    s += w.number
                    e["number"] = True
                if read.total and info["printed_total"] == read.total:
                    s += w.total
                    e["total"] = True
            if dominant_set and info["set_id"] == dominant_set:
                s += w.set_prior
                e["set_prior"] = True
            if expected is not None and info["set_id"] == set_id and info["number"] == expected:
                s += w.sequence
                e["sequence"] = True
            if orb_scores and cid in orb_scores:
                s += w.orb * min(orb_scores[cid], w.orb_cap)
                e["orb_inliers"] = orb_scores[cid]
            rows.append((s, cid, vis, e))
        if not rows:
            return []
        m = max(r[0] for r in rows)
        z = sum(math.exp((r[0] - m) / w.temperature) for r in rows)
        out = []
        for s_, cid, vis, e in rows:
            c = self.catalog.cards[cid]
            out.append(Candidate(cid, c["name"], math.exp((s_ - m) / w.temperature) / z, vis, e,
                                 set_id=c["set_id"], set_name=c.get("set_name") or "",
                                 number_label=c.get("number_label") or ""))
        out.sort(key=lambda c: -c.probability)
        return out

    def _verify(self, ev: dict, ranked: list[Candidate]) -> dict[str, int]:
        if not self.settings.use_orb:
            return {}
        q = self.orb.describe(ev["crop"])
        return {c.card_id: self.orb.inliers(q, self._ref_descriptor(c.card_id))
                for c in ranked[:self.settings.verify_k]}

    # -- page -----------------------------------------------------------------

    def recognize(self, photo: np.ndarray, layout: tuple[int, int] | None = None,
                  set_mode: SetMode | None = None) -> tuple[PageResult, np.ndarray, list]:
        _, page, found = locate_page(photo, layout)
        layout = layout or guess_layout(page)
        slots = slots_for(page, layout)
        n = len(slots)

        evidence: dict[int, dict] = {}
        states: dict[int, str] = {}
        for s in slots:
            if s.card_box is None:
                states[s.index] = "empty" if pocket_is_empty(page, s) else "unknown"
                if states[s.index] == "empty":
                    continue
            else:
                states[s.index] = "card"
            evidence[s.index] = self._evidence(crop_card(page, s))

        # Pass 1: no page priors. Verify top candidates geometrically.
        ranked = {i: self._score(ev, None, None, None) for i, ev in evidence.items()}
        orb_scores = {i: self._verify(evidence[i], r) for i, r in ranked.items()}
        ranked = {i: self._score(evidence[i], None, None, None, orb_scores[i]) for i in evidence}

        # Pass 2: dominant set among confident cards.
        confident = [r[0].card_id for r in ranked.values()
                     if r and r[0].probability >= self.settings.confirm_threshold]
        sets = collections.Counter(self.catalog.cards[c]["set_id"] for c in confident)
        dominant = None
        if sets:
            top_set, count = sets.most_common(1)[0]
            if count >= 2 and count >= 0.5 * len(confident):
                dominant = top_set
        if set_mode:
            dominant = set_mode.set_id

        expected = self._expected_numbers(n, layout, set_mode, ranked) if set_mode else {}
        ranked = {i: self._score(evidence[i], dominant, expected.get(i), set_mode.set_id if set_mode else None,
                                 orb_scores[i]) for i in evidence}

        results, wishlist = [], []
        for s in slots:
            state = states[s.index]
            r = SlotResult(s.index, s.row, s.col, state, "empty" if state == "empty" else "review")
            if s.index in evidence:
                r.candidates = ranked[s.index][:self.settings.top_k]
                read = evidence[s.index]["ocr"]
                r.ocr = {"text": read.text, "number": read.number, "total": read.total, "votes": read.votes}
                top = r.top
                if top and top.probability >= self.settings.confirm_threshold and top.visual >= self.settings.min_visual:
                    r.status = "confirmed"
                if top and top.visual < self.settings.min_visual:
                    r.flags.append("low_visual_match")
                if state == "unknown":
                    r.flags.append("card_edges_not_found")
            if set_mode and s.index in expected:
                r.expected_card_id = self.catalog.by_set_number.get((set_mode.set_id, expected[s.index]))
                if state == "empty" and r.expected_card_id:
                    wishlist.append(r.expected_card_id)
                elif r.status == "confirmed" and r.top and r.expected_card_id and r.top.card_id != r.expected_card_id:
                    r.flags.append("out_of_order")
            results.append(r)

        result = PageResult(layout, found, dominant, results,
                            asdict(set_mode) if set_mode else None, wishlist)
        return result, page, slots

    def _expected_numbers(self, n: int, layout: tuple[int, int], mode: SetMode,
                          ranked: dict[int, list[Candidate]]) -> dict[int, int]:
        """Pocket -> expected collector number for a Set binder page.

        With an explicit page index the template is fixed. Otherwise confident
        cards from the set vote for the page's first number (one anchor is
        enough; disagreements lose the vote and get flagged out_of_order).
        """
        rows, cols = layout

        def order(i: int) -> int:
            if mode.slot_order == "column-major":
                r, c = divmod(i, cols)
                return c * rows + r
            return i

        if mode.page_index is not None:
            base = mode.start_number + mode.page_index * n
        else:
            votes = collections.Counter()
            for i, cands in ranked.items():
                if cands and cands[0].probability >= self.settings.confirm_threshold:
                    info = self.catalog.cards[cands[0].card_id]
                    if info["set_id"] == mode.set_id and info["number"] is not None:
                        votes[info["number"] - order(i)] += 1
            if not votes:
                return {}
            base = votes.most_common(1)[0][0]
        return {i: base + order(i) for i in range(n)}


def draw_overlay(page: np.ndarray, slots: list, result: PageResult) -> np.ndarray:
    """Debug view: ✅ green, ❓ orange, empty grey, with the top guess."""
    out = page.copy()
    colours = {"confirmed": (60, 180, 60), "review": (0, 140, 255), "empty": (150, 150, 150)}
    for s, r in zip(slots, result.slots):
        x, y, w, h = s.card_box or s.box
        cv2.rectangle(out, (x, y), (x + w, y + h), colours[r.status], 6)
        mark = {"confirmed": "OK", "review": "?", "empty": "EMPTY"}[r.status]
        label = mark
        if r.top:
            label += f" {r.top.card_id} {r.top.probability:.2f}"
        elif r.expected_card_id:
            label += f" need {r.expected_card_id}"
        cv2.rectangle(out, (x, y), (x + w, y + 44), colours[r.status], -1)
        cv2.putText(out, label[:32], (x + 8, y + 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return out
