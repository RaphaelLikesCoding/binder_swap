"""Run the shared JSON test vectors (spec/vectors) against the Python reference rules.

The iOS app runs the same files against its Swift implementation.
"""

import json
from pathlib import Path

import pytest

from binderswap.domain.core import (Binder, CatalogSet, Collection, Item, Match, Offer, TradeRecord, Wish,
                                    apply_trade, can_add_binder, can_add_pages, match, suggest_fair_trade,
                                    tradeables, visible_trade_history, wishlist)

VECTORS = Path(__file__).resolve().parents[2] / "spec" / "vectors"


def load(name):
    return json.loads((VECTORS / name).read_text())


def cases(name):
    return [pytest.param(c, id=c["name"]) for c in load(name)["cases"]]


def item(d):
    return None if d is None else Item(**d)


def collection(d):
    binders = [Binder(**{**b, "pages": [[item(s) for s in page] for page in b["pages"]]})
               for b in d.get("binders", [])]
    return Collection(binders, [item(i) for i in d.get("loose", [])],
                      [Wish(**w) for w in d.get("manual_wishes", [])])


def sets(d):
    return {k: CatalogSet(k, v["printed_total"], [tuple(c) for c in v["cards"]]) for k, v in d.items()}


@pytest.mark.parametrize("case", cases("tradeables.json"))
def test_tradeables(case):
    got = tradeables(collection(case["collection"]), sets(load("tradeables.json")["sets"]))
    assert sorted(i.card_id for i in got) == case["expected"]


@pytest.mark.parametrize("case", cases("wishlist.json"))
def test_wishlist(case):
    wishes = wishlist(collection(case["collection"]), sets(load("wishlist.json")["sets"]))
    assert sorted([w.card_id, w.priority, w.source] for w in wishes) == case["expected"]
    for cid, where in case.get("expected_owned_elsewhere", {}).items():
        assert list(next(w for w in wishes if w.card_id == cid).owned_elsewhere) == where


@pytest.mark.parametrize("case", cases("match.json"))
def test_match(case):
    def norm(profile):
        return {"tradeables": [{"variant": "normal", "condition": "NM", "keep": False, **t}
                               for t in profile["tradeables"]],
                "wants": profile["wants"]}
    m = match(norm(case["mine"]), norm(case["theirs"]), case["prices"])
    assert [[o.item.card_id, o.item.variant, o.priority] for o in m.for_me] == case["expected_for_me"]
    assert [[o.item.card_id, o.item.variant, o.priority] for o in m.for_them] == case["expected_for_them"]
    assert len(m.near_misses) == case["expected_near_misses"]


@pytest.mark.parametrize("case", cases("fair_trade.json"))
def test_fair_trade(case):
    side = lambda rows: [Offer(Item(cid), prio, val) for cid, prio, val in rows]  # noqa: E731
    get, give = suggest_fair_trade(Match(side(case["for_me"]), side(case["for_them"]), []))
    assert [o.item.card_id for o in get] == case["expected_get"]
    assert [o.item.card_id for o in give] == case["expected_give"]


@pytest.mark.parametrize("case", cases("apply_trade.json"))
def test_apply_trade(case):
    col = collection(case["collection"])
    gave, got = [Item(**i) for i in case["gave"]], [Item(**i) for i in case["got"]]
    if case.get("expected_error"):
        with pytest.raises(ValueError):
            apply_trade(col, gave, got)
        return
    after = apply_trade(col, gave, got)
    for bid, pages in case["expected_pages"].items():
        b = next(b for b in after.binders if b.id == bid)
        assert b.pages == [[item(s) for s in p] for p in pages]
    assert after.loose == [Item(**i) for i in case["expected_loose"]]
    # The input collection is not mutated.
    assert col.binders[0].pages != after.binders[0].pages


def test_plans():
    v = load("plans.json")
    for c in v["binder_limits"]:
        assert can_add_binder(c["plan"], c["binders"]) == c["can_add"], c
    for c in v["downgrade"]:
        assert can_add_pages(c["plan"], c["binders"]) == c["can_add_pages"], c
    for c in v["trade_history"]:
        recs = [TradeRecord(d, d, "peer", [], []) for d in c["records"]]
        assert [r.completed_at for r in visible_trade_history(c["plan"], recs)] == c["visible"], c
