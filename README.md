# Binder Swap

An iPhone app for Pokémon card collectors (English and Japanese). Photograph a binder page to digitize it, keep wish lists up to date automatically, and meet other collectors to find trades instantly, with estimated values.

The product and technical spec is in [`SPEC.md`](SPEC.md).

## What's in this repo

| Path | What it is |
|---|---|
| [`SPEC.md`](SPEC.md) | Product and technical spec (decisions, open questions, roadmap) |
| [`pipeline/`](pipeline/) | Python data pipeline: card catalog, card images, visual index, binder-page recognition prototype, price cache, evaluation, reference rules |
| [`app/`](app/) | The Swift side: `BinderSwapCore`, the trading rules and index-pack reader, buildable without Xcode |
| [`spec/vectors/`](spec/vectors/) | JSON test cases for the collection and trading rules, plus an index-pack fixture. The Python reference and the Swift package both must pass them |
| [`BLOCKERS.md`](BLOCKERS.md) | Blocker blotter: what is blocking next steps, owner, status |
| [`pipeline/reports/`](pipeline/reports/) | Latest catalog build report and English cross-check report |
| `.github/workflows/` | CI tests; weekly or manual catalog rebuild (plus optional image download and index build) |

The iOS app itself is next. See the roadmap in `SPEC.md` §13.

## Quick start

```bash
cd pipeline
pip install -e ".[dev]"          # plus: bun (catalog export), tesseract (OCR)
pytest -q                        # 41 tests, synthetic end-to-end included

# Card catalog (EN + JA) from TCGdex, cross-checked against pokemon-tcg-data
python -m binderswap.catalog.build
python -m binderswap.catalog.crosscheck

# Card images + visual index (needs access to assets.tcgdex.net)
python -m binderswap.images.fetch --langs en,ja
python -m binderswap.images.index

# Recognize a binder page photo
python -m binderswap.recognition.cli IMG_0412.jpg --overlay out.jpg [--set en/sv03]

# Measure accuracy on labelled photos
python -m binderswap.recognition.eval --pages photos/labels.json --out report.md

# Index pack the iOS app can read (.bspk, memory-mapped)
python -m binderswap.images.pack --index build/index/en.npz --out build/packs/en.bspk

# Daily price cache (TCGplayer USD + Cardmarket EUR, via TCGdex)
python -m binderswap.prices.fetch --langs en,ja

# Binder pages built from real card art, with exact ground truth
python -m binderswap.realpages --pages 40 --langs en --out build/realpages

# Does the embedder still discriminate against the whole catalog, not 80 cards?
python -m binderswap.recognition.scalecheck --index build/index/en.npz --n 400

# How well does the number reader actually read real cards?
python -m binderswap.recognition.ocrcheck 200 0.35
```

### What the measurements say today

| | |
|---|---|
| Embedder (`classic-v1`) top-4, full 19,724-card pool | 1.000 clean, 0.98 moderate, 0.86 harsh |
| Number reading, exact number **and** total | 0.767 clean, 0.487 mild, 0.280 heavy (n=400) |
| Recognising a 9-card page | 1.22s |
| Real-art pages: layout / top-1 / top-4 | 1.000 / 0.977 / 0.994 (n=309 cards) |
| Auto-confirm at threshold 0.7 | precision 1.000, coverage 0.951 (our degradation model, a ceiling) |
| Price coverage, EN / JA | 0.964 / 0.800 (Cardmarket; TCGplayer has no JA) |

The embedder is not the bottleneck; segmentation and number reading are. See
[`BLOCKERS.md`](BLOCKERS.md) for what that implies and what is still open.

See [`pipeline/README.md`](pipeline/README.md) for details, including how to label your own binder photos.
