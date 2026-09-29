# app/

The iOS app, and the parts of it that do not need Xcode.

| Path | What it is |
|---|---|
| [`BinderSwapCore/`](BinderSwapCore/) | The collection and trading rules in Swift, as a SwiftPM package |

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
