# Binder Swap pipeline

Server-side data pipeline and recognition prototype for Binder Swap. Python 3.11+.

```
binderswap/
  catalog/      TCGdex -> SQLite catalog + per-set JSON packs; English cross-check
  images/       image downloader (resumable, manifest) + visual reference index
  recognition/  page -> grid -> pockets -> OCR + visual match -> fusion -> set-mode logic
  domain/       reference implementation of the collection and trading rules (spec §4, §6.1, §7.4)
  synthetic.py  fake cards and binder-page photos for tests
  demo.py       builds a full synthetic world (catalog, image server, index, labelled pages)
```

Requirements: `pip install -e ".[dev]"`, [bun](https://bun.sh) for the catalog export (TCGdex's sources are TypeScript), and `tesseract-ocr` for collector-number OCR.

## 1. Card catalog

```bash
python -m binderswap.catalog.build      # clones tcgdex/cards-database, writes build/catalog/
python -m binderswap.catalog.crosscheck  # clones pokemon-tcg-data, adds disagreements to the review queue
```

Outputs in `build/catalog/`:
- `catalog.sqlite`: tables `sets`, `cards`, `variants`, `issues` (the review queue), `card_aliases` and `meta` (source commits)
- `packs/<lang>/<set>.json` + `packs/index.json`: what the app downloads. Each pack has a sha256, so the app only re-downloads sets that changed.
- `REPORT.md` and `CROSSCHECK.md`: data-quality reports. The current ones are copied to `reports/`.

**IDs:** each card is `{lang}/{set}/{number}`, e.g. `en/sv03/125` or `ja/SV3/125`. English and Japanese are separate catalogs.

**Current snapshot (TCGdex @ `baddf4f0`):** 328 sets and 34,738 cards (21,290 English, 13,448 Japanese). The Pokémon TCG Pocket digital cards are excluded. English agrees with pokemontcg.io on **99.7%** of 20,497 compared cards. Every disagreement is in the `issues` table for review.

**New sets:** rerun both commands. The `catalog-build` workflow does this weekly and on demand.

## 2. Images and visual index

```bash
python -m binderswap.images.fetch --langs en,ja [--sets en/sv03] [--rate 10]
python -m binderswap.images.index
```

Images are saved to `build/images/<lang>/<set>/<number>.png`, and `manifest.sqlite` records the status and sha256 of each one. Rerunning only fetches what's missing. The index (`build/index/<lang>.npz`) records which embedder built it, and the recognizer refuses a mismatched index.

The default embedder (`classic-v1`) needs no model weights: an art thumbnail plus colour histograms, with ORB geometric verification when re-ranking. It's there to make the whole pipeline work and measurable. The `Embedder` interface is where a learned model plugs in; on iOS that's Vision's feature print.

## 3. Recognizing a binder page

```bash
python -m binderswap.recognition.cli photo.jpg --overlay debug.jpg
python -m binderswap.recognition.cli photo.jpg --layout 3x3 --set en/sv03 --page 4
```

Steps: find and flatten the page, detect the pocket grid from the gaps between pockets (works with empty pockets and glare), classify each pocket as card, empty or unknown, crop each card, read the collector number (OCR, voted over several readings), search visual candidates, and fuse the evidence. Then two page-level priors apply: the page's dominant set, and in a Set binder each pocket's expected number. The output is ✅ confirmed, ❓ review (with a ranked list of candidates for the swipe picker), or ⬜ empty. In a Set binder, an empty pocket becomes a specific missing card.

## 4. Measuring accuracy on your binder photos

Put photos in a folder with a `labels.json`:

```json
[
  {"photo": "IMG_0412.jpg", "layout": [3, 3],
   "slots": ["en/sv03/001", "en/sv03/002", null, "en/sv03/004", "?", "en/sv03/006", "en/sv03/007", "en/sv03/008", "en/sv03/009"]},
  {"photo": "IMG_0413.jpg", "layout": [3, 3], "set_mode": {"set_id": "en/sv03", "page_index": 1},
   "slots": ["en/sv03/010", null, "en/sv03/012", "en/sv03/013", "en/sv03/014", "en/sv03/015", "en/sv03/016", "en/sv03/017", null],
   "expected_wishes": ["en/sv03/011", "en/sv03/018"]}
]
```

Pockets are listed row by row. `null` means an empty pocket, and `"?"` means a card that isn't in the catalog. Card IDs are in `catalog.sqlite` (`SELECT id, name FROM cards WHERE set_id='en/sv03'`).

```bash
python -m binderswap.recognition.eval --pages photos/labels.json --out photos/report.md [--detect-layout]
```

The report gives top-1 and top-k accuracy, layout detection accuracy, empty-pocket accuracy, set-mode wish-list accuracy, and a threshold sweep. The sweep shows auto-confirm **precision** against **coverage** and recommends the lowest threshold that meets the 99.5% precision target (spec §5.4, §10).

## 5. Collection and trading rules

`binderswap/domain/core.py` is the executable specification for binder types (Set, Trade, Collect), what's tradeable, set-gap wishes, matching, fair-trade suggestions, recording trades and plan limits. The iOS app must pass the same JSON cases in `../spec/vectors/`.

## Tests

```bash
pytest -q
```

Tests build a synthetic world (80 fake cards served from a local HTTP server), fetch images, build the index, and recognize labelled synthetic pages end to end. The synthetic results show the pipeline works. **They do not measure real accuracy.** Only real binder photos can.
