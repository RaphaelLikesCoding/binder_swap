# Binder Swap — Product & Technical Spec

> Status: **Draft v0.3** (owner decisions from rounds 1–2 applied) · Working name: *Binder Swap* · Repo: `clip_studio`
>
> This is a living document. Items marked **[DECISION]** need an owner call; items marked **[VERIFY]** are assumptions that must be checked before we build on them.

---

## 1. Problem & Vision

Collectors keep trading cards in physical binders. Finding a trade today means flipping through each other's binders page by page, from memory, with no idea of fair value.

**Binder Swap** turns a binder into a digital inventory in a few photos. It keeps a wish list up to date on its own, and when two collectors meet it shows instantly what each has that the other wants, and roughly what those cards are worth.

### The core loop

1. **Snap** a binder page, and the app recognizes the cards and the page layout.
2. **Confirm** any cards the app is unsure about with a swipe picker.
3. **Collect**: in set mode, empty slots become wish list items automatically.
4. **Meet**: two phones connect by QR code or by being close together.
5. **Match**: each side sees *"they have N cards you need / you have M cards they need"* with estimated values.
6. **Deal**: the users agree on a trade in person. Recording it in the app is optional.

---

## 2. Target Users

| Persona | Needs |
|---|---|
| **Set completer** | Tracks progress toward full sets. Wants gaps found for them and wants to find trades for the missing cards. |
| **Kid collector** (with a parent) | **Supported in v1.** Simple intake and safe, in-person-only trading under a parent-managed account (see §11). |
| **Card-show / league trader** | Fast matching in crowded, low-signal venues. Needs to trust the values. |

---

## 3. Scope

### Platforms
- **v1: iPhone only** (decided). iOS 17+ **[VERIFY]** the minimum against the features we need. iPad works but is not optimized for.
- **Later:** Android. This affects the phone-to-phone exchange protocol today (see §7.3): **nothing in the exchange may depend on Apple-only transports.**

### Card games
- **Pokémon TCG only** (decided), in **English and Japanese** (decided).
- English and Japanese are **separate catalogs**: Japanese sets have different names, set codes, numbering and set boundaries from their English counterparts, and they are priced separately. A Japanese card never matches an English wish, unless a later "any language" wish option is added **[DECISION]** for later.

### Out of scope for v1
- Payments, escrow, or cash-difference settlement inside the app
- Remote trading or shipping between strangers (marketplace)
- Grading or condition detection from photos
- Graded slabs (PSA/BGS/CGC)

---

## 4. Core Concepts & Data Model

```
CatalogCard   (from data provider; read-only)
  id, game, set_id, number, name, rarity, variants[], image_url, set_total

CatalogSet
  id, game, name, series, release_date, printed_total, total_incl_secrets, symbol_url

Binder
  id, name, layout {rows, cols}          // e.g. 3x3 (9-pocket), 2x2, 3x4
  type: set | trade | collect             // owner-switchable at any time (§4.1)
  set_id?                                 // set type only
  slot_order: row-major | column-major    // how numbering flows across a page
  start_number?                           // set mode: number in page 1, slot 1
  pages[]

Page
  index, photo_ref?, slots[rows*cols]

Slot
  position, state: empty | card | unknown
  collection_item_id?

CollectionItem
  card_id, variant (normal | holo | reverse_holo | 1st_ed | …),
  condition (NM | LP | MP | HP | DMG, default NM),
  quantity, location (binder/page/slot)?,
  keep: bool                              // opt-out: never offered even in a trade binder
  id_source: auto_confident | user_confirmed | manual

WishlistItem
  card_id, variant?, quantity, priority (need | want),
  source: manual | set_gap | set_goal

TradeSession
  peer_display_name, started_at, their_haves[], their_wants[],
  matches, proposed_trade?, status

TradeRecord                               // written when both sides accept
  id, completed_at, peer_display_name,
  gave[] {card_id, variant, condition, qty, est_value},
  got[]  {card_id, variant, condition, qty, est_value}
```

### 4.1 Binder types (decided)
A user can have many binders (the limit depends on plan, §6.1). Each binder has one **type**, and the user can flip it with a switch at any time:

