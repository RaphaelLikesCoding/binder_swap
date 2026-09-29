"""SQLite catalog database: schema, writer and per-set JSON packs for the app."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .normalize import Catalog

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE sets (
    id TEXT PRIMARY KEY,              -- {lang}/{source_set_id}
    lang TEXT NOT NULL,
    source_set_id TEXT NOT NULL,
    serie_id TEXT NOT NULL,
    serie_name TEXT,
    name TEXT,
    name_en TEXT,
    printed_total INTEGER,            -- number printed after the slash (045/198)
    card_count INTEGER NOT NULL,      -- cards present in the catalog, incl. secrets
    number_prefix TEXT NOT NULL DEFAULT '',  -- main numbering prefix ('' | 'SM' | 'TG' ...)
    release_date TEXT,
    abbreviation TEXT,
    tcgplayer_group_id INTEGER,
    cardmarket_id INTEGER
);

CREATE TABLE cards (
    id TEXT PRIMARY KEY,              -- {lang}/{source_set_id}/{local_id}
    lang TEXT NOT NULL,
    set_id TEXT NOT NULL REFERENCES sets(id),
    local_id TEXT NOT NULL,
    number_prefix TEXT NOT NULL DEFAULT '',
    number INTEGER,
    number_suffix TEXT NOT NULL DEFAULT '',
    name TEXT,
    name_en TEXT,
    rarity TEXT,
    category TEXT,
    hp INTEGER,
    types TEXT NOT NULL,              -- JSON array
    stage TEXT,
    suffix TEXT,
    illustrator TEXT,
    regulation_mark TEXT,
    dex_ids TEXT NOT NULL,            -- JSON array
    image_base TEXT NOT NULL,         -- append /high.png or /low.webp
    source_path TEXT NOT NULL
);
CREATE INDEX cards_set ON cards(set_id, number);
CREATE INDEX cards_name ON cards(name);

CREATE TABLE variants (
    card_id TEXT NOT NULL REFERENCES cards(id),
    variant_key TEXT NOT NULL,
    type TEXT NOT NULL,               -- normal | holo | reverse | metal | lenticular
    subtype TEXT,
    stamps TEXT NOT NULL,             -- JSON array
    foil TEXT,
    size TEXT NOT NULL,
    tcgplayer_id INTEGER,
    cardmarket_id INTEGER,
    alt_ids TEXT,                     -- JSON array of extra marketplace ids
    PRIMARY KEY (card_id, variant_key)
);

-- Stable IDs survive upstream renames: old id -> current id.
CREATE TABLE card_aliases (alias TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(id));

-- Data-quality findings that need a human decision before a set is published.
CREATE TABLE issues (
    scope TEXT NOT NULL,              -- set | card
    ref TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE INDEX issues_ref ON issues(ref);
"""


def write_db(cat: Catalog, path: Path, meta: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        con.executemany("INSERT INTO meta VALUES (?, ?)",
                        [("schema_version", str(SCHEMA_VERSION)), *sorted(meta.items())])
        con.executemany(
            "INSERT INTO sets VALUES (:id,:lang,:source_set_id,:serie_id,:serie_name,:name,:name_en,"
            ":printed_total,:card_count,:number_prefix,:release_date,:abbreviation,:tcgplayer_group_id,:cardmarket_id)",
            cat.sets.values())
        con.executemany(
            "INSERT INTO cards VALUES (:id,:lang,:set_id,:local_id,:number_prefix,:number,:number_suffix,"
            ":name,:name_en,:rarity,:category,:hp,:types,:stage,:suffix,:illustrator,:regulation_mark,"
            ":dex_ids,:image_base,:source_path)",
            ({**c, "types": json.dumps(c["types"]), "dex_ids": json.dumps(c["dex_ids"])}
             for c in cat.cards.values()))
        con.executemany(
            "INSERT INTO variants VALUES (:card_id,:variant_key,:type,:subtype,:stamps,:foil,:size,"
            ":tcgplayer_id,:cardmarket_id,:alt_ids)",
            ({**v, "stamps": json.dumps(v["stamps"]),
              "alt_ids": json.dumps(v["alt_ids"]) if v.get("alt_ids") else None}
             for v in cat.variants))
        con.executemany("INSERT INTO issues VALUES (:scope,:ref,:kind,:detail)", cat.issues)
        con.commit()
    finally:
        con.close()


def _sort_key(c: dict) -> tuple:
    return (c["number_prefix"], c["number"] if c["number"] is not None else 1 << 30,
            c["number_suffix"], c["local_id"])


def write_packs(cat: Catalog, out_dir: Path, meta: dict[str, str]) -> dict:
    """Write one JSON pack per set plus an index the app uses to fetch updates.

    Each pack's sha256 is in the index, so the app downloads only sets whose
    content changed (new sets, corrections).
    """
    variants_by_card: dict[str, list[dict]] = {}
    for v in cat.variants:
        variants_by_card.setdefault(v["card_id"], []).append(
            {k: v[k] for k in ("variant_key", "type", "stamps", "foil", "size", "tcgplayer_id")
             if v.get(k) not in (None, [])})
    cards_by_set: dict[str, list[dict]] = {}
    for c in cat.cards.values():
        cards_by_set.setdefault(c["set_id"], []).append(c)

    index = {"schema_version": SCHEMA_VERSION, **meta, "sets": []}
    for skey in sorted(cat.sets):
        s = cat.sets[skey]
        cards = sorted(cards_by_set.get(skey, []), key=_sort_key)
        pack = {
            "set": s,
            "cards": [{
                "id": c["id"], "local_id": c["local_id"], "number": c["number"],
                "name": c["name"], "rarity": c["rarity"], "category": c["category"],
                "image_base": c["image_base"], "variants": variants_by_card.get(c["id"], []),
            } for c in cards],
        }
        body = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        rel = Path(s["lang"]) / f"{s['source_set_id']}.json"
        (out_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / rel).write_bytes(body)
        index["sets"].append({
            "id": skey, "name": s["name"], "release_date": s["release_date"],
            "card_count": s["card_count"], "path": str(rel),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    return index
