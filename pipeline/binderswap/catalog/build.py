"""Build the catalog: TCGdex checkout -> SQLite DB + per-set JSON packs + report.

    python -m binderswap.catalog.build --tcgdex /path/to/cards-database --out build/catalog

If ``--tcgdex`` is omitted, the pinned upstream repo is cloned into
``--work``. Requires ``bun`` (to read the TypeScript source files) and ``git``.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

from .db import write_db, write_packs
from .normalize import Catalog, build_catalog

TCGDEX_REPO = "https://github.com/tcgdex/cards-database.git"
EXPORTER = Path(__file__).with_name("tcgdex_export.ts")


def ensure_checkout(work: Path, ref: str | None) -> Path:
    dest = work / "cards-database"
    if not dest.exists():
        subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", TCGDEX_REPO, str(dest)], check=True)
    else:
        subprocess.run(["git", "-C", str(dest), "fetch", "--quiet", "origin"], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", ref or "origin/HEAD"], check=True)
    return dest


def git_commit(repo: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def export_records(tcgdex: Path, out: Path, langs: str) -> list[dict]:
    subprocess.run(["bun", "run", str(EXPORTER), str(tcgdex), str(out), langs], check=True)
    with out.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def report(cat: Catalog, meta: dict) -> str:
    by_lang = collections.Counter(c["lang"] for c in cat.cards.values())
    sets_by_lang = collections.Counter(s["lang"] for s in cat.sets.values())
    kinds = collections.Counter((i["kind"]) for i in cat.issues)
    lines = [
        "# Catalog build report", "",
        f"- Source: `tcgdex/cards-database` @ `{meta['tcgdex_commit'][:12]}`",
        f"- Built: {meta['built_at']}", "",
        "| Language | Sets | Cards | Variants |", "|---|---|---|---|",
    ]
    vcount = collections.Counter(v["card_id"].split("/")[0] for v in cat.variants)
    for lang in sorted(by_lang):
        lines.append(f"| {lang} | {sets_by_lang[lang]} | {by_lang[lang]} | {vcount[lang]} |")
    lines += ["", "## Data-quality issues (need review before publishing)", "",
              "| Kind | Count |", "|---|---|"]
    lines += [f"| {k} | {n} |" for k, n in kinds.most_common()]
    lines += ["", "### Sets with missing collector numbers", "",
              "| Set | Name | Detail |", "|---|---|---|"]
    for i in sorted((i for i in cat.issues if i["kind"] == "missing_numbers"), key=lambda i: i["ref"]):
        lines.append(f"| `{i['ref']}` | {cat.sets[i['ref']]['name']} | {i['detail']} |")
    rarity = collections.Counter(i["ref"].rsplit("/", 1)[0] for i in cat.issues if i["kind"] == "missing_rarity")
    lines += ["", "### Cards missing rarity, by set (top 25)", "", "| Set | Name | Cards |", "|---|---|---|"]
    lines += [f"| `{k}` | {cat.sets[k]['name']} | {n} |" for k, n in rarity.most_common(25)]
    other = [i for i in cat.issues if i["kind"] not in ("missing_numbers", "missing_rarity")]
    lines += ["", "### Other issues", "", "| Kind | Ref | Detail |", "|---|---|---|"]
    lines += [f"| {i['kind']} | `{i['ref']}` | {i['detail']} |" for i in other]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tcgdex", type=Path, help="existing cards-database checkout")
    ap.add_argument("--ref", help="upstream commit/branch to build from (default: latest)")
    ap.add_argument("--work", type=Path, default=Path("build/work"))
    ap.add_argument("--out", type=Path, default=Path("build/catalog"))
    ap.add_argument("--langs", default="en,ja")
    args = ap.parse_args(argv)

    args.work.mkdir(parents=True, exist_ok=True)
    tcgdex = args.tcgdex or ensure_checkout(args.work, args.ref)
    records = export_records(tcgdex, args.work / "tcgdex.ndjson", args.langs)
    cat = build_catalog(records)
    meta = {
        "source": "tcgdex/cards-database",
        "tcgdex_commit": git_commit(tcgdex),
        "built_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "langs": args.langs,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    write_db(cat, args.out / "catalog.sqlite", meta)
    write_packs(cat, args.out / "packs", meta)
    (args.out / "REPORT.md").write_text(report(cat, meta))
    print(f"{len(cat.sets)} sets, {len(cat.cards)} cards, {len(cat.variants)} variants, "
          f"{len(cat.issues)} issues -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
