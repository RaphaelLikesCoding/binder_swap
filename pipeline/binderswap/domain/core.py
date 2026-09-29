"""Reference implementation of Binder Swap's collection and trading rules (spec §4, §6.1, §7.4).

This module is the executable specification. The iOS app implements the same
rules in Swift and must pass the same JSON test vectors in ``spec/vectors/``.
Everything is derived, never stored: flipping a binder's type immediately
changes what is tradeable and what is wished for, and nothing needs migrating.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Iterable

CONDITIONS = ["DMG", "HP", "MP", "LP", "NM"]  # worst -> best
BINDER_TYPES = ("set", "trade", "collect")


@dataclass(frozen=True)
class Item:
    card_id: str
    variant: str = "normal"
    condition: str = "NM"
    keep: bool = False  # Trade binders only: never offer this copy


@dataclass
class Binder:
    id: str
    name: str
    type: str                                   # set | trade | collect
    rows: int = 3
    cols: int = 3
    pages: list[list[Item | None]] = field(default_factory=list)  # row-major pockets
    set_id: str | None = None                   # set binders
    include_secrets: bool = False               # set binders: also want numbers above printed total

    def items(self) -> Iterable[Item]:
        for page in self.pages:
            for slot in page:
                if slot is not None:
                    yield slot


@dataclass(frozen=True)
class Wish:
    card_id: str
    priority: str = "want"                      # need | want
    variant: str | None = None                  # None = any variant
    min_condition: str | None = None            # None = any condition
    quantity: int = 1
    source: str = "manual"                      # manual | set_gap
    binder_id: str | None = None                # set_gap: which set binder
    owned_elsewhere: tuple[str, ...] = ()       # set_gap: binders already holding this card


@dataclass
class Collection:
    binders: list[Binder] = field(default_factory=list)
    loose: list[Item] = field(default_factory=list)  # owned but not filed in a binder (e.g. received in a trade)
    manual_wishes: list[Wish] = field(default_factory=list)

    def all_items(self) -> Iterable[tuple[str | None, Item]]:
        for b in self.binders:
            for it in b.items():
                yield b.id, it
        for it in self.loose:
            yield None, it


@dataclass
class CatalogSet:
    """What set-gap logic needs: the set's main-numbered cards in order."""
    id: str
    printed_total: int
    cards: list[tuple[int, str]]                # (number, card_id), main numbering incl. secrets


# -- wishes --------------------------------------------------------------------

def set_gaps(binder: Binder, cset: CatalogSet, collection: Collection) -> list[Wish]:
    """Every card of the set not in this Set binder is a Need (spec §4.1)."""
    if binder.type != "set":
        return []
    have = {it.card_id for it in binder.items()}
    where: dict[str, list[str]] = {}
    for bid, it in collection.all_items():
        if bid != binder.id:
            where.setdefault(it.card_id, []).append(bid or "loose")
    out = []
    for number, cid in cset.cards:
        if number > cset.printed_total and not binder.include_secrets:
            continue
        if cid not in have:
            out.append(Wish(cid, "need", source="set_gap", binder_id=binder.id,
                            owned_elsewhere=tuple(sorted(set(where.get(cid, []))))))
    return out


def _owned_count(collection: Collection, wish: Wish) -> int:
    return sum(1 for _, it in collection.all_items()
               if it.card_id == wish.card_id and (wish.variant is None or it.variant == wish.variant)
               and _condition_ok(it.condition, wish.min_condition))


def wishlist(collection: Collection, sets: dict[str, CatalogSet]) -> list[Wish]:
    """Open wishes: unfulfilled manual wishes plus Set-binder gaps.

    A manual wish is fulfilled once enough matching copies are owned anywhere.
    """
    out = [w for w in collection.manual_wishes if _owned_count(collection, w) < w.quantity]
    for b in collection.binders:
        if b.type == "set" and b.set_id in sets:
            out.extend(set_gaps(b, sets[b.set_id], collection))
    return out


# -- tradeables ----------------------------------------------------------------

def tradeables(collection: Collection, sets: dict[str, CatalogSet]) -> list[Item]:
    """Items offered in swaps (spec §4.1 key rules).

    Only copies in Trade binders that aren't marked Keep, and never a card the
    owner currently needs (e.g. for a Set binder gap): you can't give away the
    card your own set is missing.
    """
    needed = {w.card_id for w in wishlist(collection, sets) if w.priority == "need"}
    return [it for b in collection.binders if b.type == "trade"
            for it in b.items() if not it.keep and it.card_id not in needed]


# -- matching ------------------------------------------------------------------

def _condition_ok(condition: str, minimum: str | None) -> bool:
    return minimum is None or CONDITIONS.index(condition) >= CONDITIONS.index(minimum)


@dataclass(frozen=True)
class Offer:
    item: Item
    priority: str
    value: float | None


@dataclass
class Match:
    for_me: list[Offer]                         # their tradeables I want
    for_them: list[Offer]                       # my tradeables they want
    near_misses: list[dict]                     # right card, wrong variant/condition


def profile(collection: Collection, sets: dict[str, CatalogSet]) -> dict:
    """What a phone shares in a swap (spec §7.3): tradeables and wants only."""
    return {"tradeables": [dataclasses.asdict(i) for i in tradeables(collection, sets)],
            "wants": [dataclasses.asdict(w) for w in wishlist(collection, sets)]}


def _value(item: Item, prices: dict[str, float]) -> float | None:
    return prices.get(f"{item.card_id}|{item.variant}", prices.get(item.card_id))


