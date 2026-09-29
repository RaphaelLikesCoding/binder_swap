"""Normalize raw TCGdex export records into Binder Swap catalog rows.

Input: one dict per (card, language) as written by ``tcgdex_export.ts``.
Output: plain dicts for the ``sets``, ``cards`` and ``variants`` tables.

Our IDs are ``{lang}/{set_id}/{local_id}`` (e.g. ``en/sv03/125``). They are
stable as long as the upstream set id and local id are; if upstream ever
renames, the catalog keeps an alias so existing collections never break.
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

ASSET_BASE = "https://assets.tcgdex.net"

# Language fallbacks for display names when a field is missing in the target
# language. Japanese sets in TCGdex sometimes only carry an English serie name.
_FALLBACK = {"en": ["en"], "ja": ["ja", "en"]}

_NUMBER_RE = re.compile(r"^(?P<prefix>[A-Za-z-]*?)(?P<num>\d+)(?P<suffix>[A-Za-z]*)$")


def card_id(lang: str, set_id: str, local_id: str) -> str:
    return f"{lang}/{set_id}/{local_id}"


def set_key(lang: str, set_id: str) -> str:
    return f"{lang}/{set_id}"


def localized(value: Any, lang: str) -> str | None:
    """Resolve a TCGdex ``Languages`` dict (or plain string) for ``lang``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    for code in _FALLBACK.get(lang, [lang]):
        if value.get(code):
            return value[code]
    return None


def parse_number(local_id: str) -> tuple[str, int | None, str]:
    """Split a collector number like ``TG05`` or ``125`` or ``SWSH001``.

    Returns ``(prefix, number, suffix)``; ``number`` is None when the id has no
    digits (e.g. ``?`` or ``!`` Unown cards).
    """
    m = _NUMBER_RE.match(local_id)
    if not m:
        return local_id, None, ""
    return m.group("prefix"), int(m.group("num")), m.group("suffix")


def _variant_key(v: dict) -> str:
    """Deterministic, human-readable variant identifier.

    ``holo``, ``reverse``, ``normal+1st-edition``, ``holo/shadowless+1st-edition``,
    ``reverse@pokeball``, ``holo#jumbo``.
    """
    key = v["type"]
    if v.get("subtype"):
        key += "/" + v["subtype"]
    for stamp in sorted(v.get("stamps") or []):
        key += "+" + stamp
    if v.get("foil"):
        key += "@" + v["foil"]
    if v.get("size") and v["size"] != "standard":
        key += "#" + v["size"]
    return key


def normalize_variants(raw: Any, lang: str) -> list[dict]:
    """Expand both TCGdex variant formats into a flat list.

    TCGdex has a legacy boolean object (``{normal, reverse, holo, firstEdition}``)
    and a newer detailed list. We mirror the upstream compiler's expansion of the
    legacy form so both produce the same shape.
    """
    variants: list[dict] = []
    if isinstance(raw, list):
        for v in raw:
            langs = v.get("languages")
            if langs and lang not in langs:
                continue
            tp = v.get("thirdParty") or {}
            variants.append({
                "type": v["type"],
                "subtype": v.get("subtype"),
                "stamps": list(v.get("stamp") or []),
                "foil": v.get("foil"),
                "size": v.get("size") or "standard",
                "tcgplayer_id": tp.get("tcgplayer"),
                "cardmarket_id": tp.get("cardmarket"),
            })
    else:
        raw = raw or {}
        first_ed = bool(raw.get("firstEdition"))

        def add(t: str, stamps: list[str] | None = None) -> None:
            variants.append({
                "type": t, "subtype": None, "stamps": stamps or [], "foil": None,
                "size": "standard", "tcgplayer_id": None, "cardmarket_id": None,
            })

        if raw.get("normal", True):
            add("normal")
            if first_ed:
                add("normal", ["1st-edition"])
            if raw.get("wPromo"):
                add("normal", ["w-promo"])
        if raw.get("reverse"):
            add("reverse")
            if first_ed:
                add("reverse", ["1st-edition"])
        if raw.get("holo"):
            add("holo")
            if first_ed:
                add("holo", ["1st-edition"])

    # Upstream occasionally lists the same variant twice (e.g. several prize-pack
    # printings with different marketplace ids). Keep the first; record the rest
    # as alternate marketplace ids so nothing is lost.
    seen: dict[str, dict] = {}
    for v in variants:
        v["variant_key"] = _variant_key(v)
        if v["variant_key"] in seen:
            seen[v["variant_key"]].setdefault("alt_ids", []).append(
                {"tcgplayer_id": v["tcgplayer_id"], "cardmarket_id": v["cardmarket_id"]})
        else:
            seen[v["variant_key"]] = v
    return list(seen.values())