| Type | Cards in it are… | Empty slots are… | Typical use |
|---|---|---|---|
| **Set** | **Not tradeable.** They're completing a set. | **Needed:** each blank slot is a specific missing card and goes on the wish list automatically (§5.3). | Completing Obsidian Flames in number order |
| **Trade** | **Tradeable by default.** The user can mark individual cards **Keep** to exclude them. | Meaningless (no wish list effect). | The binder you bring to a card show |
| **Collect** | **Not tradeable.** Personal collection. | Meaningless. | Favorites, mixed collections |

### Key rules
- **Tradeable is decided by binder, not by duplicate count.** A card is offered in a swap **only if** it sits in a **Trade** binder and isn't marked **Keep**. Cards in Set and Collect binders are never offered, and neither are cards with no binder (manual adds). Duplicates are not special.
- **Flipping a binder's type is instant and reversible.** Set → Trade removes that binder's auto-generated wishes and makes its cards tradeable. Trade → Set regenerates the gap wishes. Manual wishes are never touched.
- **Needs:** set-gap wishes are always priority **Need**. Manual wishes default to **Want**, and the user can promote them.
- **A needed card is never offered.** If a card is both in a Trade binder and on the same user's wish list (e.g. needed for a set binder), it is not offered. This guards against trading away a card you're about to need.
- **Wish list items are satisfied automatically.** When a wished card enters the collection, the wish is marked fulfilled.
- **A set goal** ("complete Obsidian Flames") creates wish list items for every missing number, and optionally for master-set variants.

---

## 5. Feature: Binder Page Intake (Photo Recognition)

This is the product's differentiator **and its biggest technical risk**.

### 5.1 User flow
1. The user opens a binder and taps **Add page**. The camera shows a page outline guide.
2. The app detects the page and flattens the perspective, and warns about glare, blur, or a partly visible page.
3. The app proposes a **layout** (e.g. *3×3 detected*) and the user can correct it once per binder.
4. Results appear over the photo:
   - ✅ **Confirmed**: confidence at or above the auto-accept threshold
   - ❓ **Needs review**: tap it to open the **candidate picker**
   - ⬜ **Empty slot**: in set mode, labeled with the *expected* card (e.g. "#047 missing → added to wish list")
5. **Candidate picker:** a full-screen carousel of the top-k matches, highest probability first. Swipe left and right to browse, and tap to confirm. Each candidate shows the card image, name, set, number and variant. A *Search* option handles cases where the right card isn't among the candidates.
6. **Save page.** Unresolved ❓ slots stay in a "to review" queue, so the user never has to finish in one sitting.

### 5.2 Recognition pipeline (on-device first)

| Stage | Approach (iOS) |
|---|---|
| Page detection & de-skew | Vision document segmentation / rectangle detection → perspective correction |
| Slot grid | Detect card-shaped rectangles → cluster into rows/cols → snap to common layouts (2×2, 3×3, 3×4, 4×3) |
| Slot classification | Empty / card front / card back / obstructed (small Core ML classifier) |
| Text cues | `VNRecognizeTextRequest` on the card name band and bottom collector-number band (`045/198`, set code, regulation mark) |
| Visual match | Image embedding (Vision feature print or a fine-tuned model) → nearest neighbor against a pre-computed embedding index of catalog art |
| Fusion | Combine OCR + visual similarity + **page priors** (below) into a calibrated probability per candidate |

The **visual index** covers all sets in scope. It ships as a downloadable pack per set or era so the app stays small, and is refreshed when new sets release.

### 5.3 Page priors ("smart" context)
- **Same-set prior:** if most confident cards on a page belong to set S, raise the probability of S for the uncertain ones.
- **Sequence prior (set mode):** a set-mode binder is treated as a **template**: `slot → expected card number`. One confidently identified card anchors every slot on the page, using `start_number`, `slot_order` and the page index.
  - An empty slot resolves to a specific missing card number, which is **added to the wish list**.
  - A filled slot whose expected number disagrees with its recognized number is flagged ("out of order?"), not silently overwritten.
- **Trade and Collect binders:** only the same-set prior applies. Empty slots mean nothing.

### 5.4 What "100% confident" means
No recognizer is ever literally 100% sure. **Definition:** a card gets a ✅ only when its calibrated confidence exceeds a threshold that we tune on a labeled test set, so that **fewer than 1 in 200 auto-confirmed cards are wrong** **[DECISION]** on the target. The threshold should also be tuned per variant, because variants are the hard part (§5.5).

