"""Synthetic cards and binder-page photos for tests and pipeline development.

Real card images and real binder photos are what matter for accuracy; these
fakes exist so every stage (fetch, index, page detection, grid, OCR, matching,
set-mode inference) can be exercised end to end, deterministically, in CI.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .recognition.features import CARD_H, CARD_W

TYPE_COLOURS = [(60, 170, 90), (40, 90, 220), (200, 120, 40), (40, 200, 230), (160, 80, 170), (120, 120, 120)]



def _stable_seed(text: str) -> int:
    h = 2166136261
    for ch in text.encode():
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h


def make_card(card_id: str, name: str, number: str, total: int, scale: int = 3) -> np.ndarray:
    """A fake card at ``scale`` x canonical size with unique procedural art."""
    rng = np.random.default_rng(_stable_seed(card_id))
    w, h = CARD_W * scale, CARD_H * scale
    card = np.full((h, w, 3), (40, 200, 235), np.uint8)  # yellow border (BGR)
    frame = TYPE_COLOURS[int(rng.integers(len(TYPE_COLOURS)))]
    b = int(0.045 * w)
    cv2.rectangle(card, (b, b), (w - b, h - b), frame, -1)
    # Art window with random shapes: the identity of the card.
    x0, y0, x1, y1 = int(0.08 * w), int(0.10 * h), int(0.92 * w), int(0.52 * h)
    art = np.zeros((y1 - y0, x1 - x0, 3), np.uint8)
    top, bottom = rng.integers(0, 255, 3), rng.integers(0, 255, 3)
    for row in range(art.shape[0]):
        t = row / max(1, art.shape[0] - 1)
        art[row, :] = (top * (1 - t) + bottom * t).astype(np.uint8)
    for _ in range(int(rng.integers(6, 12))):
        colour = tuple(int(c) for c in rng.integers(0, 255, 3))
        cx, cy = int(rng.integers(0, art.shape[1])), int(rng.integers(0, art.shape[0]))
        if rng.random() < 0.5:
            cv2.circle(art, (cx, cy), int(rng.integers(10, 60)) * scale // 3 + 5, colour, -1)
        else:
            pts = rng.integers(0, [art.shape[1], art.shape[0]], (3, 2)).astype(np.int32)
            cv2.fillPoly(art, [pts], colour)
    card[y0:y1, x0:x1] = art
    cv2.rectangle(card, (x0, y0), (x1, y1), (30, 30, 30), 2)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(card, name[:14], (int(0.1 * w), int(0.075 * h)), font, 0.55 * scale / 3 * 2, (20, 20, 20), 2)
    # Text box body
    cv2.rectangle(card, (int(0.08 * w), int(0.56 * h)), (int(0.92 * w), int(0.86 * h)), (235, 235, 235), -1)
    # Collector number in the bottom band, dark on light for OCR.
    label = f"{number}/{total:03d}"
    cv2.rectangle(card, (int(0.06 * w), int(0.895 * h)), (int(0.94 * w), int(0.975 * h)), (245, 245, 245), -1)
    cv2.putText(card, label, (int(0.55 * w), int(0.955 * h)), font, 0.5 * scale / 3 * 2, (0, 0, 0), 2)
    return card


@dataclass
class PageSpec:
    rows: int = 3
    cols: int = 3
    slots: list[np.ndarray | None] | None = None  # row-major; None = empty pocket


def make_page(spec: PageSpec, seed: int = 0, perspective: float = 0.06, glare: bool = True,
              noise: float = 4.0, blur: int = 1, width: int = 1600) -> tuple[np.ndarray, np.ndarray]:
    """Render a binder page photo. Returns (photo, page_corners_in_photo)."""
    rng = np.random.default_rng(seed)
    pocket_w, pocket_h, gap, margin = 240 * 2, 336 * 2, 24, 40
    pw = margin * 2 + spec.cols * pocket_w + (spec.cols - 1) * gap
    ph = margin * 2 + spec.rows * pocket_h + (spec.rows - 1) * gap
    page = np.full((ph, pw, 3), (205, 205, 200), np.uint8)  # sleeve/page plastic
    for i in range(spec.rows * spec.cols):
        r, c = divmod(i, spec.cols)
        x, y = margin + c * (pocket_w + gap), margin + r * (pocket_h + gap)
        cv2.rectangle(page, (x - 4, y - 4), (x + pocket_w + 4, y + pocket_h + 4), (185, 185, 180), 2)
        card = spec.slots[i] if spec.slots and i < len(spec.slots) else None
        if card is not None:
            page[y:y + pocket_h, x:x + pocket_w] = cv2.resize(card, (pocket_w, pocket_h), interpolation=cv2.INTER_AREA)
    # Place the page on a dark table with a random perspective.
    scale = width / pw
    page = cv2.resize(page, (width, int(ph * scale)), interpolation=cv2.INTER_AREA)
    ph, pw = page.shape[:2]
    canvas_w, canvas_h = int(pw * 1.25), int(ph * 1.2)
    ox, oy = (canvas_w - pw) // 2, (canvas_h - ph) // 2
    src = np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]])
    jitter = rng.uniform(-perspective, perspective, (4, 2)) * [pw, ph]
    dst = (src + [ox, oy] + jitter).astype(np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    table = np.full((canvas_h, canvas_w, 3), (45, 38, 34), np.uint8)
    photo = cv2.warpPerspective(page, m, (canvas_w, canvas_h), dst=table, borderMode=cv2.BORDER_TRANSPARENT)
    if glare:
        # Sleeve glare: bright soft blobs on the page (not the table).
        page_mask = np.zeros(photo.shape[:2], np.uint8)
        cv2.fillConvexPoly(page_mask, dst.astype(np.int32), 1)
        overlay = np.zeros(photo.shape[:2], np.float32)
        for _ in range(2):
            cx, cy = rng.uniform(dst[:, 0].min(), dst[:, 0].max()), rng.uniform(dst[:, 1].min(), dst[:, 1].max())
            cv2.ellipse(overlay, (int(cx), int(cy)), (int(canvas_w * 0.12), int(canvas_h * 0.05)),
                        float(rng.uniform(0, 180)), 0, 360, 1.0, -1)
        overlay = cv2.GaussianBlur(overlay, (0, 0), canvas_w * 0.02) * 0.55 * page_mask
        photo = (photo * (1 - overlay[..., None]) + 255 * overlay[..., None]).astype(np.uint8)
    if noise:
        photo = np.clip(photo + rng.normal(0, noise, photo.shape), 0, 255).astype(np.uint8)
    if blur:
        photo = cv2.GaussianBlur(photo, (blur * 2 + 1, blur * 2 + 1), 0)
    return photo, dst
