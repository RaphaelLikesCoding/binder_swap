"""Does the embedder still discriminate when the pool is the whole catalog?

    python -m binderswap.recognition.scalecheck --index build/index/en.npz --n 400

The test suite self-matches against a synthetic 80-card world. This asks the
same question against all 19,724 EN (or 7,517 JA) cards, which is a different
question: what breaks at scale is not recall but near-duplicates.

Three questions, cheapest first:

  1. self-match   -- embed the reference image itself and search. Must be 100%.
                     Anything less is a bug, not a finding.
  2. margin       -- cos(self) - cos(nearest OTHER card). This is the headroom
                     a real photo has to spend. A card whose nearest neighbour
                     sits at margin ~0 is one JPEG artefact from being wrong.
  3. perturbation -- degrade the reference image the way a phone camera and a
                     binder pocket would, then search the full index. This is
                     the kill gate.

(3) is an UPPER BOUND on real accuracy, twice over: it starts from clean
scanned art, so it cannot model glare on plastic, focus falloff or a camera's
colour response; and it scores the embedder ALONE, where the recognizer also
has OCR, ORB re-ranking and page priors. Failing it means the descriptor is
dead. Passing it means only that it is not already dead -- real numbers need
labelled photos (BLOCKERS #2).

Top-4 is the number to read: the picker shows four candidates (SPEC 5.5), so
a card in the top four costs one swipe, not an error.
"""
import argparse, json, sys, time
from pathlib import Path
import cv2, numpy as np




def load_index(p: Path):
    from binderswap.images.index import ReferenceIndex
    return ReferenceIndex.load(p)


def warp(img, rng, severity):
    """Small homography: a binder page is never exactly parallel to the sensor."""
    h, w = img.shape[:2]
    d = severity * 0.045 * min(h, w)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = src + rng.uniform(-d, d, src.shape).astype(np.float32)
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)


def glare(img, rng, severity):
    """Additive soft blob: the ceiling light in the binder's plastic sleeve."""
    h, w = img.shape[:2]
    y, x = np.ogrid[:h, :w]
    cy, cx = rng.uniform(0.15, 0.85, 2) * [h, w]
    r = rng.uniform(0.25, 0.5) * min(h, w)
    g = np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * r * r))).astype(np.float32)
    return np.clip(img.astype(np.float32) + (severity * 110.0) * g[..., None], 0, 255).astype(np.uint8)


def degrade(img, rng, severity):
    if severity <= 0:
        return img
    out = warp(img, rng, severity)
    # resolution loss: a card is a small part of a page photo
    f = 1.0 - 0.55 * severity
    small = cv2.resize(out, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    out = cv2.resize(small, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)
    k = int(2 * round(severity * 2) + 1)
    if k > 1:
        out = cv2.GaussianBlur(out, (k, k), 0)
    out = glare(out, rng, severity)
    # white balance / exposure drift
    out = np.clip(out.astype(np.float32) * rng.uniform(1 - .18 * severity, 1 + .18 * severity, 3)
                  + rng.uniform(-22, 22) * severity, 0, 255).astype(np.uint8)
    q = int(90 - 55 * severity)
    ok, enc = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR) if ok else out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=Path, default=Path("build/index/en.npz"))
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    from binderswap.recognition.features import default_embedder
    emb = default_embedder()
    idx = load_index(args.index)
    N, D = idx.vectors.shape
    print(f"index: {N} cards, dim {D}, embedder {idx.embedder_id}", flush=True)

    rng = np.random.default_rng(args.seed)
    pick = rng.choice(N, size=min(args.n, N), replace=False)

    # ---- 2. margin: nearest OTHER card, over the whole index -----------------
    t0 = time.time()
    sims = idx.vectors[pick] @ idx.vectors.T          # (n, N)
    self_sim = sims[np.arange(len(pick)), pick].copy()
    sims[np.arange(len(pick)), pick] = -np.inf
    nn = sims.argmax(1)
    nn_sim = sims[np.arange(len(pick)), nn]
    margin = self_sim - nn_sim
    print(f"margin over {len(pick)} cards vs all {N} (computed in {time.time()-t0:.1f}s)")
    for q in (1, 5, 25, 50):
        print(f"   p{q:<2} margin {np.percentile(margin, q):.4f}")
    print(f"   nearest-other cosine: median {np.median(nn_sim):.4f}  max {nn_sim.max():.4f}")
    tight = int((margin < 0.01).sum())
    print(f"   cards whose nearest neighbour is within 0.01: {tight}/{len(pick)} ({100*tight/len(pick):.1f}%)")
    print("   tightest pairs:")
    for i in np.argsort(margin)[:8]:
        print(f"      {str(idx.ids[pick[i]]):<22} vs {str(idx.ids[nn[i]]):<22} margin {margin[i]:.5f}")

    # ---- 1 & 3. self-match and perturbation ---------------------------------
    rows = []
    for sev in (0.0, 0.35, 0.7, 1.0):
        r = np.random.default_rng(args.seed + 1)
        ranks, miss = [], 0
        for i in pick:
            img = cv2.imread(str(idx.paths[i]), cv2.IMREAD_COLOR)
            if img is None:
                miss += 1
                continue
            v = emb.embed(degrade(img, r, sev))
            s = idx.vectors @ v
            ranks.append(int((s > s[i]).sum()))     # 0 == top-1
        ranks = np.array(ranks)
        row = dict(severity=sev, n=len(ranks), unreadable=miss,
                   top1=float((ranks == 0).mean()), top5=float((ranks < 5).mean()),
                   top4=float((ranks < 4).mean()), top20=float((ranks < 20).mean()), median_rank=float(np.median(ranks)))
        rows.append(row)
        print(f"severity {sev:>4}: n={row['n']:<4} top1={row['top1']:.3f} "
              f"TOP4={row['top4']:.3f} top20={row['top20']:.3f} median_rank={row['median_rank']:.0f}",
              flush=True)

    print(f"\nchance top-1 for reference: {1/N:.6f}")
    if args.out:
        args.out.write_text(json.dumps(
            {"index": str(args.index), "n_pool": int(N), "rows": rows,
             "margin_p1": float(np.percentile(margin, 1)),
             "margin_p25": float(np.percentile(margin, 25)),
             "tight_frac": tight / len(pick)}, indent=2))


if __name__ == "__main__":
    main()