### 5.5 Known hard cases (design for them, don't pretend they're solved)
- **Glare through binder sleeves.** This is the most common failure. Mitigations: glare detection, a "tilt slightly" hint, and an optional two-shot capture merge.
- **Reverse holo vs normal vs holo.** The art is identical, and a flat photo shows the foil pattern only weakly. v1 should **ask** when variant is ambiguous and default to the most common variant rather than guess silently.
- **Reprints and alternate arts** with the same name across sets: the collector number and set symbol decide.
- **Secret rares** numbered above the printed set total (e.g. `205/198`). The sequence prior must allow for them.
- **Japanese cards.** The name OCR must handle Japanese script, and the language is detected per card (from script, set code and card frame). Mixed-language pages are allowed. Japanese collector numbers and set codes follow a different format, so the parser needs a separate path for them.
- **Small pockets**, 4×3 or larger: lower resolution per card, so the camera may need to capture at maximum resolution.

### 5.6 Learning loop
Every user confirmation or correction is a labeled example. Store these locally. With **opt-in** consent, upload anonymized crops to improve the models. The app never uploads full photos without consent.

---

## 6. Feature: Collection, Binders & Wish List

- **Binders:** create, rename, reorder, and set layout and **type** (Set / Trade / Collect, §4.1). Page view mirrors the physical binder.
- **Set tracker:** progress per set (e.g. `142 / 198`, with a master-set count optional), plus a list of missing cards.
- **Manual add:** search by name, number, or set, for single cards or when there's no binder.
- **Wish list:** manual items, set-gap items and set-goal items, each marked **Need** or **Want**. Can be filtered and sorted by value.
- **Keep flags:** per card in Trade binders (§4.1).
- **Backup & sync:** so an inventory is never lost with a phone. See §9.

### 6.1 Plans & monetization (decided: freemium + subscription + one-time purchase)
The numbers below are **proposals** **[DECISION]**. The structure is decided.

| | **Free** | **Premium** (subscription) | **Lifetime** (one-time purchase) |
|---|---|---|---|
| Binders | 2 | Tiered: e.g. 10 / 30 / unlimited | Same as the top subscription tier |
| Photo page scans | e.g. 20 / month | Unlimited | Unlimited |
| Manual adds, set tracker | ✅ | ✅ | ✅ |
| Swaps and matching | ✅ | ✅ | ✅ |
| **Recording trades** (inventories update on both phones) | ✅ | ✅ | ✅ |
| **Trade history** (stored records, values at trade time, export) | Last trade only | ✅ Full history | ✅ Full history |
| Cloud backup & sync | ❌ (on device only) | ✅ | ✅ |
| Price refresh | Weekly | Daily | Daily |
| Family: parent + child accounts | 1 child | Up to 4 children | Up to 4 children |

- Recording a trade is **free for everyone**, because a swap only works if both sides' inventories stay correct. **Storing** trade history is the premium feature.
- Purchases go through **Apple In-App Purchase** (StoreKit 2), which the App Store requires for digital features.
- **Kids:** children never see a purchase screen. Upgrades happen from the parent account (Family Sharing where possible). **[VERIFY]** App Store kids-category rules on in-app purchases.
- **Downgrade behavior:** a user over the free binder limit keeps read-only access to all binders and can swap from all of them, but can't add new pages until they're under the limit. Data is never deleted because of a plan change.

---

## 7. Feature: Meet & Match (the swap)

### 7.1 User flow
1. Both users open **Swap**. They can do one of the following:
   - **Scan a QR code**: one phone shows a code and the other scans it (works everywhere), or
   - **Hold the phones close**: the app discovers nearby Binder Swap users, and both accept.
2. The phones exchange **trade profiles**: for-trade haves and wants only, never the full collection.
3. Each phone computes matches locally and shows:
   - **They have for you:** cards on your wish list that they are offering, with values
   - **You have for them:** cards on their wish list that you are offering, with values
   - A **value balance bar** and a "suggest a fair trade" button, which picks a subset that roughly evens out the value
4. Either user can build a proposal by selecting cards. The other user sees it live and accepts or counters.
5. When both accept, the trade is optionally **recorded**: inventories update and wishes are fulfilled on both sides.

### 7.2 About "bumping"
**[VERIFY]** iOS does **not** give third-party apps phone-to-phone NFC. Apple's own "bump" gestures (NameDrop/AirDrop) aren't available to us. What we *can* do:
- **QR code:** universal and the primary path for v1. Works cross-platform later.
- **Nearby discovery:** MultipeerConnectivity (Bluetooth/Wi-Fi peer-to-peer, **Apple-only**), with optional **Nearby Interaction (UWB)** to require the phones to be within ~20 cm, which gives a "bump-like" feel on supported iPhones.
- **Bluetooth LE:** a custom BLE service works iOS↔Android. A later option.

