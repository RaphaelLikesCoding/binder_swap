// Wishes, tradeables, matching and trades. Mirrors
// pipeline/binderswap/domain/core.py; both run spec/vectors/*.json.
//
// Ordering is part of the contract, not an implementation detail: the vectors
// pin the exact sequence of offers, so the sorts here must match the Python
// ones key for key.

import Foundation

// MARK: - wishes

/// Every card of the set not in this Set binder is a Need (spec §4.1).
public func setGaps(binder: Binder, set cset: CatalogSet, collection: Collection) -> [Wish] {
    guard binder.type == .set else { return [] }
    let have = Set(binder.items.map(\.cardID))
    var where_: [String: Set<String>] = [:]
    for (bid, it) in collection.allItems where bid != binder.id {
        where_[it.cardID, default: []].insert(bid ?? "loose")
    }
    var out: [Wish] = []
    for (number, cid) in cset.cards {
        if number > cset.printedTotal && !binder.includeSecrets { continue }
        if have.contains(cid) { continue }
        out.append(Wish(cardID: cid, priority: "need", source: "set_gap",
                        binderID: binder.id,
                        ownedElsewhere: (where_[cid] ?? []).sorted()))
    }
    return out
}

func ownedCount(_ collection: Collection, _ wish: Wish) -> Int {
    collection.allItems.filter { _, it in
        it.cardID == wish.cardID
            && (wish.variant == nil || it.variant == wish.variant)
            && conditionOK(it.condition, wish.minCondition)
    }.count
}

/// Open wishes: unfulfilled manual wishes plus Set-binder gaps.
/// A manual wish is fulfilled once enough matching copies are owned anywhere.
public func wishlist(collection: Collection, sets: [String: CatalogSet]) -> [Wish] {
    var out = collection.manualWishes.filter { ownedCount(collection, $0) < $0.quantity }
    for b in collection.binders {
        if b.type == .set, let sid = b.setID, let cset = sets[sid] {
            out.append(contentsOf: setGaps(binder: b, set: cset, collection: collection))
        }
    }
    return out
}

// MARK: - tradeables

/// Copies in Trade binders not marked Keep, and never a card the owner
/// currently needs: you cannot give away the card your own set is missing.
public func tradeables(collection: Collection, sets: [String: CatalogSet]) -> [Item] {
    let needed = Set(wishlist(collection: collection, sets: sets)
        .filter { $0.priority == "need" }.map(\.cardID))
    return collection.binders.filter { $0.type == .trade }
        .flatMap(\.items)
        .filter { !$0.keep && !needed.contains($0.cardID) }
}

/// What a phone shares in a swap (spec §7.3): tradeables and wants only.
public func profile(collection: Collection, sets: [String: CatalogSet]) -> (tradeables: [Item], wants: [Wish]) {
    (tradeables(collection: collection, sets: sets), wishlist(collection: collection, sets: sets))
}

// MARK: - matching

func conditionOK(_ condition: String, _ minimum: String?) -> Bool {
    guard let minimum else { return true }
    guard let c = conditions.firstIndex(of: condition),
          let m = conditions.firstIndex(of: minimum) else { return false }
    return c >= m
}

func value(_ item: Item, _ prices: [String: Double]) -> Double? {
    prices["\(item.cardID)|\(item.variant)"] ?? prices[item.cardID]
}

