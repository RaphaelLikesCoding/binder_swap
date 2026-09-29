"""Price cache: flattening, freshness and the variant-naming trap."""

import sqlite3
import time
from pathlib import Path

from binderswap.prices import fetch


# A real TCGdex pricing block (en/bw1/1, fetched 2026-09-29), trimmed.
PRICING = {
    "tcgplayer": {
        "unit": "USD", "updated": "2026-09-28T22:54:49.641Z",
        "normal": {"lowPrice": 0.13, "midPrice": 0.33, "marketPrice": 0.37},
        "reverse-holofoil": {"lowPrice": 1.82, "midPrice": 15, "marketPrice": 2.22},
    },
    "cardmarket": {
        "unit": "EUR", "updated": "2026-09-28T22:54:33.281Z",
        "avg": 0.17, "low": 0.02, "trend": 0.15, "avg7": 0.22,
        "avg-holo": 1.62, "low-holo": 0.15, "avg7-holo": 2.08,
    },
}


def test_flattens_both_vendors_to_the_values_they_publish():
    rows = {(v, src): (usd, eur)
            for _, v, usd, eur, src, _, _ in fetch.rows_from_pricing("en/bw1/1", PRICING, "now")}
    assert rows[("normal", "tcgplayer")] == (0.37, None)
    assert rows[("reverse-holofoil", "tcgplayer")] == (2.22, None)
    assert rows[("normal", "cardmarket")] == (None, 0.22)


def test_cardmarket_foil_is_not_filed_under_a_tcgplayer_variant_name():
    """Cardmarket publishes one "-holo" series without saying which foil it is.

    Filing it as "holofoil" would let a caller join it to a TCGplayer holofoil
    price that may be a different physical card -- bw1/1 has no holofoil at all,
    only reverse-holofoil.
    """
    variants = {v for _, v, _, _, src, _, _ in
                fetch.rows_from_pricing("en/bw1/1", PRICING, "now") if src == "cardmarket"}
    assert "any-foil" in variants
    assert "holofoil" not in variants and "reverse-holofoil" not in variants


def test_a_card_with_no_pricing_yields_no_rows():
    assert fetch.rows_from_pricing("en/x/1", {}, "now") == []
    assert fetch.rows_from_pricing("en/x/1", {"tcgplayer": {"unit": "USD"}}, "now") == []


def test_plan_skips_cards_priced_recently_and_returns_stale_ones(tmp_path):
    cat = tmp_path / "catalog.sqlite"
    con = sqlite3.connect(cat)
    con.executescript("""CREATE TABLE sets(id TEXT PRIMARY KEY, source_set_id TEXT);
                         CREATE TABLE cards(id TEXT PRIMARY KEY, lang TEXT, set_id TEXT, local_id TEXT);""")
    con.execute("INSERT INTO sets VALUES ('en/bw1','bw1')")
    for n in (1, 2, 3):
        con.execute("INSERT INTO cards VALUES (?,?,?,?)", (f"en/bw1/{n}", "en", "en/bw1", str(n)))
    con.commit(); con.close()

    db = sqlite3.connect(tmp_path / "prices.sqlite")
    db.executescript(fetch.SCHEMA)
    assert len(fetch.plan(cat, db, ["en"], 20.0)) == 3

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 48 * 3600))
    db.execute("INSERT INTO fetch_log VALUES ('en/bw1/1','ok',200,?)", (now,))
    db.execute("INSERT INTO fetch_log VALUES ('en/bw1/2','ok',200,?)", (old,))   # stale
    db.execute("INSERT INTO fetch_log VALUES ('en/bw1/3','error',NULL,?)", (now,))  # retry errors
    db.commit()
    ids = {j.card_id for j in fetch.plan(cat, db, ["en"], 20.0)}
    assert ids == {"en/bw1/2", "en/bw1/3"}, "fresh card refetched, or stale/errored one skipped"