### 7.3 Exchange protocol (must survive Android later)
- The QR code encodes a **short-lived session invite**: a session id, an ephemeral public key, and a transport hint. It **never encodes list contents** (QR capacity is too small, and the contents would go stale).
- **"Updatable QR":** a user can also have a **permanent profile QR / link** (`binderswap.app/u/<handle>` — **[VERIFY]** domain). Because it points to live data, updating the lists never requires a new code. Scanning it without the app opens a web preview and an App Store link, which is also a growth loop.
- **Transport, in order of preference:**
  1. Local peer-to-peer (Multipeer on iOS↔iOS). Works **offline**, which matters because card shows often have poor signal.
  2. Backend relay over the internet (works iOS↔Android and at a distance).
- The payload is versioned JSON (`{schema_version, card_ids, variants, conditions, qty}`), end-to-end encrypted with the session key. Game catalog IDs must be canonical across platforms.

### 7.4 Matching logic
```
for_me   = their.tradeables ∩ my.wants     (match on card_id; variant/condition rules below)
for_them = my.tradeables    ∩ their.wants
```
- Variant: a wish with no variant accepts any variant. A variant-specific wish requires an exact match.
- Condition: wishes may set a minimum condition (default: any).
- Rank by **priority (Need > Want)**, then by value.
- **Also show** near-misses ("they have the holo, you wanted the reverse holo").

---

## 8. Feature: Card Values

### 8.1 Principles
- Show **"estimated market value"** with its source and date, never as a guaranteed price.
- Values depend on variant and condition. Show NM market by default, with a condition adjustment.
- Prices are cached server-side and refreshed daily. Devices never call price vendors directly, so no API keys ship in the app.

### 8.2 Card catalog: where the "clean database" comes from

**Does The Pokémon Company provide one?** No, not in a usable form. pokemon.com has an official *card search website* for English cards, but there is no public API, no bulk download, and no license to reuse the data or images. We should not build on it, and scraping it would be a Terms of Service and IP risk. **[VERIFY]** whether TPC offers any developer or licensing program. None was found.

**Why not scrape TCGplayer, PriceDex or similar once?** Their terms prohibit scraping. "Once" still means copying their compiled database, and the result would still need updating for every new set. Free and licensed sources exist, so we don't need to take that risk.

**Candidate sources (researched September 2026):**

| Source | Cost | EN | JA | Images | Prices | License / status |
|---|---|---|---|---|---|---|
| **TCGdex** (`api.tcgdex.net`, `github.com/tcgdex/cards-database`) | Free, no key | ✅ | ✅ | ✅ | TCGplayer (USD) and Cardmarket (EUR) fields | Open source; database repo is **MIT** licensed. Community maintained. Supports 14 languages. **Recommended primary seed.** |
| **Pokémon TCG API / pokemon-tcg-data** (pokemontcg.io) | Free | ✅ | ❌ | ✅ | TCGplayer & Cardmarket | **Legacy.** Scheduled to go offline **March 1, 2027**, and no longer updated routinely. Use only as a one-time cross-check snapshot. |
| **Scrydex** (successor to pokemontcg.io) | Paid, from about $29/mo (credit based, no free tier) | ✅ | ✅ | ✅ (HQ) | Market prices, price history, graded prices | Commercial and actively maintained. **Recommended paid upgrade or fallback** for price accuracy and Japanese prices. |
| **pokemon.com card search** | — | ✅ | ❌ | ✅ | ❌ | Official, but no API or reuse license. Useful only as a **human reference** to resolve disputes. |
| **TCGplayer API** | — | | | | | Closed to new developers. Do not plan around it. |

