# Binder Swap

An iPhone app for Pokémon card collectors (English and Japanese). Photograph a binder page to digitize it, keep wish lists up to date automatically, and meet other collectors to find trades instantly, with estimated values.

The product and technical spec is in [`SPEC.md`](SPEC.md).

## What's in this repo

| Path | What it is |
|---|---|
| [`SPEC.md`](SPEC.md) | Product and technical spec (decisions, open questions, roadmap) |
| [`pipeline/`](pipeline/) | Python data pipeline: card catalog, card images, visual index, binder-page recognition prototype, evaluation, reference rules |
| [`spec/vectors/`](spec/vectors/) | JSON test cases for the collection and trading rules. The Python reference and the iOS app both must pass them |
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
```

See [`pipeline/README.md`](pipeline/README.md) for details, including how to label your own binder photos.
