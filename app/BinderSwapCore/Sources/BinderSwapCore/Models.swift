// The model, mirroring pipeline/binderswap/domain/core.py.
//
// Everything is DERIVED, never stored: flipping a binder's type immediately
// changes what is tradeable and what is wished for, and nothing migrates.

import Foundation

/// Worst to best. Order is the comparison.
public let conditions = ["DMG", "HP", "MP", "LP", "NM"]

public enum BinderType: String, Codable, Sendable, CaseIterable {
    case set, trade, collect
}

public struct Item: Hashable, Codable, Sendable {
    public var cardID: String
    public var variant: String
    public var condition: String
    /// Trade binders only: never offer this copy.
    public var keep: Bool

    public init(cardID: String, variant: String = "normal",
                condition: String = "NM", keep: Bool = false) {
        self.cardID = cardID; self.variant = variant
        self.condition = condition; self.keep = keep
    }

    enum CodingKeys: String, CodingKey {
        case cardID = "card_id", variant, condition, keep
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        cardID = try c.decode(String.self, forKey: .cardID)
        variant = try c.decodeIfPresent(String.self, forKey: .variant) ?? "normal"
        condition = try c.decodeIfPresent(String.self, forKey: .condition) ?? "NM"
        keep = try c.decodeIfPresent(Bool.self, forKey: .keep) ?? false
    }
}

public struct Binder: Codable, Sendable {
    public var id: String
    public var name: String
    public var type: BinderType
    public var rows: Int
    public var cols: Int
    /// Row-major pockets; nil is an empty pocket.
    public var pages: [[Item?]]
    /// Set binders.
    public var setID: String?
    /// Set binders: also want numbers above the printed total.
    public var includeSecrets: Bool

    public init(id: String, name: String, type: BinderType, rows: Int = 3, cols: Int = 3,
                pages: [[Item?]] = [], setID: String? = nil, includeSecrets: Bool = false) {
        self.id = id; self.name = name; self.type = type
        self.rows = rows; self.cols = cols; self.pages = pages
        self.setID = setID; self.includeSecrets = includeSecrets
    }

    public var items: [Item] { pages.flatMap { $0.compactMap { $0 } } }

    enum CodingKeys: String, CodingKey {
        case id, name, type, rows, cols, pages
        case setID = "set_id", includeSecrets = "include_secrets"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        type = try c.decode(BinderType.self, forKey: .type)
        rows = try c.decodeIfPresent(Int.self, forKey: .rows) ?? 3
        cols = try c.decodeIfPresent(Int.self, forKey: .cols) ?? 3
        pages = try c.decodeIfPresent([[Item?]].self, forKey: .pages) ?? []
        setID = try c.decodeIfPresent(String.self, forKey: .setID)
        includeSecrets = try c.decodeIfPresent(Bool.self, forKey: .includeSecrets) ?? false
    }
}

public struct Wish: Hashable, Codable, Sendable {
    public var cardID: String
    /// need | want
    public var priority: String
    /// nil means any variant.
    public var variant: String?
    /// nil means any condition.
    public var minCondition: String?
    public var quantity: Int
    /// manual | set_gap
    public var source: String
    /// set_gap: which set binder.
    public var binderID: String?
    /// set_gap: binders already holding this card.
    public var ownedElsewhere: [String]

    public init(cardID: String, priority: String = "want", variant: String? = nil,
                minCondition: String? = nil, quantity: Int = 1, source: String = "manual",
                binderID: String? = nil, ownedElsewhere: [String] = []) {
        self.cardID = cardID; self.priority = priority; self.variant = variant
        self.minCondition = minCondition; self.quantity = quantity; self.source = source
        self.binderID = binderID; self.ownedElsewhere = ownedElsewhere
    }

    enum CodingKeys: String, CodingKey {
        case cardID = "card_id", priority, variant, quantity, source
        case minCondition = "min_condition", binderID = "binder_id"
        case ownedElsewhere = "owned_elsewhere"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        cardID = try c.decode(String.self, forKey: .cardID)
        priority = try c.decodeIfPresent(String.self, forKey: .priority) ?? "want"
        variant = try c.decodeIfPresent(String.self, forKey: .variant)
        minCondition = try c.decodeIfPresent(String.self, forKey: .minCondition)
        quantity = try c.decodeIfPresent(Int.self, forKey: .quantity) ?? 1
        source = try c.decodeIfPresent(String.self, forKey: .source) ?? "manual"
        binderID = try c.decodeIfPresent(String.self, forKey: .binderID)
        ownedElsewhere = try c.decodeIfPresent([String].self, forKey: .ownedElsewhere) ?? []
    }
}

public struct Collection: Codable, Sendable {
    public var binders: [Binder]
    /// Owned but not filed in a binder, e.g. just received in a trade.
    public var loose: [Item]
    public var manualWishes: [Wish]

    public init(binders: [Binder] = [], loose: [Item] = [], manualWishes: [Wish] = []) {
        self.binders = binders; self.loose = loose; self.manualWishes = manualWishes
    }

    /// (binder id or nil for loose, item)
    public var allItems: [(String?, Item)] {
        binders.flatMap { b in b.items.map { (Optional(b.id), $0) } } + loose.map { (nil, $0) }
    }

    enum CodingKeys: String, CodingKey {
        case binders, loose, manualWishes = "manual_wishes"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        binders = try c.decodeIfPresent([Binder].self, forKey: .binders) ?? []
        loose = try c.decodeIfPresent([Item].self, forKey: .loose) ?? []
        manualWishes = try c.decodeIfPresent([Wish].self, forKey: .manualWishes) ?? []
    }
}

/// What set-gap logic needs: the set's main-numbered cards in order.
public struct CatalogSet: Sendable {
    public var id: String
    public var printedTotal: Int
    /// (number, card_id), main numbering including secrets.
    public var cards: [(Int, String)]

    public init(id: String, printedTotal: Int, cards: [(Int, String)]) {
        self.id = id; self.printedTotal = printedTotal; self.cards = cards
    }
}

public struct Offer: Sendable {
    public var item: Item
    public var priority: String
    public var value: Double?
    public init(item: Item, priority: String, value: Double?) {
        self.item = item; self.priority = priority; self.value = value
    }
}

/// Right card, wrong variant or condition.
public struct NearMiss: Sendable {
    public var cardID: String
    public var offeredVariant: String
    public var offeredCondition: String
    public var wantedVariant: String?
    public var wantedMinCondition: String?
}

public struct Match: Sendable {
    /// Their tradeables I want.
    public var forMe: [Offer]
    /// My tradeables they want.
    public var forThem: [Offer]
    public var nearMisses: [NearMiss]
    public init(forMe: [Offer], forThem: [Offer], nearMisses: [NearMiss] = []) {
        self.forMe = forMe; self.forThem = forThem; self.nearMisses = nearMisses
    }
}

public struct TradeRecord: Sendable {
    public var id: String
    public var completedAt: String
    public var peer: String
    public var gave: [Item]
    public var got: [Item]
    public init(id: String, completedAt: String, peer: String, gave: [Item], got: [Item]) {
        self.id = id; self.completedAt = completedAt; self.peer = peer
        self.gave = gave; self.got = got
    }
}

public struct TradeError: Error, CustomStringConvertible {
    public let description: String
}
