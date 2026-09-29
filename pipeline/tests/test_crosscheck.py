import json
import sqlite3

from binderswap.catalog.crosscheck import crosscheck, norm_number, norm_set_id, rarity_tier
from binderswap.catalog.db import write_db
from binderswap.catalog.normalize import build_catalog

from test_catalog import rec


def test_normalizers():
    assert norm_set_id("sv03.5") == "sv3pt5" == norm_set_id("sv3pt5")
    assert norm_set_id("swsh12.5") == "swsh12pt5"
    assert norm_number("001") == "1" and norm_number("TG05") == "TG5" and norm_number("15A") == "15a"
    assert rarity_tier("Rare Holo EX") == rarity_tier("Rare") == "rare"
    assert rarity_tier("Promo") is None


def _ptcg(tmp_path, cards):
    (tmp_path / "sets").mkdir(parents=True)
    (tmp_path / "cards" / "en").mkdir(parents=True)
    (tmp_path / "sets" / "en.json").write_text(json.dumps([{
        "id": "sv3", "name": "Obsidian Flames", "printedTotal": 3, "ptcgoCode": "OBF", "releaseDate": "2023/08/11"}]))
    (tmp_path / "cards" / "en" / "sv3.json").write_text(json.dumps(cards))
    return tmp_path


def test_crosscheck_finds_each_disagreement_kind(tmp_path):
    cat = build_catalog([rec(local_id="1"), rec(local_id="2"), rec(local_id="3", rarity="Common"),
                         rec(local_id="4")])
    write_db(cat, tmp_path / "c.sqlite", {})
    ptcg = _ptcg(tmp_path / "ptcg", [
        {"number": "1", "name": "Card 1", "rarity": "Rare Holo"},       # agrees (wording differs)
        {"number": "2", "name": "Different", "rarity": "Rare"},         # name
        {"number": "3", "name": "Card 3", "rarity": "Rare"},            # rarity tier
        {"number": "5", "name": "Card 5", "rarity": "Rare"},            # missing from catalog
    ])
    con = sqlite3.connect(tmp_path / "c.sqlite")
    result = crosscheck(con, ptcg)
    assert result["mapping"] == {"en/sv03": "sv3"}
    kinds = {(i[2], i[1]) for i in result["issues"]}
    assert ("xcheck_name", "en/sv03/2") in kinds
    assert ("xcheck_rarity", "en/sv03/3") in kinds
    assert ("xcheck_missing_from_catalog", "en/sv03") in kinds
    assert ("xcheck_only_in_catalog", "en/sv03") in kinds  # our #4
    assert result["stats"]["agree"] == 1
    # Issues are persisted for the review queue, and a rerun replaces them.
    crosscheck(con, ptcg)
    (n,) = con.execute("SELECT count(*) FROM issues WHERE kind='xcheck_name'").fetchone()
    assert n == 1