def _offers(tradeable: list[dict], wants: list[dict], prices: dict[str, float]) -> tuple[list[Offer], list[dict]]:
    """Match one side's tradeables against the other side's wants, copy by copy."""
    remaining = {id(w): w.get("quantity", 1) for w in wants}
    by_card: dict[str, list[dict]] = {}
    for w in wants:
        by_card.setdefault(w["card_id"], []).append(w)
    # Needs first so a scarce copy goes to the most important wish.
    for ws in by_card.values():
        ws.sort(key=lambda w: w.get("priority") != "need")
    offers, near = [], []
    for t in tradeable:
        item = Item(**t)
        hit, miss = None, None
        for w in by_card.get(item.card_id, []):
            if remaining[id(w)] <= 0:
                continue
            variant_ok = w.get("variant") in (None, item.variant)
            cond_ok = _condition_ok(item.condition, w.get("min_condition"))
            if variant_ok and cond_ok:
                hit = w
                break
            miss = miss or {"card_id": item.card_id, "offered_variant": item.variant,
                            "offered_condition": item.condition, "wanted_variant": w.get("variant"),
                            "wanted_min_condition": w.get("min_condition")}
        if hit:
            remaining[id(hit)] -= 1
            offers.append(Offer(item, hit.get("priority", "want"), _value(item, prices)))
        elif miss:
            near.append(miss)
    offers.sort(key=lambda o: (o.priority != "need", -(o.value or 0.0), o.item.card_id))
    return offers, near


def match(mine: dict, theirs: dict, prices: dict[str, float] | None = None) -> Match:
    prices = prices or {}
    for_me, near_me = _offers(theirs["tradeables"], mine["wants"], prices)
    for_them, near_them = _offers(mine["tradeables"], theirs["wants"], prices)
    return Match(for_me, for_them, near_me + near_them)


def suggest_fair_trade(m: Match, tolerance: float = 0.10) -> tuple[list[Offer], list[Offer]]:
    """Pick a subset of both sides whose values are within ``tolerance``.

    Deterministic greedy: start from everything; while the heavier side exceeds
    the lighter by more than the tolerance, drop the heavier side's item that
    best closes the gap, preferring Wants over Needs. Items without a price
    count as 0 and are kept (the users can discuss them).
    """
    get, give = list(m.for_me), list(m.for_them)
    if not get or not give:
        return get, give

    def total(xs):
        return sum(o.value or 0.0 for o in xs)

    while True:
        a, b = total(get), total(give)
        diff = abs(a - b)
        if diff <= tolerance * max(a, b) or max(a, b) == 0:
            break
        heavy = get if a > b else give
        if len(heavy) == 1:
            break
        best = None
        for o in heavy:
            if not o.value:
                continue
            new_diff = abs(diff - o.value)
            key = (o.priority == "need", new_diff, o.item.card_id)
            if new_diff < diff and (best is None or key < best[0]):
                best = (key, o)
        if best is None:
            break
        heavy.remove(best[1])
    return get, give


# -- recording trades ------------------------------------------------------------

@dataclass
class TradeRecord:
    id: str
    completed_at: str
    peer: str
    gave: list[Item]
    got: list[Item]


def apply_trade(collection: Collection, gave: list[Item], got: list[Item]) -> Collection:
    """Update inventory after both sides accept (spec §6.1: free for everyone).

    Given copies leave Trade binders first (their pocket becomes empty);
    received cards land in ``loose`` for the user to file. Raises if a given
    copy isn't tradeable, so a stale swap can't remove a kept or needed card.
    """
    col = dataclasses.replace(collection, binders=[dataclasses.replace(b, pages=[list(p) for p in b.pages])
                                                   for b in collection.binders],
                              loose=list(collection.loose))
    for item in gave:
        placed = False
        for b in col.binders:
            if b.type != "trade":
                continue
            for page in b.pages:
                for i, slot in enumerate(page):
                    if slot == item and not slot.keep:
                        page[i] = None
                        placed = True
                        break
                if placed:
                    break
            if placed:
                break
        if not placed:
            raise ValueError(f"not tradeable: {item}")
    col.loose.extend(got)
    return col


# -- plans ------------------------------------------------------------------------

PLANS = {
    # Proposed numbers (spec §6.1 [DECISION]); the structure is decided.
    "free": {"binders": 2, "scans_per_month": 20, "trade_history": 1, "cloud_backup": False, "children": 1},
    "premium_10": {"binders": 10, "scans_per_month": None, "trade_history": None, "cloud_backup": True, "children": 4},
    "premium_30": {"binders": 30, "scans_per_month": None, "trade_history": None, "cloud_backup": True, "children": 4},
    "premium_unlimited": {"binders": None, "scans_per_month": None, "trade_history": None, "cloud_backup": True,
                          "children": 4},
    "lifetime": {"binders": None, "scans_per_month": None, "trade_history": None, "cloud_backup": True, "children": 4},
}


def can_add_binder(plan: str, binder_count: int) -> bool:
    limit = PLANS[plan]["binders"]
    return limit is None or binder_count < limit


def can_add_pages(plan: str, binder_count: int) -> bool:
    """Over the limit after a downgrade: read-only (and still swappable), never deleted."""
    limit = PLANS[plan]["binders"]
    return limit is None or binder_count <= limit


def visible_trade_history(plan: str, history: list[TradeRecord]) -> list[TradeRecord]:
    """Newest first; free keeps the last trade. Records are kept, only hidden."""
    ordered = sorted(history, key=lambda t: t.completed_at, reverse=True)
    keep = PLANS[plan]["trade_history"]
    return ordered if keep is None else ordered[:keep]
