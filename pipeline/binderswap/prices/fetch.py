"""Cache card prices from TCGdex, resumably, with a coverage report.

    python -m binderswap.prices.fetch --catalog build/catalog/catalog.sqlite \
        --out build/prices/prices.sqlite [--langs en,ja] [--max-age-hours 20]

Devices never call price vendors (SPEC 8.3): this builds the server-side cache
they read. A row is refetched only when it is missing or older than
``--max-age-hours``, so a daily job re-reads only what has gone stale.

Currency is not a preference. Measured over 440 sampled cards, TCGplayer
carries prices for 89.5% of English cards and **none at all** for Japanese,
while Cardmarket covers 93.6% English and 80.0% Japanese. EUR is therefore the
only figure that can price both catalogues, and USD is stored alongside it for
English rather than instead of it.

Prices are an estimate with a source and a date, never a guaranteed price, and
a card with no price says so rather than guessing.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

USER_AGENT = "BinderSwapCatalog/0.1 (+https://github.com/RaphaelLikesCoding/binder_swap)"
API = "https://api.tcgdex.net/v2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    card_id TEXT NOT NULL,
    variant TEXT NOT NULL,            -- normal | holofoil | reverse-holofoil | ...
    usd REAL,                         -- TCGplayer market, English only in practice
    eur REAL,                         -- Cardmarket, the only source covering JA
    source TEXT NOT NULL,             -- tcgplayer | cardmarket
    vendor_updated TEXT,              -- as reported by the vendor
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (card_id, variant, source)
);
CREATE TABLE IF NOT EXISTS fetch_log (
    card_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,             -- ok | nodata | error
    http_status INTEGER,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS prices_card ON prices(card_id);
"""

# Vendor fields to read a market value from, best first.
TCG_KEYS = ("marketPrice", "midPrice", "directLowPrice", "lowPrice")
CM_KEYS = ("avg7", "trend", "avg", "avg30", "low")


@dataclass
class Job:
    card_id: str
    url: str


class RateLimiter:
    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second if per_second > 0 else 0.0
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self) -> None:
        if not self.interval:
            return
        with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_at - now)
            self.next_at = max(now, self.next_at) + self.interval
        if delay:
            time.sleep(delay)


def _pick(d: dict, keys) -> float | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def rows_from_pricing(card_id: str, pricing: dict, now: str) -> list[tuple]:
    """Flatten TCGdex's pricing block into (card, variant, usd, eur, source, ...)."""
    out: list[tuple] = []
    tp = pricing.get("tcgplayer") or {}
    tp_updated = tp.get("updated")
    for variant, block in tp.items():
        if not isinstance(block, dict):
            continue
        usd = _pick(block, TCG_KEYS)
        if usd is not None:
            out.append((card_id, variant, usd, None, "tcgplayer", tp_updated, now))
    cm = pricing.get("cardmarket") or {}
    if isinstance(cm, dict):
        cm_updated = cm.get("updated")
        # Cardmarket is flat, with -holo suffixes rather than nested blocks.
        base = _pick(cm, CM_KEYS)
        if base is not None:
            out.append((card_id, "normal", None, base, "cardmarket", cm_updated, now))
        # Cardmarket offers one "-holo" series and does not say whether that is
        # holo or reverse-holo; TCGplayer names the two separately and a given
        # card often has only one of them (bw1-1 is normal + reverse-holofoil,
        # priced 0.37 and 2.22 USD, while Cardmarket gives 0.22 and 2.08 EUR
        # with no way to tell which foil it means). Stored under its own name so
        # a caller cannot silently join it to the wrong TCGplayer variant.
        holo = _pick({k[:-5]: v for k, v in cm.items() if k.endswith("-holo")}, CM_KEYS)
        if holo is not None:
            out.append((card_id, "any-foil", None, holo, "cardmarket", cm_updated, now))
    return out


