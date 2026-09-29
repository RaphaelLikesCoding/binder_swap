// Plan limits and gates (spec §6.2, decided). One subscription, no lifetime.
// The free limit is CARDS, not binders: a collector's binder count reflects how
// they organise, not how much they own, so limiting it prices the wrong thing.

import Foundation

public enum Plan: String, Sendable, CaseIterable {
    case free, premium

    /// Physical cards, duplicates counted. nil is unlimited.
    public var cards: Int? { self == .free ? 200 : nil }
    /// Unlimited on every plan.
    public var binders: Int? { nil }
    /// Values are current or absent; a stale price in a trading app is worse
    /// than none, because someone acts on it.
    public var values: Bool { self == .premium }
    /// Free sees how many cards a set is missing, not which.
    public var setGapDetail: Bool { self == .premium }
    public var trading: Bool { self == .premium }
    public var backup: Bool { self == .premium }
    public var export: Bool { self == .premium }
    public var catalogUpdates: Bool { self == .premium }
    /// Trading is Premium, so Free shows no history. Records are kept, never
    /// deleted, and reappear on resubscribing. nil is unlimited.
    public var tradeHistory: Int? { self == .free ? 0 : nil }
}

/// Physical cards held, duplicates included (spec §6.2).
public func cardCount(_ collection: Collection) -> Int { collection.allItems.count }

public func canAddCard(plan: Plan, cardsHeld: Int) -> Bool {
    guard let limit = plan.cards else { return true }
    return cardsHeld < limit
}

public func canAddBinder(plan: Plan, binderCount: Int) -> Bool {
    guard let limit = plan.binders else { return true }
    return binderCount < limit
}

/// Over the card limit after a downgrade: the collection stays, and stays
/// editable. Only *growing* past the limit is blocked (spec §6.1).
public func canAddPages(plan: Plan, cardsHeld: Int) -> Bool {
    canAddCard(plan: plan, cardsHeld: cardsHeld)
}

/// Newest first.
public func visibleTradeHistory(plan: Plan, history: [TradeRecord]) -> [TradeRecord] {
    let ordered = history.sorted { $0.completedAt > $1.completedAt }
    guard let keep = plan.tradeHistory else { return ordered }
    return Array(ordered.prefix(keep))
}
