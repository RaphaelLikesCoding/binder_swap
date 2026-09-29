// The shared JSON vectors in spec/vectors, run against the Swift rules.
//
// The Python reference in pipeline/binderswap/domain/core.py runs these same
// files. That is the point: two independent implementations of the trading
// rules, pinned to one set of expectations, so a divergence is a test failure
// rather than a support ticket about someone's inventory being wrong.

import Foundation
import Testing
@testable import BinderSwapCore

// spec/vectors lives four levels up from this file.
let vectorsDir = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent()   // BinderSwapCoreTests
    .deletingLastPathComponent()   // Tests
    .deletingLastPathComponent()   // BinderSwapCore
    .deletingLastPathComponent()   // app
    .deletingLastPathComponent()   // repo root
    .appendingPathComponent("spec/vectors")

func loadVector(_ name: String) throws -> [String: Any] {
    let data = try Data(contentsOf: vectorsDir.appendingPathComponent(name))
    return try JSONSerialization.jsonObject(with: data) as! [String: Any]
}

func decode<T: Decodable>(_ type: T.Type, _ any: Any) throws -> T {
    try JSONDecoder().decode(T.self, from: JSONSerialization.data(withJSONObject: any))
}

func catalogSets(_ any: Any?) throws -> [String: CatalogSet] {
    guard let d = any as? [String: [String: Any]] else { return [:] }
    var out: [String: CatalogSet] = [:]
    for (k, v) in d {
        let cards = (v["cards"] as! [[Any]]).map { ($0[0] as! Int, $0[1] as! String) }
        out[k] = CatalogSet(id: k, printedTotal: v["printed_total"] as! Int, cards: cards)
    }
    return out
}

@Test func vectorsDirectoryIsWhereWeThinkItIs() throws {
    #expect(FileManager.default.fileExists(atPath: vectorsDir.path),
            "spec/vectors not found at \(vectorsDir.path)")
}

@Test func tradeablesVectors() throws {
    let v = try loadVector("tradeables.json")
    let sets = try catalogSets(v["sets"])
    for c in v["cases"] as! [[String: Any]] {
        let col: Collection = try decode(Collection.self, c["collection"]!)
        let got = tradeables(collection: col, sets: sets).map(\.cardID).sorted()
        #expect(got == c["expected"] as! [String], "\(c["name"]!)")
    }
}

@Test func wishlistVectors() throws {
    let v = try loadVector("wishlist.json")
    let sets = try catalogSets(v["sets"])
    for c in v["cases"] as! [[String: Any]] {
        let col: Collection = try decode(Collection.self, c["collection"]!)
        let wishes = wishlist(collection: col, sets: sets)
        let got = wishes.map { [$0.cardID, $0.priority, $0.source] }
            .sorted { $0.lexicographicallyPrecedes($1) }
        let want = (c["expected"] as! [[String]]).sorted { $0.lexicographicallyPrecedes($1) }
        #expect(got == want, "\(c["name"]!)")
        for (cid, where_) in (c["expected_owned_elsewhere"] as? [String: [String]] ?? [:]) {
            let w = wishes.first { $0.cardID == cid }
            #expect(w?.ownedElsewhere == where_, "\(c["name"]!) owned_elsewhere for \(cid)")
        }
    }
}

@Test func matchVectors() throws {
    let v = try loadVector("match.json")
    for c in v["cases"] as! [[String: Any]] {
        func side(_ any: Any) throws -> (tradeables: [Item], wants: [Wish]) {
            let d = any as! [String: Any]
            return (try decode([Item].self, d["tradeables"]!), try decode([Wish].self, d["wants"]!))
        }
        let prices = (c["prices"] as? [String: Double]) ?? [:]
        let m = match(mine: try side(c["mine"]!), theirs: try side(c["theirs"]!), prices: prices)
        let forMe = m.forMe.map { [$0.item.cardID, $0.item.variant, $0.priority] }
        let forThem = m.forThem.map { [$0.item.cardID, $0.item.variant, $0.priority] }
        #expect(forMe == c["expected_for_me"] as! [[String]], "\(c["name"]!) for_me")
        #expect(forThem == c["expected_for_them"] as! [[String]], "\(c["name"]!) for_them")
        #expect(m.nearMisses.count == c["expected_near_misses"] as! Int, "\(c["name"]!) near misses")
    }
}