**Plan:**
1. **Seed once from TCGdex** (EN + JA): every set, card, variant list and image. Store it in **our own catalog database** with **our own stable card IDs**, and keep the TCGdex, pokemontcg.io, Scrydex and TCGplayer product IDs as cross-reference columns.
2. **Cross-validate English** against the pokemon-tcg-data snapshot before it shuts down. Card counts per set, numbers, names and rarities must agree, and any disagreement goes to a **review queue** that a human resolves against pokemon.com card search. This is how we reach "no questions" data: no single community source is perfect, but two independent sources that agree, plus human review of the disagreements, gets close.
3. **New sets:** a scheduled job checks sources for new sets. New sets go through the same validation and review queue before publishing, and then the app downloads that set's catalog and recognition pack. Expect a few days' lag after release for community sources; Scrydex is usually faster.
4. **Images:** we mirror images to our own storage/CDN, used for display and to build recognition embeddings. Card art is © The Pokémon Company, Nintendo, Creatures and GAME FREAK, regardless of which source serves it. **[VERIFY]** image terms with a lawyer before launch. Fan collection apps commonly display card images with a non-affiliation disclaimer, but that is a norm, not a license.

### 8.3 Price sources
- **v1: prices from TCGdex's TCGplayer and Cardmarket fields**, cached daily on our server.
- **Japanese prices:** likely sparse in free sources. **[VERIFY]** TCGdex Japanese price coverage. If it's poor, Scrydex (paid) covers Japanese cards. Show "no price data" rather than guessing.
- **Accuracy gate:** before launch, compare our values against TCGplayer's public market prices for ~200 English cards and ~100 Japanese cards across rarities. **[DECISION]** tolerance, for example median error < 10%. If the free source fails the gate, switch to Scrydex.

**Data budget (decided):** **$0 for now**, using free sources only. Revisit Scrydex (from about $29/mo) if free price coverage fails the accuracy gate, especially for Japanese cards.

---

## 9. Architecture (proposed)

```
┌───────────── iPhone app (SwiftUI) ─────────────┐
│ Camera + Vision + Core ML (recognition)        │
│ Local DB (SwiftData/SQLite) ← source of truth  │
│ Swap: QR (AVFoundation) + Multipeer + NI       │
└───────────────┬────────────────────────────────┘
                │ HTTPS
┌───────────────▼────────────────────────────────┐
│ Backend (thin)                                 │
│ • Catalog + price cache (daily ETL from APIs)  │
│ • Embedding-index packs per set (CDN)          │
│ • Accounts, sync/backup, profile links         │
│ • Swap relay (when not peer-to-peer)           │
└────────────────────────────────────────────────┘
```

### Stack decisions
- **iOS client: native Swift/SwiftUI (decided).** The hard parts (camera, Vision, Core ML, MultipeerConnectivity, Nearby Interaction) are all native Apple frameworks. A cross-platform framework would put every one of them behind a bridge and still need an Android rewrite of those modules. The cost: Android later means a second client, though the backend, protocol, catalog and models are shared. The alternative is Kotlin Multiplatform for shared business logic (matching, models) with native UIs.
- **[DECISION] Backend:** a managed option (Supabase or Firebase) for auth, database and storage, plus a small scheduled job for catalog and price ETL. It should be cheap and fast to ship. Avoid CloudKit-only sync, because it blocks Android.
- **Offline-first:** the collection lives on the device. Recognition, matching and peer-to-peer swap all work with no signal. Sync happens when online.

---

## 10. Non-Functional Requirements

| Area | Target |
|---|---|
| Page recognition latency | < 3 s per page from capture to results on iPhone 12 or newer **[VERIFY]** |
| Auto-confirm precision | ≥ 99.5% (see §5.4) |
| Auto-confirm coverage | ≥ 70% of cards on a clean 9-pocket page confirmed without review (stretch goal: 85%) |
| Swap time | QR scan → matches shown in < 5 s |
| Offline | Intake, collection, matching and local swap all work in airplane mode |
| App size | < 100 MB initial download; recognition packs downloaded per set |

---

## 11. Privacy, Safety & Compliance

- **Minimum data shared in a swap:** a display name plus for-trade and want lists. No location, contacts or full collection.
- **Kids are supported** (decided). This makes COPPA (US) and similar laws a v1 requirement, not an add-on:
  - **Age gate at signup** (neutral date-of-birth entry). Under-13 accounts require **verifiable parental consent** and are created and managed from a parent account.
  - **Child accounts:** no public profile link or web preview, no free-text display name (pick from generated names such as "BlueCharizard42"), no chat, and no remote trades. Swaps happen only in person, by QR or nearby discovery.
  - **Parent controls:** see the child's collection and trade history, and optionally require parent approval before a trade is recorded.
  - **No third-party ads or tracking analytics** in the app at all. This keeps us eligible for the App Store Kids category rules **[VERIFY]** whether we list there or in Reference/Entertainment with a 4+ rating.
  - **Data minimization:** no precise location, contacts or photos leaving the device for child accounts, including no opt-in model training (§5.6).
  - **[VERIFY]** COPPA and GDPR-K compliance with counsel before launch.
