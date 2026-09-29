"""Binder page geometry: find the page, flatten it, find the pocket grid, crop cards."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Binder pocket layouts, rows x cols. Portrait and landscape pages both exist,
# so these come in pairs; (1, 1) is deliberately absent because a single cell
# has no interior gutter to score and outscores every real grid on brightness.
COMMON_LAYOUTS = [(3, 3), (2, 2), (3, 4), (4, 3), (4, 4), (2, 3), (3, 2),
                  (2, 4), (4, 2), (1, 2), (2, 1), (1, 3), (3, 1)]
PAGE_WIDTH = 1500  # rectified page width in px


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.float32([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]])


def page_candidates(photo: np.ndarray) -> list[np.ndarray]:
    """Plausible page outlines, best guesses first; the full frame is always last.

    A single threshold is fragile (glare, bright tables, hands), so we propose
    several outlines and let ``locate_page`` keep the one whose flattened
    image has the clearest pocket grid.
    """
    h, w = photo.shape[:2]
    scale = 1000 / max(h, w)
    small = cv2.resize(photo, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    grey = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    area_total = small.shape[0] * small.shape[1]
    masks = [cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]
    # Distance from the table colour, estimated from the photo border.
    border = np.concatenate([small[:8].reshape(-1, 3), small[-8:].reshape(-1, 3),
                             small[:, :8].reshape(-1, 3), small[:, -8:].reshape(-1, 3)]).astype(np.float32)
    dist = np.linalg.norm(small.astype(np.float32) - np.median(border, axis=0), axis=2)
    masks.append(((dist > max(40.0, float(np.percentile(dist, 30)))) * 255).astype(np.uint8))
    quads = []
    for mask in masks:
        for k in (15, 41):
            m = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))  # cut glare bridges
            contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            c = max(contours, key=cv2.contourArea)
            if cv2.contourArea(c) < 0.2 * area_total:
                continue
            hull = cv2.convexHull(c)
            peri = cv2.arcLength(hull, True)
            for eps in (0.01, 0.02, 0.04):
                approx = cv2.approxPolyDP(hull, eps * peri, True)
                if len(approx) == 4:
                    quads.append(order_corners(approx / scale))
                    break
            quads.append(order_corners(cv2.boxPoints(cv2.minAreaRect(hull)) / scale))
    quads.append(np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
    return quads


def locate_page(photo: np.ndarray, layout: tuple[int, int] | None = None) -> tuple[np.ndarray, np.ndarray, bool]:
    """Pick the page outline whose flattened page has the strongest pocket grid.

    Returns (corners, flattened page, found) where found=False means the full
    frame was used.
    """
    cands = page_candidates(photo)
    best = None
    for i, quad in enumerate(cands):
        page = rectify(photo, quad, width=600)
        score = grid_score(page, layout)
        if best is None or score > best[0] + 1e-3:
            best = (score, i, quad)
    _, i, quad = best
    return quad, rectify(photo, quad), i < len(cands) - 1


def rectify(photo: np.ndarray, corners: np.ndarray, width: int = PAGE_WIDTH) -> np.ndarray:
    tl, tr, br, bl = corners
    w_est = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    h_est = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    height = int(round(width * h_est / max(w_est, 1)))
    dst = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    m = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
    return cv2.warpPerspective(photo, m, (width, height), flags=cv2.INTER_CUBIC)


def cardness(page: np.ndarray) -> np.ndarray:
    """Per-pixel evidence of 'card, not sleeve plastic': saturation + edges.

    Sleeve plastic and page backing are pale and smooth; card fronts are
    colourful and busy. Glare lowers both, which is why grid finding uses
    whole-row/column profiles rather than per-pixel decisions.
    """
    hsv = cv2.cvtColor(page, cv2.COLOR_BGR2HSV)
    sat = hsv[..., 1].astype(np.float32) / 255.0
    grey = cv2.GaussianBlur(cv2.cvtColor(page, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    edges = cv2.Canny(grey, 40, 120).astype(np.float32) / 255.0
    edges = cv2.blur(edges, (9, 9))
    return 0.6 * sat + 0.4 * np.clip(edges * 4, 0, 1)


def _gutter_score(profile: np.ndarray, n: int) -> float:
    """How strongly the profile dips at the n-1 interior boundaries of n equal cells."""
    if n == 1:
        return 0.0
    length = len(profile)
    half = max(2, int(0.012 * length))
    dips = [profile[max(0, int(k * length / n) - half):int(k * length / n) + half + 1].min() for k in range(1, n)]
    cells = [np.median(profile[int((k + 0.2) * length / n):int((k + 0.8) * length / n)]) for k in range(n)]
    return float(np.median(cells) - np.mean(dips)) / (float(np.median(cells)) + 1e-6)


def content_bounds(page: np.ndarray, card_map: np.ndarray | None = None) -> tuple[int, int, int, int]:
    """Bounding box (x0, y0, x1, y1) of the pocket area, trimming empty page margins."""
    cm = cardness(page) if card_map is None else card_map
    h, w = cm.shape
    bounds = []
    for axis, length in ((0, w), (1, h)):
        prof = cv2.GaussianBlur(cm.mean(axis=axis).reshape(1, -1), (1, 0), sigmaX=3).ravel()
        on = np.nonzero(prof > 0.35 * np.percentile(prof, 90))[0]
        lo, hi = (int(on[0]), int(on[-1]) + 1) if len(on) else (0, length)
        bounds.append((lo, hi))
    (x0, x1), (y0, y1) = bounds
    return x0, y0, x1, y1


def _layout_scores(page: np.ndarray, layouts) -> list[tuple[float, tuple[int, int]]]:
    cm = cardness(page)
    x0, y0, x1, y1 = content_bounds(page, cm)
    area = cm[y0:y1, x0:x1]
    if area.size == 0:
        return []
    col_prof, row_prof = area.mean(axis=0), area.mean(axis=1)
    out = []
    for rows, cols in layouts:
        # Pockets hold upright cards: reject grids whose cells are far from card-shaped.
        cell_aspect = ((x1 - x0) / cols) / max(1e-6, (y1 - y0) / rows)
        if not 0.55 < cell_aspect < 0.95:
            continue
        out.append((_gutter_score(col_prof, cols) + _gutter_score(row_prof, rows), (rows, cols)))
    return out


def grid_score(page: np.ndarray, layout: tuple[int, int] | None = None) -> float:
    """How clearly the page shows a pocket grid (of ``layout``, or the best one)."""
    scores = _layout_scores(page, [layout] if layout else COMMON_LAYOUTS)
    return max((s for s, _ in scores), default=0.0)


def guess_layout(page: np.ndarray) -> tuple[int, int]:
    """Infer (rows, cols) from the periodic gutters between pockets.

    Works with empty pockets and glare because it scores whole-page profiles;
    the binder's layout is confirmed by the user once and then passed in.
    """
    scores = _layout_scores(page, COMMON_LAYOUTS)
    return max(scores)[1] if scores else (3, 3)


@dataclass
class Slot:
    index: int
    row: int
    col: int
    box: tuple[int, int, int, int]       # pocket box on the flattened page
    card_box: tuple[int, int, int, int] | None  # detected card inside the pocket


def _card_in_pocket(page: np.ndarray, cm: np.ndarray, box: tuple[int, int, int, int]):
    x, y, w, h = box
    roi = cm[y:y + h, x:x + w]
    if roi.size == 0:
        return None
    mask = (roi > max(0.18, float(np.percentile(roi, 20)) + 0.1)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    bx, by, bw, bh = cv2.boundingRect(c)
    if bw * bh < 0.45 * w * h or not 0.55 < bw / bh < 0.9:
        return None
    return (x + bx, y + by, bw, bh)


def slots_for(page: np.ndarray, layout: tuple[int, int]) -> list[Slot]:
    """Split the pocket area into a uniform grid and locate the card in each pocket."""
    rows, cols = layout
    cm = cardness(page)
    x0, y0, x1, y1 = content_bounds(page, cm)
    sw, sh = (x1 - x0) / cols, (y1 - y0) / rows
    slots = []
    for i in range(rows * cols):
        r, c = divmod(i, cols)
        box = (int(x0 + c * sw), int(y0 + r * sh), int(sw), int(sh))
        slots.append(Slot(i, r, c, box, _card_in_pocket(page, cm, box)))
    return slots


def crop_card(page: np.ndarray, slot: Slot) -> np.ndarray:
    """Crop the card in a pocket, refining to its exact edges when possible."""
    x, y, w, h = slot.card_box or slot.box
    pad = int(0.03 * max(w, h))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(page.shape[1], x + w + pad), min(page.shape[0], y + h + pad)
    roi = page[y0:y1, x0:x1]
    grey = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.dilate(cv2.Canny(cv2.GaussianBlur(grey, (5, 5), 0), 30, 90), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        c = max(contours, key=cv2.contourArea)
        if cv2.contourArea(c) > 0.6 * w * h:
            rect = cv2.minAreaRect(c)
            (rw, rh) = rect[1]
            if rw > 0 and rh > 0 and 0.6 < min(rw, rh) / max(rw, rh) < 0.8:
                corners = order_corners(cv2.boxPoints(rect))
                dst = np.float32([[0, 0], [480, 0], [480, 672], [0, 672]])
                m = cv2.getPerspectiveTransform(corners, dst)
                return cv2.warpPerspective(roi, m, (480, 672), flags=cv2.INTER_CUBIC)
    inner = page[y:y + h, x:x + w]
    return cv2.resize(inner, (480, 672), interpolation=cv2.INTER_CUBIC)


def pocket_is_empty(page: np.ndarray, slot: Slot) -> bool:
    """A pocket with no card-shaped content. Kept separate from card detection so
    a card hidden by glare is 'unknown' (ask the user), not silently 'empty'."""
    if slot.card_box is not None:
        return False
    x, y, w, h = slot.box
    inset = page[y + h // 6:y + h - h // 6, x + w // 6:x + w - w // 6]
    return float(np.percentile(cardness(inset), 75)) < 0.2
