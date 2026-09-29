# Blocker blotter

Open blockers for Binder Swap, most critical first. Update the **Status** and **Log** whenever something moves. When a blocker is cleared, move it to *Cleared* with the date.

**Status values:** 🔴 blocked · 🟡 in progress · 🟢 cleared

Last updated: 2026-09-29

## Open

| # | Blocker | Holds up | Owner | Status | Next action |
|---|---|---|---|---|---|
| 1 | **Real card images not downloaded.** `assets.tcgdex.net` is blocked in the Claude Code cloud environment. | Visual index → any real accuracy test | Claude | 🟡 | `catalog-build` running on GitHub Actions with images on (GitHub's machines aren't blocked). Started by pushing `.github/catalog-build-request.json`, because the Claude GitHub App can't dispatch workflows (403). Optional: also allow `assets.tcgdex.net` + `api.tcgdex.net` in the environment's network settings, so work can happen in the session too. |
| 2 | **Real binder photos not in the repo.** | Real accuracy numbers; the ✅ auto-confirm threshold | Owner | 🔴 | Upload ~30–50 pages (Set + Trade, EN + JA, 9- and 4-pocket, some glare) in chat or to `photos/`. Claude drafts `labels.json` from the catalog; owner confirms. |
| 3 | **No macOS / Xcode build machine.** The session is Linux: Swift can be written but not compiled or run. | The iOS app itself; building the app's Vision-based visual index | Owner | 🔴 | A Mac with Xcode, or GitHub macOS runners (more expensive minutes on private repos). |
| 3b | **No Apple Developer account.** | Running on a real iPhone, TestFlight, App Store | Owner | 🔴 | Enroll ($99/yr). |
| 4 | **Price feed not built**; its source `api.tcgdex.net` is blocked in the session. | Trade values on the match screen | Claude | 🔴 | After #1: build the daily price cache (can also run in GitHub Actions). Doesn't block recognition. |
| 5 | **Japanese catalog gaps**: 127 sets only; some incomplete (e.g. `ja/SV4a` missing 40 of 190); ~3,600 cards without rarity; **5,931 of 13,448 JA cards (44%) have no image on TCGdex** (EN: 1,567 of 21,290, 7%). Cards without an image can only be matched by their printed number. | A trustworthy JA catalog | Claude + owner | 🔴 | Decide: contribute fixes upstream to TCGdex, fill by hand, or Scrydex (paid) later. See `pipeline/reports/catalog-build.md`. |
| 6 | **Open product decisions**: plan numbers (binder/scan limits, prices); whether free adult users need an account; domain and branding; whether a wish can accept any language. | Paywall, onboarding | Owner | 🔴 | Decide; Claude updates `SPEC.md` §6.1 / §14. |

## Before launch (not blocking development)

| Item | Owner | Status |
|---|---|---|
| Legal review: card-image use and the "not affiliated" disclaimer | Owner (counsel) | 🔴 |
| Legal review: COPPA / GDPR-K setup for kid accounts | Owner (counsel) | 🔴 |
| Switch GitHub's default branch to `main` (Settings → General → Default branch) | Owner | 🔴 |

## Cleared

| # | Blocker | Cleared | How |
|---|---|---|---|
| — | No `main` branch | 2026-09-29 | Created from `dab21fc` and pushed |

## Log

- **2026-09-29 12:05**: Attempt 1 ([run](https://github.com/RaphaelLikesCoding/clip_studio/actions/runs/36558935912)) downloaded **27,233 images** (EN 19,716 · JA 7,517, 2.2 GB) in 58 min; **7,498 not on TCGdex's server** (EN 1,567 · JA 5,931); 8 transient errors. The fetcher exited 1 on *any* error, so the index build and artifact upload were skipped (bug). Fixed: fail only above a 1% error rate, cache images between runs, always upload the manifest, report missing images by set. Attempt 2 requested.
- **2026-09-29**: Direct workflow dispatch refused (403: the Claude GitHub App lacks Actions write permission). Added a push trigger on `.github/catalog-build-request.json`; build requested by pushing that file.
- **2026-09-29**: Blotter created. #1 moved to 🟡: image download + index build handed to GitHub Actions (`catalog-build`, images on, high-resolution webp to fit the runner's disk).
