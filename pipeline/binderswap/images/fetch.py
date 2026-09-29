"""Download card images for every catalog card, resumably, with a manifest.

    python -m binderswap.images.fetch --catalog build/catalog/catalog.sqlite \
        --out build/images [--langs en,ja] [--sets en/sv03,...] [--quality high]

Images land at ``<out>/<lang>/<set>/<local_id>.<ext>``. The manifest
(``<out>/manifest.sqlite``) records status, size and sha256 per image, so a
rerun only fetches what's missing or failed, and new sets are picked up by
simply rerunning after a catalog rebuild.

Card art is © The Pokémon Company / Nintendo / Creatures / GAME FREAK. Images
are fetched for display and for building the recognition index only.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

USER_AGENT = "BinderSwapCatalog/0.1 (+https://github.com/RaphaelLikesCoding/clip_studio)"

MANIFEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    card_id TEXT NOT NULL,
    quality TEXT NOT NULL,            -- high | low
    url TEXT NOT NULL,
    path TEXT,
    status TEXT NOT NULL,             -- ok | missing | error
    http_status INTEGER,
    bytes INTEGER,
    sha256 TEXT,
    error TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (card_id, quality)
);
"""

# TCGdex serves {image_base}/{quality}.{ext} with ext png | webp | jpg.
# Default: lossless png for high, small webp for low. high.webp is ~10x
# smaller than png at the same resolution; use it where disk is limited (CI).
FORMATS = {"high": "png", "low": "webp"}


@dataclass
class Job:
    card_id: str
    url: str
    dest: Path


class RateLimiter:
    """At most ``rate`` requests per second across all worker threads."""

    def __init__(self, rate: float):
        self.interval = 1.0 / rate if rate > 0 else 0.0
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


def plan(catalog: Path, out: Path, quality: str, langs: list[str], sets: list[str] | None,
         manifest: sqlite3.Connection, retry_errors: bool, ext: str | None = None) -> list[Job]:
    ext = ext or FORMATS[quality]
    done = {row[0]: row[1] for row in manifest.execute(
        "SELECT card_id, status FROM images WHERE quality=?", (quality,))}
    con = sqlite3.connect(catalog)
    q = "SELECT id, lang, set_id, local_id, image_base FROM cards WHERE lang IN (%s)" % ",".join("?" * len(langs))
    params: list[str] = list(langs)
    if sets:
        q += " AND set_id IN (%s)" % ",".join("?" * len(sets))
        params += sets
    jobs = []
    for cid, lang, set_id, local_id, base in con.execute(q + " ORDER BY id", params):
        status = done.get(cid)
        if status in ("ok", "missing") or (status == "error" and not retry_errors):
            continue
        dest = out / lang / set_id.split("/", 1)[1] / f"{local_id}.{ext}"
        jobs.append(Job(cid, f"{base}/{quality}.{ext}", dest))
    con.close()
    return jobs


def fetch_one(job: Job, limiter: RateLimiter, timeout: float, retries: int) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    last_err = ""
    for attempt in range(retries + 1):
        limiter.wait()
        try:
            req = urllib.request.Request(job.url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            job.dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = job.dest.with_suffix(job.dest.suffix + ".part")
            tmp.write_bytes(body)
            tmp.replace(job.dest)
            return {"status": "ok", "http_status": 200, "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(), "path": str(job.dest),
                    "error": None, "fetched_at": now}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"status": "missing", "http_status": 404, "bytes": None, "sha256": None,
                        "path": None, "error": None, "fetched_at": now}
            last_err = f"HTTP {e.code}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = str(e)
        time.sleep(min(2 ** attempt, 16))
    return {"status": "error", "http_status": None, "bytes": None, "sha256": None,
            "path": None, "error": last_err[:300], "fetched_at": now}


def run(catalog: Path, out: Path, quality: str = "high", langs: list[str] | None = None,
        sets: list[str] | None = None, workers: int = 8, rate: float = 20.0, timeout: float = 30.0,
        retries: int = 3, retry_errors: bool = False, limit: int | None = None,
        progress: bool = True, ext: str | None = None) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    manifest = sqlite3.connect(out / "manifest.sqlite")
    manifest.executescript(MANIFEST_SCHEMA)
    jobs = plan(catalog, out, quality, langs or ["en", "ja"], sets, manifest, retry_errors, ext)
    if limit is not None:
        jobs = jobs[:limit]
    limiter = RateLimiter(rate)
    counts = {"ok": 0, "missing": 0, "error": 0}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_one, j, limiter, timeout, retries): j for j in jobs}
        for i, fut in enumerate(cf.as_completed(futures), 1):
            job, res = futures[fut], fut.result()
            counts[res["status"]] += 1
            manifest.execute(
                "INSERT OR REPLACE INTO images VALUES (?,?,?,?,?,?,?,?,?,?)",
                (job.card_id, quality, job.url, res["path"], res["status"], res["http_status"],
                 res["bytes"], res["sha256"], res["error"], res["fetched_at"]))
            if i % 200 == 0:
                manifest.commit()
                if progress:
                    print(f"  {i}/{len(jobs)} {counts}", file=sys.stderr)
    manifest.commit()
    manifest.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", type=Path, default=Path("build/catalog/catalog.sqlite"))
    ap.add_argument("--out", type=Path, default=Path("build/images"))
    ap.add_argument("--quality", choices=sorted(FORMATS), default="high")
    ap.add_argument("--ext", choices=["png", "webp", "jpg"], help="image format (default: png for high, webp for low)")
    ap.add_argument("--langs", default="en,ja")
    ap.add_argument("--sets", help="comma-separated catalog set ids, e.g. en/sv03,ja/SV3")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rate", type=float, default=20.0, help="max requests per second")
    ap.add_argument("--retry-errors", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)
    counts = run(args.catalog, args.out, args.quality, args.langs.split(","),
                 args.sets.split(",") if args.sets else None, args.workers, args.rate,
                 retry_errors=args.retry_errors, limit=args.limit, ext=args.ext)
    print(f"done: {counts}", file=sys.stderr)
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
