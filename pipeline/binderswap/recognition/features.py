"""Image features shared by the reference index and the page recognizer.

Everything operates on a *canonical* card image: the card cropped to its edges,
upright, resized to CARD_W x CARD_H (63x88mm aspect).

The ``Embedder`` interface is the seam for better models. The default
``ClassicEmbedder`` needs no downloaded weights (art thumbnail + colour
histogram), which is enough to build and evaluate the pipeline end to end. A
learned embedder (Core ML / Vision feature print on iOS, an ONNX model on the
server) replaces it without changing the index or matcher code, as long as the
index is rebuilt with the same embedder: every index records its embedder id.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

CARD_W, CARD_H = 240, 336  # 63 x 88 mm

# Illustration window of a standard-frame Pokémon card, as fractions of the card.
# Full-art cards have no window, but the region still covers the busiest part of
# the art, so the same crop works as a descriptor for both.
ART_BOX = (0.08, 0.10, 0.92, 0.52)  # x0, y0, x1, y1

# Bottom band where the collector number / set code is printed.
NUMBER_BAND = (0.0, 0.88, 1.0, 1.0)


def canonical(img: np.ndarray) -> np.ndarray:
    return cv2.resize(img, (CARD_W, CARD_H), interpolation=cv2.INTER_AREA)


def crop_frac(img: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


class Embedder:
    id: str = "base"
    dim: int = 0

    def embed(self, card_bgr: np.ndarray) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class ClassicEmbedder(Embedder):
    """Weight-free descriptor: normalized art thumbnail + HSV histograms.

    * Art thumbnail (32x24 grey, zero-mean/unit-variance): captures layout and
      shapes; robust to overall brightness and contrast changes from sleeves.
    * HSV histogram of the art and of the whole card (Hellinger-normalized):
      captures palette and frame colour (energy type), robust to small
      misalignment.
    """

    thumb: tuple[int, int] = (24, 32)  # w, h
    art_weight: float = 0.75
    hist_weight: float = 0.25
    id: str = "classic-v1"

    @property
    def dim(self) -> int:  # type: ignore[override]
        return self.thumb[0] * self.thumb[1] + 2 * (8 * 4 * 4)

    def embed(self, card_bgr: np.ndarray) -> np.ndarray:
        card = canonical(card_bgr)
        art = crop_frac(card, ART_BOX)
        grey = cv2.cvtColor(art, cv2.COLOR_BGR2GRAY)
        t = cv2.resize(grey, self.thumb, interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
        t = (t - t.mean()) / (t.std() + 1e-6)
        parts = [_unit(t) * self.art_weight]
        for region in (art, card):
            hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
            h = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256]).ravel()
            h = np.sqrt(h / (h.sum() + 1e-6))
            parts.append(_unit(h) * self.hist_weight)
        return _unit(np.concatenate(parts).astype(np.float32))


def default_embedder() -> Embedder:
    return ClassicEmbedder()


class OrbVerifier:
    """Geometric verification for re-ranking the top few candidates.

    Counts RANSAC-consistent ORB matches between a query card and a reference
    card. Distinguishes near-identical embeddings (reprints with the same art
    but different frames) far better than global descriptors.
    """

    def __init__(self, features: int = 600):
        self.orb = cv2.ORB_create(nfeatures=features)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    def describe(self, card_bgr: np.ndarray):
        grey = cv2.cvtColor(canonical(card_bgr), cv2.COLOR_BGR2GRAY)
        return self.orb.detectAndCompute(grey, None)

    def inliers(self, query, ref) -> int:
        (kq, dq), (kr, dr) = query, ref
        if dq is None or dr is None or len(kq) < 8 or len(kr) < 8:
            return 0
        pairs = self.matcher.knnMatch(dq, dr, k=2)
        good = [m for m, *rest in pairs if rest and m.distance < 0.8 * rest[0].distance]
        if len(good) < 8:
            return len(good) // 2
        src = np.float32([kq[m.queryIdx].pt for m in good])
        dst = np.float32([kr[m.trainIdx].pt for m in good])
        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
        return int(mask.sum()) if mask is not None else 0
