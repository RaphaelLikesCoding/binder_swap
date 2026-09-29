"""Cross-check the English catalog against pokemon-tcg-data (pokemontcg.io).

Two independent community sources that agree are strong evidence a card record
is right; every disagreement becomes an ``issues`` row for human review.

    python -m binderswap.catalog.crosscheck --catalog build/catalog/catalog.sqlite \
        --ptcg /path/to/pokemon-tcg-data

pokemon-tcg-data goes offline with the legacy API on 2027-03-01, so a snapshot
of it (commit recorded in ``meta``) is the reference we keep.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path

PTCG_REPO = "https://github.com/PokemonTCG/pokemon-tcg-data.git"

# Known set splits/renames the heuristics can't infer (ours -> pokemontcg.io).
SET_OVERRIDES = {
    "en/swsh4.5": "swsh45",
    "en/swsh4.5sv": "swsh45sv",
    "en/hgssp": "hsp",
    "en/sv10.5b": "zsv10pt5",
    "en/sv10.5w": "rsv10pt5",
    "en/30th": "me55",
    "en/30th-c": "me55c",
    "en/tk-ex-latia": "tk1a",
    "en/tk-ex-latio": "tk1b",
    "en/2016xy": "mcd16",
    "en/2017sm": "mcd17",
    "en/2018sm": "mcd18",
}


def norm_set_id(set_id: str) -> str:
    """``sv03.5`` / ``sv3pt5`` -> ``sv3pt5``; ``swsh12.5gg`` -> ``swsh12pt5gg``."""
    s = set_id.lower().replace(".", "pt")
    return re.sub(r"(?<=[a-z])0+(?=\d)", "", s)


def norm_number(n: str) -> str:
    m = re.match(r"^([A-Za-z]*?)0*(\d+)([A-Za-z]*)$", n)
    return f"{m.group(1).upper()}{m.group(2)}{m.group(3).lower()}" if m else n


def norm_name(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("’", "'").replace("δ", "delta").replace("♀", "f").replace("♂", "m")
    return re.sub(r"[^a-z0-9]+", "", s)


def rarity_tier(r: str | None) -> str | None:
    """Coarse rarity tier: common / uncommon / rare (and everything above).

    The sources word rarities differently (TCGdex says "Rare" and records holo
    as a variant; pokemontcg.io says "Rare Holo"), so only tier changes are real
    disagreements. Promo is a distribution channel, not a tier: ignored.
    """
    if not r:
        return None
    r = r.strip().lower()
    if r == "promo":
        return None
    if r == "common":
        return "common"
    if r == "uncommon":
        return "uncommon"
    return "rare"


def load_ptcg(root: Path) -> tuple[dict, dict]:
    sets = {s["id"]: s for s in json.loads((root / "sets" / "en.json").read_text())}
    cards: dict[str, list[dict]] = {}
    for f in (root / "cards" / "en").glob("*.json"):
        cards[f.stem] = json.loads(f.read_text())
    return sets, cards


def map_sets(con: sqlite3.Connection, ptcg_sets: dict) -> tuple[dict[str, str], list[str], list[str]]:
    """Map catalog set ids (en/...) to ptcg set ids.

    Tries normalized id first, then (abbreviation, release date), then
    (normalized name, release date). Returns (mapping, unmatched_ours, unmatched_theirs).
    """
    by_norm = {norm_set_id(k): k for k in ptcg_sets}
    by_code_date = {((s.get("ptcgoCode") or "").lower(), s["releaseDate"].replace("/", "-")): k
                    for k, s in ptcg_sets.items() if s.get("ptcgoCode")}
    by_name_date = {(norm_name(s["name"]), s["releaseDate"].replace("/", "-")): k for k, s in ptcg_sets.items()}
    rows = con.execute("SELECT id, source_set_id, name, abbreviation, release_date FROM sets WHERE lang='en'").fetchall()
    ours_all = [r[0] for r in rows]
    mapping: dict[str, str] = {k: v for k, v in SET_OVERRIDES.items() if v in ptcg_sets and k in ours_all}
    for sid, src, name, abbr, date in rows:
        if sid in mapping:
            continue
        theirs = (by_norm.get(norm_set_id(src))
                  or by_code_date.get(((abbr or "").lower(), date))
                  or by_name_date.get((norm_name(name), date)))
        if theirs and theirs not in mapping.values():
            mapping[sid] = theirs
    unmatched_ours = sorted(s for s in ours_all if s not in mapping)
    unmatched_theirs = sorted(set(ptcg_sets) - set(mapping.values()))
    return mapping, unmatched_ours, unmatched_theirs


def crosscheck(con: sqlite3.Connection, ptcg_root: Path) -> dict:
    ptcg_sets, ptcg_cards = load_ptcg(ptcg_root)
    mapping, unmatched_ours, unmatched_theirs = map_sets(con, ptcg_sets)
    issues: list[tuple[str, str, str, str]] = []
    stats = collections.Counter()

    for ours, theirs in sorted(mapping.items()):
        our_cards = {norm_number(local): (cid, name, suffix, rarity)
                     for cid, local, name, suffix, rarity in con.execute(
                         "SELECT id, local_id, name, suffix, rarity FROM cards WHERE set_id=?", (ours,))}
        their_cards = {norm_number(c["number"]): c for c in ptcg_cards.get(theirs, [])}
        (printed,) = con.execute("SELECT printed_total FROM sets WHERE id=?", (ours,)).fetchone()
        their_printed = ptcg_sets[theirs].get("printedTotal")
        if printed and their_printed and printed != their_printed:
            issues.append(("set", ours, "xcheck_printed_total", f"ours {printed}, pokemontcg.io {their_printed}"))
        only_ours = sorted(set(our_cards) - set(their_cards), key=_num_key)
        only_theirs = sorted(set(their_cards) - set(our_cards), key=_num_key)
        if only_ours:
            issues.append(("set", ours, "xcheck_only_in_catalog", _short(only_ours)))
        if only_theirs:
            issues.append(("set", ours, "xcheck_missing_from_catalog",
                           _short([f"{n} {their_cards[n]['name']}" for n in only_theirs])))
        for num in set(our_cards) & set(their_cards):
            cid, name, suffix, rarity = our_cards[num]
            t = their_cards[num]
            stats["compared"] += 1
            # TCGdex sometimes keeps "LV.X" / "BREAK" style suffixes in a separate field.
            if norm_name(t["name"]) not in (norm_name(name), norm_name(f"{name} {suffix or ''}")):
                issues.append(("card", cid, "xcheck_name", f"ours {name!r}, pokemontcg.io {t['name']!r}"))
            elif (rarity_tier(rarity) and rarity_tier(t.get("rarity"))
                  and rarity_tier(rarity) != rarity_tier(t["rarity"])):
                issues.append(("card", cid, "xcheck_rarity", f"ours {rarity!r}, pokemontcg.io {t['rarity']!r}"))
            else:
                stats["agree"] += 1

    con.execute("DELETE FROM issues WHERE kind LIKE 'xcheck_%'")
    con.executemany("INSERT INTO issues VALUES (?,?,?,?)", issues)
    for s in unmatched_ours:
        con.execute("INSERT INTO issues VALUES ('set', ?, 'xcheck_set_unmatched', 'no pokemontcg.io set')", (s,))
    commit = _git_commit(ptcg_root)
    con.execute("INSERT OR REPLACE INTO meta VALUES ('ptcg_commit', ?)", (commit,))
    con.commit()
    return {"mapping": mapping, "unmatched_ours": unmatched_ours, "unmatched_theirs": unmatched_theirs,
            "issues": issues, "stats": stats, "ptcg_commit": commit}


def _num_key(n: str) -> tuple:
    m = re.match(r"^([A-Z]*)(\d+)(.*)$", n)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else (n, 0, "")


def _short(items: list[str], limit: int = 15) -> str:
    return f"{len(items)}: " + ", ".join(items[:limit]) + (" …" if len(items) > limit else "")


def _git_commit(repo: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def render(result: dict) -> str:
    st = result["stats"]
    kinds = collections.Counter(i[2] for i in result["issues"])
    pct = 100 * st["agree"] / st["compared"] if st["compared"] else 0
    lines = [
        "# English cross-check: TCGdex vs pokemon-tcg-data", "",
        f"- pokemon-tcg-data @ `{result['ptcg_commit'][:12]}`",
        f"- Sets matched: **{len(result['mapping'])}**; catalog-only sets: {len(result['unmatched_ours'])}; "
        f"pokemontcg.io-only sets: {len(result['unmatched_theirs'])}",
        f"- Cards compared: **{st['compared']}**, agreeing on name and rarity tier: **{st['agree']} ({pct:.1f}%)**",
        "", "| Disagreement | Count |", "|---|---|",
    ]
    lines += [f"| {k} | {n} |" for k, n in kinds.most_common()]
    for kind, title in [("xcheck_missing_from_catalog", "Cards pokemontcg.io has that the catalog lacks"),
                        ("xcheck_only_in_catalog", "Cards only in the catalog"),
                        ("xcheck_printed_total", "Printed total disagreements"),
                        ("xcheck_name", "Name disagreements (first 40)"),
                        ("xcheck_rarity", "Rarity tier disagreements (first 40)")]:
        rows = [i for i in result["issues"] if i[2] == kind][:40]
        if rows:
            lines += ["", f"## {title}", "", "| Ref | Detail |", "|---|---|"]
            lines += [f"| `{r[1]}` | {r[3]} |" for r in rows]
    lines += ["", "## Sets without a counterpart", "",
              "Catalog only: " + (", ".join(f"`{s}`" for s in result["unmatched_ours"]) or "none"), "",
              "pokemontcg.io only: " + (", ".join(f"`{s}`" for s in result["unmatched_theirs"]) or "none")]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", type=Path, default=Path("build/catalog/catalog.sqlite"))
    ap.add_argument("--ptcg", type=Path, help="pokemon-tcg-data checkout (cloned into build/work if omitted)")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(argv)
    ptcg = args.ptcg
    if ptcg is None:
        ptcg = Path("build/work/pokemon-tcg-data")
        if not ptcg.exists():
            subprocess.run(["git", "clone", "--quiet", "--depth", "1", PTCG_REPO, str(ptcg)], check=True)
    con = sqlite3.connect(args.catalog)
    result = crosscheck(con, ptcg)
    out = args.report or args.catalog.with_name("CROSSCHECK.md")
    out.write_text(render(result))
    st = result["stats"]
    print(f"{len(result['mapping'])} sets matched, {st['agree']}/{st['compared']} cards agree -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
