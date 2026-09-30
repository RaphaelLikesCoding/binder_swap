"""How well does the number reader actually read real cards?

    python -m binderswap.recognition.ocrcheck [n] [severity]

Renders each sampled card through the same degradation as ``scalecheck``, reads
its number band, and scores an exact match on BOTH the number and the printed
total. Reports per-attempt accuracy so the (threshold variant, PSM) grid can be
justified rather than assumed -- that is how PSM 7 was found to contribute
nothing while costing a third of the Tesseract calls.

This number is load-bearing. The band is what separates reprints (it settles
~97% of the near-duplicate tail) and is the only per-card identity on puzzle
cards, whose art runs continuously across pockets. Needs build/images and
build/catalog.
"""
import collections
import sqlite3
import sys
import time
import zlib
import concurrent.futures as cf

import cv2
import numpy as np
from pathlib import Path
from binderswap.recognition import ocr
from binderswap.recognition.features import canonical, crop_frac, NUMBER_BAND

from .scalecheck import degrade                     # same degradation as scalecheck

N = int(sys.argv[1]) if len(sys.argv) > 1 else 120
SEV = float(sys.argv[2]) if len(sys.argv) > 2 else 0.35

cat = sqlite3.connect("build/catalog/catalog.sqlite")
man = sqlite3.connect("build/images/manifest.sqlite")
rows = cat.execute("""select c.id, c.local_id, s.printed_total from cards c
                      join sets s on s.id=c.set_id
                      where c.lang='en' and s.printed_total is not null""").fetchall()
paths = dict(man.execute("select card_id, path from images where status='ok'"))
rows = [r for r in rows if r[0] in paths and str(r[1]).isdigit()]
rng = np.random.default_rng(0)
pick = [rows[i] for i in rng.choice(len(rows), size=min(N, len(rows)), replace=False)]
print(f"{len(pick)} cards, severity {SEV}")

VARIANTS = [(51, 15), (31, 8)]
PSMS = (11, 6, 7)

def card_seed(card_id: str) -> int:
    """A per-card seed that is the same in every process.

    ``hash()`` on a str is salted per interpreter, so seeding degradation with
    it gives each card different damage on every run. The baseline then wanders
    by more than the effects being measured -- it moved 0.04 between two runs
    of the same cards here, which is larger than the number-band signal.
    """
    return zlib.crc32(card_id.encode()) & 0xffffffff


def work(row):
    cid, local, total = row
    img = cv2.imread(paths[cid], cv2.IMREAD_COLOR)
    if img is None: return None
    r = np.random.default_rng(card_seed(cid))
    card = degrade(img, r, SEV)
    # mirror read_number: only shrink to canonical if the crop is already small
    band = crop_frac(canonical(card) if card.shape[1] < 400 else card, NUMBER_BAND)
    grey = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    grey = cv2.resize(grey, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    out = {}
    for vi,(blk,C) in enumerate(VARIANTS):
        v = cv2.adaptiveThreshold(grey,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,blk,C)
        for psm in PSMS:
            rd = ocr.parse(ocr._tesseract(v, psm))
            out[(vi,psm)] = bool(rd.ok and rd.number == int(local) and rd.total == int(total))
    return out

t0=time.time()
res=[]
with cf.ThreadPoolExecutor(max_workers=12) as pool:
    for o in pool.map(work, pick):
        if o: res.append(o)
print(f"{len(res)} scored in {time.time()-t0:.0f}s\n")

combos = [(vi,psm) for vi in range(len(VARIANTS)) for psm in PSMS]
print("per-attempt accuracy (exact number AND total):")
for c in combos:
    acc = sum(r[c] for r in res)/len(res)
    print(f"   variant{c[0]} psm{c[1]}: {acc:.3f}")
any_all = sum(any(r[c] for c in combos) for r in res)/len(res)
print(f"\nANY of the six correct: {any_all:.3f}")
keep = [c for c in combos if c[1] != 7]
u4 = sum(any(r[x] for x in keep) for r in res)/len(res)
lost = sum(1 for r in res if any(r[x] for x in combos) and not any(r[x] for x in keep))
print(f"DROP BOTH PSM7 -> {u4:.3f}  (vs {any_all:.3f}); cards lost: {lost}/{len(res)}")
print("\nleave-one-out (union accuracy without that attempt):")
for c in combos:
    rest=[x for x in combos if x!=c]
    u = sum(any(r[x] for x in rest) for r in res)/len(res)
    print(f"   drop variant{c[0]} psm{c[1]}: {u:.3f}   (loses {any_all-u:+.3f})")
print("\nbest single, pair, triple by union accuracy:")
import itertools
for k in (1,2,3):
    best=max(itertools.combinations(combos,k),
             key=lambda cc: sum(any(r[x] for x in cc) for r in res))
    u=sum(any(r[x] for x in best) for r in res)/len(res)
    print(f"   k={k}: {best} -> {u:.3f}")
