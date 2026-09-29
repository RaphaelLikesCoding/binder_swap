"""Read the collector number (e.g. ``045/198``, ``TG05/TG30``, ``SV-P 123``) from a card.

Uses the Tesseract CLI on the server/prototype; the iOS app uses Vision's
``VNRecognizeTextRequest`` on the same crop. Returns ``None`` fields when
nothing trustworthy was read: OCR is one signal among several, never required.
"""

from __future__ import annotations

import collections
import re
import shutil
import os
import subprocess
from dataclasses import dataclass

import cv2
import numpy as np

from .features import NUMBER_BAND, canonical, crop_frac

_NUM_RE = re.compile(r"(?P<prefix>[A-Z]{0,4})\s*(?P<num>\d{1,3})\s*/\s*(?P<tprefix>[A-Z]{0,4})\s*(?P<total>\d{2,3})")
_WHITELIST = "0123456789/ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass
class NumberRead:
    text: str
    prefix: str | None = None
    number: int | None = None
    total: int | None = None
    votes: int = 0
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return self.number is not None


def available() -> bool:
    return shutil.which("tesseract") is not None


# Tesseract on Linux is built with OpenMP and sizes a thread team per call from
# the core count. We already read the pockets concurrently, so each of those
# calls would spawn its own team: on a 2-vCPU runner that is four-plus threads
# fighting over two cores, and every call overran its timeout. One thread per
# call is also faster for single small images, which is all we ever give it.
# Harmless where Tesseract has no OpenMP, as on macOS via Homebrew.
_ENV = {**os.environ, "OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1"}

# Generous: this is a guard against a hung binary, not a performance budget.
_TIMEOUT = float(os.environ.get("BS_OCR_TIMEOUT", "60"))


def _tesseract(img: np.ndarray, psm: int) -> str:
    ok, png = cv2.imencode(".png", img)
    if not ok:
        return ""
    try:
        res = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", str(psm), "-l", "eng",
             "-c", f"tessedit_char_whitelist={_WHITELIST}"],
            input=png.tobytes(), capture_output=True, timeout=_TIMEOUT, env=_ENV)
    except subprocess.TimeoutExpired:
        # A slow or wedged OCR call must degrade the read, not fail the page:
        # the number band is one signal among several (SPEC 5.4).
        return ""
    return res.stdout.decode(errors="ignore").strip()


def parse(text: str) -> NumberRead:
    t = text.upper().replace("O", "0").replace("\\", "/").replace("|", "/")
    m = _NUM_RE.search(t)
    if not m:
        return NumberRead(text)
    return NumberRead(text, m.group("prefix") or "", int(m.group("num")), int(m.group("total")))


# Page-segmentation modes to try, in order. PSM 7 ("one text line") is absent
# deliberately: measured against printed numbers on real cards it scored 0.007
# on clean scans and 0.000 degraded, and dropping it lost none of the 200 cards
# the full set read correctly. It was a third of the Tesseract calls.
PSMS = (11, 6)


def read_number(card_bgr: np.ndarray) -> NumberRead:
    if not available():
        return NumberRead("")
    band = crop_frac(canonical(card_bgr) if card_bgr.shape[1] < 400 else card_bgr, NUMBER_BAND)
    grey = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    grey = cv2.resize(grey, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    # Adaptive thresholding copes with glare gradients and the card's own
    # coloured bands; global (Otsu) thresholding merges text into the frame.
    variants = [
        cv2.adaptiveThreshold(grey, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 15),
        cv2.adaptiveThreshold(grey, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8),
    ]
    texts, reads = [], []
    for img in variants:
        for psm in PSMS:
            text = _tesseract(img, psm)
            texts.append(text)
            read = parse(text)
            if read.ok:
                reads.append(read)
                # Two independent reads agreeing is enough; saves Tesseract calls.
                if sum(1 for r in reads if (r.number, r.total) == (read.number, read.total)) >= 2:
                    return NumberRead(read.text, read.prefix, read.number, read.total,
                                      votes=2, attempts=len(texts))
    if not reads:
        return NumberRead(" | ".join(t for t in texts if t))
    # Vote number and total separately: one misread digit shouldn't win.
    number = collections.Counter(r.number for r in reads).most_common(1)[0][0]
    totals = collections.Counter(r.total for r in reads if r.number == number)
    total = totals.most_common(1)[0][0]
    agree = sum(1 for r in reads if r.number == number and r.total == total)
    best = next(r for r in reads if r.number == number and r.total == total)
    return NumberRead(best.text, best.prefix, number, total, votes=agree, attempts=len(texts))
