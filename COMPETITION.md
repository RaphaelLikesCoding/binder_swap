# Competitive landscape

Researched 2026-09-30. Every claim here is from a store listing, a vendor page
or the iTunes Lookup API; anything that could not be confirmed is marked
**unverified** rather than guessed. Ratings counts are approximate (Apple rounds
them).

## The two findings that matter

**1. "Binder Swap" is taken, by almost exactly this product.**
[iOS `id6762248004`](https://apps.apple.com/us/app/binder-swap/id6762248004),
Luis Murillo, launched 15 Aug 2026. Also on Google Play, plus `binderswap.com`
and `@binder_swap`. Its pitch: find collectors near you who have the cards you
want, meet and trade in person, no shipping, no fees. Digital binders, want
lists, local match alerts, in-app DM, LGS store locator. Monetised **by search
radius** — free 15 miles, $2.99/mo 30 miles, $6.99/mo 50 miles — plus store
plans at $79.99–$149.99/mo.

It has **zero ratings after six weeks**. The name is gone; the market is not.

**2. Whole-page scanning is not novel. It already ships.**
- **[PokeLenz](https://apps.apple.com/us/app/pokelenz-tcg-scanner/id6747037909)**
  (4.8★, ~179 ratings) scans a full 9-card page in one shot *through sleeves*,
  auto-splits it, tracks set completion and missing cards, and **supports
  Japanese** (added v2.4.0). Free tier is **15 scans/day**. Elite $3.99/mo,
  Champion $7.99/mo.
- **[Ripdex](https://apps.apple.com/us/app/ripdex-tcg-card-scanner/id6742319104)**
  (4.7★, ~328 ratings) — batch page scanning EN+JP is *reported by a comparison
  site*, **unverified** from the vendor's own listing.

Neither does peer-to-peer trading.

## The field

| App | Ratings | Page capture | P2P trade | Japanese | Price |
|---|---|---|---|---|---|
| Collectr | ~66,400 ★4.9 | no | marketplace/social | unverified | $7.99/mo, $59.99/yr |
| CollX | ~48,800 ★4.6 | no | marketplace | unverified | $9.99/mo, $99.99/yr |
| Ludex | ~27,700 ★4.7 | no | no | unverified | $4.99–$24.99/mo |
| TCGplayer | ~15,600 ★4.2 | no | marketplace | — | free |
| **Dex** | ~13,800 ★4.8 | no | friend graph | **yes**, EN+JA+zh | $3.99/mo, **Lifetime $109** |
| Pokellector | ~3,773 ★4.7 | no | no | yes | stale (last update Oct 2024) |
| **Ripdex** | ~328 ★4.7 | reported | no | yes | free + subs |
| **PokeLenz** | ~179 ★4.8 | **yes** | no | **yes** | free 15/day + subs |
| DeckTradr | ~603 ★4.9 | — | yes | — | — |
| SuperSwap | **4** ★5.0 | no | yes, local | — | — |
| **Binder Swap** | **0** | unverified | yes, local | unverified | radius tiers |

## What this means for us

**The gap is the combination, not either half.** Nobody found does whole-page
capture *and* geo-matched in-person trading. Page capture as the on-ramp that
feeds a trade graph is unoccupied — but it is a bet that the two halves make
each other more valuable, which is unproven.

**Cold-start is the unsolved problem in this category, and it is ours too.**
Binder Swap: 0 ratings. SuperSwap: 4. Both shipped, both stalled. A trade
network is worth nothing without local density. Meanwhile Collectr (66k) and
CollX (49k) thrive on *single-user* collection tracking, which needs nobody
else. **The set tracker has to be worth having alone**, with trading as upside —
which is what §6.2's free/paid split already assumes, and this is evidence for
it rather than against.

**Two things we can claim that nobody else does.**
1. **A measured accuracy number.** Not one competitor publishes one. Ludex says
   "the most accurate trading card scanner in the hobby" with nothing behind it.
   We have `scalecheck`, `ocrcheck`, `realpages` and pre-registered bars (§5.4).
   A published per-card figure on 9-up segmentation, with its n and its method,
   would be genuinely novel — and it is hard to fake.
2. **Japanese in a trading app.** Every trading app found is absent or
   unverified on Japanese; PokeLenz, Ripdex and Dex prove the demand exists on
   the tracking side. This is why BLOCKERS #5 is worth money rather than being
   tidy-up.

**Where we are behind:** database breadth (CollX 20M cards, Collectr 200k+
products), price-data relationships, and trust mass. We are at zero.

**Pricing worth noting.** PokeLenz gives **15 scans/day free**, far more
generous than our 200-card cap (§6.2) — a free user there can digitise a binder
a week forever. Dex sells a **$109 lifetime** we have ruled out. Binder Swap
gates on **search radius**, a lever we had not considered and which fits a
local-trade product better than a volume cap.

## Unverified, on purpose

Whether Binder Swap does whole-page capture, supports Japanese, or tracks set
completion. Ripdex's page batch scanning. Japanese support for Collectr, CollX,
Ludex, TCGplayer, Binder Swap, SuperSwap. Any app named "Binder Finder TCG" —
no such app was found on either store.