/// Match one side's tradeables against the other side's wants, copy by copy.
func offers(tradeable: [Item], wants: [Wish], prices: [String: Double]) -> ([Offer], [NearMiss]) {
    var remaining = wants.map(\.quantity)
    var byCard: [String: [Int]] = [:]
    for (i, w) in wants.enumerated() { byCard[w.cardID, default: []].append(i) }
    // Needs first, so a scarce copy goes to the most important wish. Stable, to
    // match Python's list.sort on a single boolean key.
    for (cid, idxs) in byCard {
        byCard[cid] = idxs.enumerated()
            .sorted { a, b in
                let an = wants[a.element].priority != "need", bn = wants[b.element].priority != "need"
                return an == bn ? a.offset < b.offset : (!an && bn)
            }
            .map(\.element)
    }
    var out: [Offer] = []
    var near: [NearMiss] = []
    for item in tradeable {
        var hit: Int?
        var miss: NearMiss?
        for i in byCard[item.cardID] ?? [] {
            if remaining[i] <= 0 { continue }
            let w = wants[i]
            let variantOK = w.variant == nil || w.variant == item.variant
            if variantOK && conditionOK(item.condition, w.minCondition) { hit = i; break }
            if miss == nil {
                miss = NearMiss(cardID: item.cardID, offeredVariant: item.variant,
                                offeredCondition: item.condition,
                                wantedVariant: w.variant, wantedMinCondition: w.minCondition)
            }
        }
        if let i = hit {
            remaining[i] -= 1
            out.append(Offer(item: item, priority: wants[i].priority, value: value(item, prices)))
        } else if let miss { near.append(miss) }
    }
    out.sort { a, b in
        let an = a.priority != "need", bn = b.priority != "need"
        if an != bn { return !an }
        let av = -(a.value ?? 0), bv = -(b.value ?? 0)
        if av != bv { return av < bv }
        return a.item.cardID < b.item.cardID
    }
    return (out, near)
}

public func match(mine: (tradeables: [Item], wants: [Wish]),
                  theirs: (tradeables: [Item], wants: [Wish]),
                  prices: [String: Double] = [:]) -> Match {
    let (forMe, nearMe) = offers(tradeable: theirs.tradeables, wants: mine.wants, prices: prices)
    let (forThem, nearThem) = offers(tradeable: mine.tradeables, wants: theirs.wants, prices: prices)
    return Match(forMe: forMe, forThem: forThem, nearMisses: nearMe + nearThem)
}

/// Pick a subset of both sides whose values are within `tolerance`.
///
/// Deterministic greedy: start from everything; while the heavier side exceeds
/// the lighter by more than the tolerance, drop the heavier side's item that
/// best closes the gap, preferring Wants over Needs. Items without a price
/// count as 0 and are kept -- the users can discuss them.
public func suggestFairTrade(_ m: Match, tolerance: Double = 0.10) -> (get: [Offer], give: [Offer]) {
    var get = m.forMe, give = m.forThem
    if get.isEmpty || give.isEmpty { return (get, give) }
    func total(_ xs: [Offer]) -> Double { xs.reduce(0) { $0 + ($1.value ?? 0) } }
    while true {
        let a = total(get), b = total(give)
        let diff = abs(a - b)
        if diff <= tolerance * max(a, b) || max(a, b) == 0 { break }
        let heavyIsGet = a > b
        var heavy = heavyIsGet ? get : give
        if heavy.count == 1 { break }
        var best: (key: (Bool, Double, String), index: Int)?
        for (i, o) in heavy.enumerated() {
            guard let v = o.value, v != 0 else { continue }
            let newDiff = abs(diff - v)
            guard newDiff < diff else { continue }
            let key = (o.priority == "need", newDiff, o.item.cardID)
            if best == nil || lessThan(key, best!.key) { best = (key, i) }
        }
        guard let best else { break }
        heavy.remove(at: best.index)
        if heavyIsGet { get = heavy } else { give = heavy }
    }
    return (get, give)
}

private func lessThan(_ a: (Bool, Double, String), _ b: (Bool, Double, String)) -> Bool {
    if a.0 != b.0 { return !a.0 }          // false < true, as in Python
    if a.1 != b.1 { return a.1 < b.1 }
    return a.2 < b.2
}

// MARK: - recording trades

/// Update inventory after both sides accept (spec §6.1).
///
/// Given copies leave Trade binders first, so their pocket becomes empty;
/// received cards land in `loose` for the user to file. Throws if a given copy
/// is not tradeable, so a stale swap cannot remove a kept or needed card.
public func applyTrade(_ collection: Collection, gave: [Item], got: [Item]) throws -> Collection {
    var col = collection
    for item in gave {
        var placed = false
        outer: for bi in col.binders.indices where col.binders[bi].type == .trade {
            for pi in col.binders[bi].pages.indices {
                for si in col.binders[bi].pages[pi].indices {
                    if let slot = col.binders[bi].pages[pi][si], slot == item, !slot.keep {
                        col.binders[bi].pages[pi][si] = nil
                        placed = true
                        break outer
                    }
                }
            }
        }
        if !placed { throw TradeError(description: "not tradeable: \(item.cardID)") }
    }
    col.loose.append(contentsOf: got)
    return col
}