def plan(catalog: Path, db: sqlite3.Connection, langs: list[str], max_age_hours: float,
         limit: int | None = None) -> list[Job]:
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                           time.gmtime(time.time() - max_age_hours * 3600))
    fresh = {r[0] for r in db.execute(
        "SELECT card_id FROM fetch_log WHERE fetched_at >= ? AND status != 'error'", (cutoff,))}
    con = sqlite3.connect(catalog)
    q = ("SELECT c.id, c.lang, s.source_set_id, c.local_id FROM cards c "
         "JOIN sets s ON s.id = c.set_id WHERE c.lang IN (%s) ORDER BY c.id"
         % ",".join("?" * len(langs)))
    jobs = []
    for cid, lang, src_set, local in con.execute(q, langs):
        if cid in fresh:
            continue
        jobs.append(Job(cid, f"{API}/{lang}/cards/{src_set}-{local}"))
        if limit and len(jobs) >= limit:
            break
    con.close()
    return jobs


def fetch_one(job: Job, limiter: RateLimiter, timeout: float, retries: int) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for attempt in range(retries + 1):
        limiter.wait()
        try:
            req = urllib.request.Request(job.url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                card = json.loads(resp.read())
            pricing = card.get("pricing") or {}
            rows = rows_from_pricing(job.card_id, pricing, now)
            return {"status": "ok" if rows else "nodata", "http_status": 200,
                    "rows": rows, "fetched_at": now}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"status": "nodata", "http_status": 404, "rows": [], "fetched_at": now}
        except Exception:
            pass
        if attempt < retries:
            time.sleep(0.5 * (attempt + 1))
    return {"status": "error", "http_status": None, "rows": [], "fetched_at": now}


def run(catalog: Path, out: Path, langs: list[str] | None = None, rate: float = 8.0,
        workers: int = 6, max_age_hours: float = 20.0, limit: int | None = None,
        progress: bool = True) -> dict:
    langs = langs or ["en", "ja"]
    out.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(out, check_same_thread=False)
    db.executescript(SCHEMA)
    jobs = plan(catalog, db, langs, max_age_hours, limit)
    counts = {"ok": 0, "nodata": 0, "error": 0}
    if not jobs:
        return counts
    limiter = RateLimiter(rate)
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_one, j, limiter, 20.0, 2): j for j in jobs}
        for n, fut in enumerate(cf.as_completed(futures), 1):
            job = futures[fut]
            res = fut.result()
            counts[res["status"]] += 1
            db.executemany(
                "INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?)", res["rows"])
            db.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?)",
                       (job.card_id, res["status"], res["http_status"], res["fetched_at"]))
            if n % 250 == 0:
                db.commit()
                if progress:
                    print(f"  {n}/{len(jobs)} {counts}", file=sys.stderr, flush=True)
    db.commit()
    return counts


def coverage(db_path: Path) -> dict:
    db = sqlite3.connect(db_path)
    out = {}
    for src, col in (("tcgplayer", "usd"), ("cardmarket", "eur")):
        out[src] = db.execute(
            f"SELECT COUNT(DISTINCT card_id) FROM prices WHERE source=? AND {col} IS NOT NULL",
            (src,)).fetchone()[0]
    out["cards_with_any_price"] = db.execute(
        "SELECT COUNT(DISTINCT card_id) FROM prices").fetchone()[0]
    out["cards_attempted"] = db.execute("SELECT COUNT(*) FROM fetch_log").fetchone()[0]
    out["no_price"] = db.execute(
        "SELECT COUNT(*) FROM fetch_log WHERE status='nodata'").fetchone()[0]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", type=Path, default=Path("build/catalog/catalog.sqlite"))
    ap.add_argument("--out", type=Path, default=Path("build/prices/prices.sqlite"))
    ap.add_argument("--langs", default="en,ja")
    ap.add_argument("--rate", type=float, default=8.0, help="max requests per second")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-age-hours", type=float, default=20.0,
                    help="refetch a card only once its cached price is older than this")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)
    counts = run(args.catalog, args.out, args.langs.split(","), args.rate, args.workers,
                 args.max_age_hours, args.limit)
    total = sum(counts.values())
    print(f"done: {counts}", file=sys.stderr)
    print(f"coverage: {coverage(args.out)}", file=sys.stderr)
    # A handful of transient failures is normal; a wall of them is a broken run.
    return 1 if total and counts["error"] / total > 0.02 else 0


if __name__ == "__main__":
    sys.exit(main())
