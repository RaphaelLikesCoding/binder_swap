# Roadmap

The ordered plan. [`BLOCKERS.md`](BLOCKERS.md) is what is *stuck* and the
historical log; this is what we do next, in order.

## How this file works

- **Milestones are sequential.** A milestone is done when every task in it meets
  its *Done when*. Tasks inside a milestone are ordered by dependency.
- **Every task has an owner** — Owner (you) or Claude. Nothing is unowned.
- **Every task has a verifiable *Done when*.** Not "improve recognition" but a
  number, a passing test, or an artefact that exists. If a task cannot be given
  one, it is not understood well enough to start.
- **Measured claims carry their n and their bar.** A number without a sample
  size and a pre-registered threshold is an anecdote.
- **Decisions are not tasks.** They are listed once, below, with what each one
  blocks. An undecided item blocks its dependents rather than being guessed.

---

## Decisions waiting on the owner

Each blocks real work. Roughly in the order they start to hurt.

| # | Decision | Blocks | Notes |
|---|---|---|---|
| D1 | **Branding and domain.** Is "Binder Swap" clear for trademark and App Store use, and do we own a domain? | Bundle id (placeholder `com.binderswap.app` today), App Store listing, the profile URL `binderswap.app/u/<handle>` | Cheap to settle, and everything downstream hardcodes it. Renaming a shipped bundle id is not possible. |
| D2 | **Apple Developer account** — enroll at $99/yr? | Running on a real iPhone, TestFlight, any submission. Enrolment can take days | Simulator works without it. Nothing else does. |
| D3 | **Minimum iOS version.** SPEC §2 says 17+ `[VERIFY]`; the project currently targets **16.0** | Which APIs we may use | 16 vs 17 vs 18 is a reach-versus-capability call. I can measure what each buys if useful. |
| D4 | **Japanese catalogue gaps** (BLOCKERS #5): 44% of JA cards have no image, whole vintage sets have none | Whether JA ships in v1 at parity, or ships degraded and labelled | Options: contribute upstream to TCGdex, hand-fill, pay for Scrydex, or ship JA knowingly partial. |
| D5 | **Published profile expiry** — 30 days is a placeholder (SPEC §7.3) | The profile QR feature | Shorter = fresher lists, more dead QRs. Longer = someone scans a code and sees a list from months ago. |
| D6 | **Social login at all?** Offering Google/Facebook obliges an equivalent privacy-preserving option (Sign in with Apple) | Sign-in UI, App Store gate §6.4 | Recommendation: email one-time code only. Fewer obligations, nothing to breach. |
| D7 | **Cross-language wishes** — may a wish ever accept "any language"? | Matching semantics; JA/EN are separate catalogues today | Affects the match rules and their vectors. |
| D8 | **Price accuracy tolerance** (SPEC §8.3) — median error under 10%? | The pre-launch accuracy gate | Note it **cannot be run for Japanese**: TCGplayer lists no JA cards, so there is no independent source to check against. |

---

## M0 — Prove the toolchain  ✅ *complete*

| # | Task | Owner | Done when |
|---|---|---|---|
| 0.1 | ~~Rules layer in Swift, passing the shared vectors~~ | Claude | ✅ `BinderSwapCore`, 14 tests, same `spec/vectors/*.json` as Python |
| 0.2 | ~~Index pack format both languages can read~~ | Claude | ✅ `.bspk`; real index round-trips at `max|delta| = 0` |
| 0.3 | ~~App builds for iOS~~ | Claude | ✅ `BUILD SUCCEEDED`, device and simulator SDK |
| 0.4 | ~~Launch the app in a simulator~~ | Claude | ✅ 2026-09-30. Runs on iPhone 18 Pro / iOS 27.0; the first screen renders and its numbers are the rules firing live — tradeable is 1 because a Keep card and a set-needed card are both excluded, and `owned_elsewhere` resolves across binders. |
| 0.5 | ~~App build in CI~~ | Claude | ✅ `core-tests` now has an `app` job: generates the project with xcodegen and builds for iOS. |

## M1 — Recognition on the device  *(the hard part, and the real unknown)*

Everything here is a port with an existing Python reference and a measured
number to hold it against. Same discipline as M0: cross-language fixtures, so
Swift is checked against values Python produced.

| # | Task | Owner | Blocked by | Done when |
|---|---|---|---|---|
| 1.1 | **Real binder photos** — 30–50 pages, Set and Trade, EN and JA, 9- and 4-pocket, some with glare | **Owner** | — | Photos in `photos/`; Claude drafts `labels.json`, owner confirms. **This is the only path to a real accuracy number**; everything measured so far is our own degradation model. |
| 1.2 | `classic-v1` embedder in Swift | Claude | — | A committed fixture of card→vector from Python; Swift reproduces it to float16 precision. |
| 1.3 | Page geometry in Swift (`locate_page`, `slots_for`, `crop_card`) | Claude | 1.2 | On the `realpages` corpus, Swift matches Python's layout detection and per-slot crops within tolerance. |
| 1.4 | Ship index packs to the device | Claude | 1.2 | App loads `en.bspk` and searches it; EN is 40.7 MB, so bundle-vs-download is a real call to make here. |
| 1.5 | End-to-end recognition in the app | Claude | 1.1–1.4 | A photographed page produces 4 candidates per pocket with set and number, on device. |
| 1.6 | **Accuracy on real photos** | Claude | 1.1, 1.5 | The §5.4 bar, measured on the owner's photos: **auto-confirm precision ≥ 0.995 at coverage ≥ 0.70**. Currently 1.000 / 0.951 on synthetic degradation — which is a ceiling, not an answer. |

## M2 — The product loop

| # | Task | Owner | Blocked by | Done when |
|---|---|---|---|---|
| 2.1 | Local persistence (SwiftData or SQLite) | Claude | — | Collection survives a relaunch; local-first per §6.5, nothing leaves the device. |
| 2.2 | Binder list and page view, Set/Trade/Collect | Claude | 2.1 | Binder type switchable; the change immediately alters tradeables and wishes (§4.1 — everything derived, nothing migrated). |
| 2.3 | Intake flow: capture → review queue → commit | Claude | 1.5, 2.1 | Many pages in one sitting, **one** review queue at the end, auto-advancing (§6.6). Retries never burn quota. |
| 2.4 | The picker: 4 candidates, confidence, set + number | Claude | 1.5 | Decidable on sight. Reprint art is byte-identical, so a row without set and number is undecidable. |
| 2.5 | Set tracker + "this looks like Evolving Skies — track what's missing?" | Claude | 2.2 | One tap converts a binder to Set and starts the gap list. Free sees the count, Premium sees which (§6.2). |
| 2.6 | Wish list and CSV/text export | Claude | 2.5 | Export byte-identical to `spec/vectors/wishlist_export.json`. |

## M3 — Trading

| # | Task | Owner | Blocked by | Done when |
|---|---|---|---|---|
| 3.1 | Session QR + peer-to-peer exchange | Claude | 2.1 | Two devices swap with **no network** — card shows are where this is used and where signal is worst. |
| 3.2 | Match screen, value balance, fair-trade suggestion | Claude | 3.1 | Rules already exist and pass vectors; this is presentation. |
| 3.3 | Record a trade, update both inventories | Claude | 3.1 | `applyTrade` semantics: a given copy leaves its pocket, received cards land loose, a stale swap is refused. |
| 3.4 | Published profile snapshot + QR | Claude | 3.1, D1, D5 | Publish is explicit, carries a date, expires, is revocable, and is never issued to a child. |

## M4 — Money and compliance  *(before any submission)*

| # | Task | Owner | Blocked by | Done when |
|---|---|---|---|---|
| 4.1 | StoreKit 2 entitlements, server-side JWS validation | Claude | D2 | Plan gates enforced where data is written, never client-asserted. |
| 4.2 | **In-app account deletion** | Claude | 4.1 | Guideline 5.1.1(v). A guaranteed rejection without it. |
| 4.3 | **Report / block / contact** | Claude | 3.4 | Guideline 1.2, triggered by profiles and proposals. |
| 4.4 | **Restore Purchases** | Claude | 4.1 | Guideline 3.1.1. |
| 4.5 | Backup to the user's own iCloud Drive (Premium) | Claude | 2.1 | Restores onto a fresh device. Their storage, not ours. |
| 4.6 | Privacy nutrition labels from a real data inventory | Owner + Claude | 4.1–4.5 | Filled from what the code does, not from memory. |
| 4.7 | Legal review: card-image use, disclaimer, COPPA/GDPR-K | **Owner (counsel)** | — | Local-first removed most of the COPPA surface (§11) but not the IP question. |

## M5 — Quality, once there is something to improve

Deliberately last. Each is a measured *maybe*, not a known gap.

| # | Task | Owner | Done when |
|---|---|---|---|
| 5.1 | Number reader (trained) | Claude | **Only if 1.6 shows coverage below the 0.70 bar.** Today the tail costs coverage and coverage measures 0.951 — there is no problem to spend a model on. Tesseract reads 0.767 clean / 0.487 mild / 0.280 heavy (n=400) if it turns out to matter. |
| 5.2 | JA catalogue repair | Claude | D4 |
| 5.3 | Price accuracy gate | Claude | D8, and only for EN — TCGplayer lists no Japanese cards |
| 5.4 | Learned embedder to replace `classic-v1` | Claude | Only if 1.6 says the descriptor is the limit. It is not today: top-4 is 1.000 clean and 0.98 moderately degraded. |

---

## Closed, so nobody reopens them

- **Segmentation rewrite** — branch `segmentation-grid-fit`. The 0.611 that motivated it came from cardbinderideas composites, which are posters with a title bar and watermark, not photographs of binders. On realistic pages `locate_page` gets layout 1.000 unchanged. Superseded; re-test only if real photos say otherwise.
- **Number-band template matching** — `bandcheck`. Hurts on a random card (0.973 → 0.963); on the tail it is +0.09 at mild degradation and nothing at heavy, against a ceiling of 1.000. Most of the band is identical on a reprint, so correlation dilutes the digits.
- **Empty-pocket detection** — 0.889 is 3 errors in 27, all an empty pocket offered as a card, none the reverse. Tightening it would trade harmless dismissals for silently losing a card.