def _release_date(value: Any, lang: str) -> str | None:
    if isinstance(value, dict):
        return value.get(lang) or next(iter(value.values()), None)
    return value


@dataclass
class Catalog:
    sets: dict[str, dict] = field(default_factory=dict)
    cards: dict[str, dict] = field(default_factory=dict)
    variants: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)

    def issue(self, scope: str, ref: str, kind: str, detail: str) -> None:
        self.issues.append({"scope": scope, "ref": ref, "kind": kind, "detail": detail})


def build_catalog(records: Iterable[dict]) -> Catalog:
    cat = Catalog()
    for r in records:
        lang, raw_set, raw_card, serie = r["lang"], r["set"], r["card"], r["serie"]
        skey = set_key(lang, raw_set["id"])
        if skey not in cat.sets:
            tp = raw_set.get("thirdParty") or {}
            abbr = raw_set.get("abbreviations") or {}
            cat.sets[skey] = {
                "id": skey,
                "lang": lang,
                "source_set_id": raw_set["id"],
                "serie_id": serie["id"],
                "serie_name": localized(serie.get("name"), lang),
                "name": localized(raw_set.get("name"), lang),
                "name_en": localized(raw_set.get("name"), "en"),
                "printed_total": (raw_set.get("cardCount") or {}).get("official") or None,
                "number_prefix": "",
                "release_date": _release_date(raw_set.get("releaseDate"), lang),
                "abbreviation": abbr.get("official") or raw_set.get("tcgOnline"),
                "tcgplayer_group_id": tp.get("tcgplayer"),
                "cardmarket_id": tp.get("cardmarket"),
            }
            if not cat.sets[skey]["name"]:
                cat.issue("set", skey, "missing_name", f"no {lang} or fallback name")

        local_id = r["localId"]
        cid = card_id(lang, raw_set["id"], local_id)
        if cid in cat.cards:
            cat.issue("card", cid, "duplicate", r["source"]["path"])
            continue
        prefix, number, suffix = parse_number(local_id)
        name = localized(raw_card.get("name"), lang)
        # LV.X cards print "LV.X" as part of the name; TCGdex encodes it as a stage.
        if name and raw_card.get("stage") == "LEVEL-UP" and "LV.X" not in name:
            name = f"{name} LV.X"
        rarity = raw_card.get("rarity")
        variants = normalize_variants(raw_card.get("variants"), lang)
        cat.cards[cid] = {
            "id": cid,
            "lang": lang,
            "set_id": skey,
            "local_id": local_id,
            "number_prefix": prefix,
            "number": number,
            "number_suffix": suffix,
            "name": name,
            "name_en": localized(raw_card.get("name"), "en"),
            "rarity": rarity if rarity and rarity != "None" else None,
            "category": raw_card.get("category"),
            "hp": raw_card.get("hp"),
            "types": raw_card.get("types") or [],
            "stage": raw_card.get("stage"),
            "suffix": raw_card.get("suffix"),
            "illustrator": raw_card.get("illustrator"),
            "regulation_mark": raw_card.get("regulationMark"),
            "dex_ids": raw_card.get("dexId") or [],
            "image_base": f"{ASSET_BASE}/{lang}/{serie['id']}/{raw_set['id']}/{local_id}",
            "source_path": r["source"]["path"],
        }
        for v in variants:
            cat.variants.append({"card_id": cid, **v})
        if not variants:
            cat.issue("card", cid, "no_variants", "no printable variant for this language")
        if rarity in (None, "None"):
            cat.issue("card", cid, "missing_rarity", "")
    _check_sets(cat)
    return cat


def _check_sets(cat: Catalog) -> None:
    """Completeness checks: every number 1..printed_total should exist."""
    by_set: dict[str, list[dict]] = {}
    for c in cat.cards.values():
        by_set.setdefault(c["set_id"], []).append(c)
    for skey, s in cat.sets.items():
        cards = by_set.get(skey, [])
        s["card_count"] = len(cards)
        total = s["printed_total"]
        if not total:
            cat.issue("set", skey, "missing_printed_total", f"{len(cards)} cards present")
            continue
        # Main-set numbering uses the set's dominant prefix: '' for 045/198,
        # 'SM' for SM Black Star Promos, 'TG' for Trainer Gallery subsets.
        prefixes = collections.Counter(c["number_prefix"] for c in cards if c["number"] is not None)
        main_prefix = prefixes.most_common(1)[0][0] if prefixes else ""
        s["number_prefix"] = main_prefix
        numbered = {c["number"] for c in cards
                    if c["number"] is not None and c["number_prefix"] == main_prefix}
        missing = sorted(set(range(1, total + 1)) - numbered)
        if missing:
            shown = ", ".join(map(str, missing[:20])) + (" …" if len(missing) > 20 else "")
            cat.issue("set", skey, "missing_numbers", f"{len(missing)}/{total} missing: {shown}")