@Test func fairTradeVectors() throws {
    let v = try loadVector("fair_trade.json")
    for c in v["cases"] as! [[String: Any]] {
        func side(_ rows: Any) -> [Offer] {
            (rows as! [[Any]]).map {
                Offer(item: Item(cardID: $0[0] as! String), priority: $0[1] as! String,
                      value: ($0[2] as? NSNumber)?.doubleValue)
            }
        }
        let (get, give) = suggestFairTrade(Match(forMe: side(c["for_me"]!), forThem: side(c["for_them"]!)))
        #expect(get.map(\.item.cardID) == c["expected_get"] as! [String], "\(c["name"]!) get")
        #expect(give.map(\.item.cardID) == c["expected_give"] as! [String], "\(c["name"]!) give")
    }
}

@Test func applyTradeVectors() throws {
    let v = try loadVector("apply_trade.json")
    for c in v["cases"] as! [[String: Any]] {
        let col: Collection = try decode(Collection.self, c["collection"]!)
        let gave: [Item] = try decode([Item].self, c["gave"]!)
        let got: [Item] = try decode([Item].self, c["got"]!)
        if (c["expected_error"] as? Bool) == true {
            #expect(throws: TradeError.self, "\(c["name"]!)") { try applyTrade(col, gave: gave, got: got) }
            continue
        }
        let after = try applyTrade(col, gave: gave, got: got)
        for (bid, pages) in (c["expected_pages"] as! [String: Any]) {
            let b = after.binders.first { $0.id == bid }!
            let want: [[Item?]] = try decode([[Item?]].self, pages)
            #expect(b.pages == want, "\(c["name"]!) pages for \(bid)")
        }
        #expect(after.loose == (try decode([Item].self, c["expected_loose"]!)), "\(c["name"]!) loose")
        // The input collection is a value type and must not have been touched.
        #expect(col.binders[0].pages != after.binders[0].pages, "\(c["name"]!) input mutated")
    }
}

@Test func planVectors() throws {
    let v = try loadVector("plans.json")
    for c in v["card_limits"] as! [[String: Any]] {
        let p = Plan(rawValue: c["plan"] as! String)!
        #expect(canAddCard(plan: p, cardsHeld: c["cards_held"] as! Int) == c["can_add"] as! Bool, "\(c)")
    }
    for c in v["binder_limits"] as! [[String: Any]] {
        let p = Plan(rawValue: c["plan"] as! String)!
        #expect(canAddBinder(plan: p, binderCount: c["binders"] as! Int) == c["can_add"] as! Bool, "\(c)")
    }
    for c in v["downgrade"] as! [[String: Any]] {
        let p = Plan(rawValue: c["plan"] as! String)!
        #expect(canAddPages(plan: p, cardsHeld: c["cards_held"] as! Int) == c["can_add_pages"] as! Bool, "\(c)")
    }
    for c in v["trade_history"] as! [[String: Any]] {
        let p = Plan(rawValue: c["plan"] as! String)!
        let recs = (c["records"] as! [String]).map {
            TradeRecord(id: $0, completedAt: $0, peer: "peer", gave: [], got: [])
        }
        #expect(visibleTradeHistory(plan: p, history: recs).map(\.completedAt) == c["visible"] as! [String], "\(c)")
    }
    for c in v["gates"] as! [[String: Any]] {
        let p = Plan(rawValue: c["plan"] as! String)!
        #expect(p.values == c["values"] as! Bool)
        #expect(p.setGapDetail == c["set_gap_detail"] as! Bool)
        #expect(p.trading == c["trading"] as! Bool)
        #expect(p.backup == c["backup"] as! Bool)
        #expect(p.export == c["export"] as! Bool)
        #expect(p.catalogUpdates == c["catalog_updates"] as! Bool)
    }
}

@Test func wishlistExportVectors() throws {
    let v = try loadVector("wishlist_export.json")
    let meta = v["meta"] as! CardMeta
    for c in v["cases"] as! [[String: Any]] {
        let wishes: [Wish] = try decode([Wish].self, c["wishes"]!)
        let got = (c["format"] as! String) == "csv"
            ? wishlistCSV(wishes, meta: meta)
            : wishlistText(wishes, meta: meta, setName: c["set_name"] as? String)
        #expect(got == c["expected"] as! String, "\(c["name"]!)\n--- got ---\n\(got)")
    }
}
