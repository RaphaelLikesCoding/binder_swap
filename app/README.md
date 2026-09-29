# app/

The iOS app, and the parts of it that do not need Xcode.

| Path | What it is |
|---|---|
| [`BinderSwapCore/`](BinderSwapCore/) | The collection and trading rules, and the index-pack reader, in Swift as a SwiftPM package |

## BinderSwapCore

Every rule that decides what is tradeable, what is missing from a set, what two
collectors can swap and what a plan allows — with no UIKit, no SwiftUI and no
iOS SDK. That is deliberate: it builds and tests with the Swift toolchain
alone, so it could be written before Xcode was installed, and it is the part of
the app whose correctness matters most. A recognition miss costs a swipe; a
trading-rule bug silently corrupts someone's inventory.

```bash
cd app/BinderSwapCore
swift build
swift test          # runs ../../spec/vectors/*.json
```

**It passes the same JSON vectors as the Python reference** in
`pipeline/binderswap/domain/core.py`. Two independent implementations pinned to
one set of expectations: a divergence is a test failure rather than a support
ticket. When the app exists, it takes this as a package dependency.

Verified by sabotage, not just by passing: dropping the `keep` flag from
tradeables and inverting the needs-before-wants ordering each fail the vector
that covers them.

### IndexPack

`IndexPack` reads a `.bspk` card index — memory-mapped and searched in place,
so finding a card among 19,724 does not allocate 40 MB of objects first. Packs
are written by `binderswap.images.pack` on the Python side.

The format exists because the build index is a numpy `.npz` and Swift has no
numpy. A format only one language can read is a contract waiting to break, so
both sides are checked against the *same* committed fixture in
`spec/vectors/packs/` — Swift against values Python produced, not against its
own idea of what it wrote.