- **Photos** stay on the device unless the user opts in to contribute training data.
- **IP / trademarks:** "Pokémon" and card images belong to Nintendo, Creatures and GAME FREAK (via The Pokémon Company). **[VERIFY]** App Store naming and screenshot rules, the image licensing terms of the data provider, and a "not affiliated" disclaimer. Keep "Binder Swap" game-neutral, which is also good for multi-game support.
- **App Store guidelines:** no in-app real-money trading in v1 avoids most payment and marketplace review issues.

---

## 12. Risks (ranked)

1. **Recognition accuracy through sleeves and glare.** If intake isn't faster than typing, the product fails. → Mitigate with a **Phase 0 spike** before building anything else.
2. **Variant detection** (reverse holo). Wrong variants lead to wrong values and bad trades. → Ask the user rather than guess.
3. **Price data access and terms.** The best data (TCGplayer) is hard to get directly. → Validate a source's accuracy and licensing early.
4. **Cold start.** Swaps need *both* people to have the app. → Profile QR + web preview; a solo-player value (set tracking alone must be worth it).
5. **Android parity.** Apple-only transports would split the user base. → Platform-neutral protocol from day one (§7.3).
6. **Sports cards,** if ever in scope: huge catalogs, parallels, weak public data. Treat as a separate product decision.

---

## 13. Roadmap

### Phase 0: Recognition spike (validate the core risk)
- Collect **50+ real binder page photos**: sleeved, varied lighting, 9-pocket and 4-pocket.
- **Build the catalog seed** (§8.2): import TCGdex EN + JA, cross-check EN against pokemon-tcg-data, and produce a discrepancy report.
- Prototype detection → grid → OCR + embedding match against 3–5 English sets and 2 Japanese sets.
- **Exit criteria:** measure precision and coverage against the §10 targets and decide go/adjust.

### Phase 1: MVP (iOS, Pokémon, English + Japanese, kid accounts)
- Binders (Set / Trade / Collect types), photo intake with ✅/❓ and candidate picker, manual search
- Set tracker and automatic set-gap wish list
- Values (single source, daily cache)
- Swap via QR + nearby (Multipeer), match screen, value balance, record trade
- Accounts (parent/child) + backup sync; Free / Premium / Lifetime plans (StoreKit 2)

### Phase 2
- Permanent profile QR (adult accounts only) + web preview, trade history, proposal/counter flow polish
- Nearby Interaction "bump" proximity, master-set variants, condition-adjusted values

### Phase 3
- Android client (shared backend and protocol)
- Opt-in community model improvement, more games, events and card-show mode

---

## 14. Decisions & Open Questions

### Decided (round 1)
- **Pokémon only**, **English + Japanese**.
- **Kids supported**, via parent-managed accounts (§11).
- **iPhone first**, native Swift. Android later.
- **The owner supplies real binder photos** for Phase 0.
- **Catalog** seeded once from free sources, then updated per new set (§8.2).

### Decided (round 2)
- **Tradeable = binder type:** Set / Trade / Collect binders, with per-card **Keep** in Trade binders (§4.1). Duplicates aren't special.
- **Many binders per user**, limited by plan.
- **Monetization:** free (limited) + subscription + one-time lifetime purchase (§6.1).
- **Recording trades:** included for everyone. Stored trade history is premium.
- **Data budget:** $0 for now.

### Still open
1. **Plan numbers:** binder limits, scan limits and prices in §6.1.
2. **Accounts:** the free tier could work without an account (on-device only) for adults. Kids always need a parent account. OK?
3. **Domain/branding:** is "Binder Swap" clear for App Store and trademark use, and do we own a domain?
4. **Cross-language wishes:** should a wish ever accept "any language"?

---

## 15. Glossary
- **9-pocket page:** standard 3×3 binder sheet. 4-pocket = 2×2, 12-pocket = 3×4 or 4×3.
- **Set mode:** a binder that mirrors one set in collector-number order. Empty slots imply missing cards.
- **Master set:** every card *and* every variant (e.g. reverse holos) in a set.
- **Tradeable:** a collection item the owner is willing to share in swaps.
