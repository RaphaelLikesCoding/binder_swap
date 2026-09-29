import json
import sqlite3

from binderswap.catalog.db import write_db, write_packs
from binderswap.catalog.normalize import build_catalog, normalize_variants, parse_number


def rec(lang="en", set_id="sv03", local_id="125", name=None, total=3, variants=None, rarity="Rare"):
    return {
        "source": {"repo": "tcgdex/cards-database", "path": f"data/x/{set_id}/{local_id}.ts"},
        "lang": lang,
        "localId": local_id,
        "serie": {"id": "sv", "name": {"en": "Scarlet & Violet"}},
        "set": {"id": set_id, "name": {"en": "Obsidian Flames", "ja": "黒炎の支配者"},
                "cardCount": {"official": total}, "releaseDate": "2023-08-11",
                "abbreviations": {"official": "OBF"}, "thirdParty": {"tcgplayer": 23228}},
        "card": {"name": name or {"en": f"Card {local_id}", "ja": f"カード{local_id}"},
                 "rarity": rarity, "category": "Pokemon", "variants": variants},
    }


def test_parse_number():
    assert parse_number("125") == ("", 125, "")
    assert parse_number("TG05") == ("TG", 5, "")
    assert parse_number("SWSH001") == ("SWSH", 1, "")
    assert parse_number("15a") == ("", 15, "a")
    assert parse_number("?") == ("?", None, "")


def test_legacy_variants_expand_like_upstream():
    vs = normalize_variants({"holo": True, "reverse": True, "normal": False, "firstEdition": True}, "en")
    assert [v["variant_key"] for v in vs] == ["reverse", "reverse+1st-edition", "holo", "holo+1st-edition"]
    # Missing variants object means a plain normal card.
    assert [v["variant_key"] for v in normalize_variants(None, "en")] == ["normal"]


def test_detailed_variants_filter_language_and_dedupe():
    raw = [
        {"type": "holo", "thirdParty": {"tcgplayer": 1}},
        {"type": "holo", "thirdParty": {"tcgplayer": 2}},
        {"type": "reverse", "foil": "pokeball", "languages": ["ja"]},
        {"type": "holo", "size": "jumbo"},
    ]
    en = normalize_variants(raw, "en")
    assert [v["variant_key"] for v in en] == ["holo", "holo#jumbo"]
    assert en[0]["tcgplayer_id"] == 1 and en[0]["alt_ids"] == [{"tcgplayer_id": 2, "cardmarket_id": None}]
    assert [v["variant_key"] for v in normalize_variants(raw, "ja")][1] == "reverse@pokeball"


def test_build_catalog_ids_and_completeness():
    cat = build_catalog([rec(local_id="1"), rec(local_id="3"), rec(local_id="4"), rec(lang="ja", local_id="1")])
    assert set(cat.cards) == {"en/sv03/1", "en/sv03/3", "en/sv03/4", "ja/sv03/1"}
    assert cat.sets["ja/sv03"]["name"] == "黒炎の支配者"
    assert cat.cards["ja/sv03/1"]["name"] == "カード1"
    # 4 is a secret rare above the printed total: allowed. 2 is a real gap.
    gaps = {i["ref"]: i["detail"] for i in cat.issues if i["kind"] == "missing_numbers"}
    assert gaps == {"en/sv03": "1/3 missing: 2", "ja/sv03": "2/3 missing: 2, 3"}
    assert cat.sets["en/sv03"]["card_count"] == 3


def test_prefixed_promo_numbering_is_not_a_gap():
    cat = build_catalog([rec(set_id="smp", local_id=f"SM0{i}", total=3) for i in (1, 2, 3)])
    assert not [i for i in cat.issues if i["kind"] == "missing_numbers"]
    assert cat.sets["en/smp"]["number_prefix"] == "SM"


def test_duplicate_and_missing_rarity_are_reported():
    cat = build_catalog([rec(local_id="1"), rec(local_id="1"), rec(local_id="2", rarity="None")])
    kinds = sorted(i["kind"] for i in cat.issues)
    assert "duplicate" in kinds and "missing_rarity" in kinds
    assert cat.cards["en/sv03/2"]["rarity"] is None


def test_db_and_packs_roundtrip(tmp_path):
    cat = build_catalog([rec(local_id=str(i)) for i in (1, 2, 3)])
    meta = {"tcgdex_commit": "abc", "built_at": "now"}
    write_db(cat, tmp_path / "c.sqlite", meta)
    con = sqlite3.connect(tmp_path / "c.sqlite")
    assert con.execute("select count(*) from cards").fetchone() == (3,)
    assert con.execute("select value from meta where key='tcgdex_commit'").fetchone() == ("abc",)
    index = write_packs(cat, tmp_path / "packs", meta)
    assert index["sets"][0]["path"] == "en/sv03.json"
    pack = json.loads((tmp_path / "packs" / "en" / "sv03.json").read_text())
    assert [c["local_id"] for c in pack["cards"]] == ["1", "2", "3"]
    # Packs are deterministic, so unchanged sets keep their hash.
    again = write_packs(cat, tmp_path / "packs2", meta)
    assert again["sets"][0]["sha256"] == index["sets"][0]["sha256"]


def test_level_up_cards_get_printed_lv_x_name():
    r = rec(local_id="1", total=1)
    r["card"]["stage"] = "LEVEL-UP"
    cat = build_catalog([r])
    assert cat.cards["en/sv03/1"]["name"] == "Card 1 LV.X"
