"""Does matching the number band add anything over the visual score?

    python -m binderswap.recognition.bandcheck [severity] [n]

The recogniser never needs a free-text read of a card's number: it has k
candidates whose numbers are already known, and a clean reference image for
each. So compare the observed band to each candidate's band instead. ART_BOX
and NUMBER_BAND are disjoint, so this is independent evidence.

Answer, kept here because it is a negative: on a random card it HURTS (0.973
visual alone vs 0.963 fused). On the near-duplicate tail it is real but small
(0.533 -> 0.623 at mild degradation, n=600) and vanishes under heavy damage.
Most of the band is identical on a reprint -- copyright line, illustrator
credit -- so only a few digits carry the difference and correlation dilutes it.


Earlier runs seeded degradation with hash(cid). Python salts string hashing per
process, so the same card got different damage on every run and the baseline
wandered by 0.04 -- larger than the effect being measured. zlib.crc32 is stable
across processes, so the arms now differ by the treatment and nothing else.
"""
import sqlite3, sys, zlib
import concurrent.futures as cf
import cv2, numpy as np
from pathlib import Path
from binderswap.recognition.scalecheck import degrade
from binderswap.images.index import ReferenceIndex
from binderswap.recognition.features import canonical, crop_frac, NUMBER_BAND, default_embedder

SEV = float(sys.argv[1]) if len(sys.argv) > 1 else 0.35
N   = int(sys.argv[2]) if len(sys.argv) > 2 else 600
K = 4
idx = ReferenceIndex.load(Path("build/index/en.npz")); emb = default_embedder()
V = idx.vectors; ids = np.array([str(x) for x in idx.ids])
paths = dict(sqlite3.connect("build/images/manifest.sqlite")
             .execute("select card_id, path from images where status='ok'"))

def seed(cid):                      # stable across processes, unlike hash()
    return zlib.crc32(cid.encode()) & 0xffffffff

tail = []
for s in range(0, len(V), 2000):
    sims = V[s:s+2000] @ V.T
    for r in range(sims.shape[0]):
        i = s + r; sims[r, i] = -np.inf
        if 1.0 - float(sims[r].max()) <= 0.01: tail.append(i)

def band(img):
    b = crop_frac(canonical(img), NUMBER_BAND)
    g = cv2.cvtColor(cv2.resize(b, (480, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (3, 3), 0).astype(np.float32)
    return (g - g.mean()) / (g.std() + 1e-6)

cache = {}
def ref(cid):
    if cid not in cache:
        p = paths.get(cid); im = cv2.imread(p, cv2.IMREAD_COLOR) if p else None
        cache[cid] = band(im) if im is not None else None
    return cache[cid]

WEIGHTS = [0.0, 0.25, 0.5, 1.0, 2.0]
def work(i):
    cid = ids[i]
    if cid not in paths: return None
    im = cv2.imread(paths[cid], cv2.IMREAD_COLOR)
    if im is None: return None
    dq = degrade(im, np.random.default_rng(seed(cid)), SEV)
    sims = V @ emb.embed(dq)
    top = np.argpartition(-sims, K)[:K]; top = top[np.argsort(-sims[top])]
    cands = [ids[t] for t in top]
    obs = band(dq)
    bs = [(-1.0 if ref(c) is None else float((obs * ref(c)).mean())) for c in cands]
    out = [cid in cands]
    for w in WEIGHTS:
        fused = [float(sims[t]) + w*b for t, b in zip(top, bs)]
        out.append(cands[int(np.argmax(fused))] == cid)
    return out

rng = np.random.default_rng(5)
pick = [tail[i] for i in rng.choice(len(tail), size=min(N, len(tail)), replace=False)]
res = [r for r in cf.ThreadPoolExecutor(max_workers=8).map(work, pick) if r]
n = len(res)
ceil = sum(r[0] for r in res)/n
print(f"near-duplicate tail, n={n}, severity {SEV}")
print(f"  true card in top-{K} (ceiling)   {ceil:.3f}")
for wi, w in enumerate(WEIGHTS):
    acc = sum(r[wi+1] for r in res)/n
    se = (acc*(1-acc)/n) ** 0.5
    tag = "  <- visual alone" if w == 0 else ""
    print(f"  band weight {w:<5}              {acc:.3f} +/- {1.96*se:.3f}{tag}")
