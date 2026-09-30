import SwiftUI
import BinderSwapCore

/// The first screen exists to prove the seam, not to be the product.
///
/// BinderSwapCore was written and tested before Xcode existed, against the same
/// JSON vectors as the Python reference. This runs those same rules inside a
/// real iOS app, so "the package passes its tests" and "the app can use it" are
/// separately demonstrated rather than assumed to be the same claim.
struct RootView: View {
    private let demo = DemoCollection()

    var body: some View {
        NavigationStack {
            List {
                Section("Rules, running in the app") {
                    LabeledContent("Cards held", value: "\(cardCount(demo.collection))")
                    LabeledContent("Binders", value: "\(demo.collection.binders.count)")
                    LabeledContent("Tradeable", value: "\(demo.tradeables.count)")
                    LabeledContent("Missing from the set", value: "\(demo.missing.count)")
                }

                Section("Missing from \(demo.setName)") {
                    if demo.missing.isEmpty {
                        Text("Nothing missing.").foregroundStyle(.secondary)
                    }
                    ForEach(demo.missing, id: \.cardID) { wish in
                        HStack {
                            Text(wish.cardID).font(.body.monospaced())
                            Spacer()
                            if !wish.ownedElsewhere.isEmpty {
                                Text("have a copy elsewhere")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }

                Section("Plan gates") {
                    ForEach(Plan.allCases, id: \.self) { plan in
                        LabeledContent(plan.rawValue.capitalized) {
                            Text(plan.cards.map { "\($0) cards" } ?? "unlimited")
                        }
                    }
                    LabeledContent("Free can add another card") {
                        Text(canAddCard(plan: .free, cardsHeld: cardCount(demo.collection)) ? "yes" : "no")
                    }
                }
            }
            .navigationTitle("Binder Swap")
        }
    }
}

/// Stand-in data until intake exists. Deliberately mirrors the shape the
/// vectors use, so what is on screen is the same thing CI checks.
struct DemoCollection {
    let setName = "Obsidian Flames"
    let collection: BinderSwapCore.Collection
    let sets: [String: CatalogSet]

    init() {
        let setID = "en/sv03"
        let cards = (1...9).map { ($0, "\(setID)/\($0)") }
        sets = [setID: CatalogSet(id: setID, printedTotal: 9, cards: cards)]
        let setBinder = Binder(
            id: "set", name: setName, type: .set,
            pages: [[Item(cardID: "en/sv03/1"), Item(cardID: "en/sv03/2"), nil,
                     nil, Item(cardID: "en/sv03/5"), Item(cardID: "en/sv03/6"),
                     Item(cardID: "en/sv03/7"), Item(cardID: "en/sv03/8"), Item(cardID: "en/sv03/9")]],
            setID: setID)
        let tradeBinder = Binder(
            id: "trade", name: "Trade", type: .trade,
            pages: [[Item(cardID: "en/sv03/3"), Item(cardID: "en/sv04/12"),
                     Item(cardID: "en/sv04/13", keep: true)]])
        collection = BinderSwapCore.Collection(binders: [setBinder, tradeBinder])
    }

    var missing: [Wish] { wishlist(collection: collection, sets: sets) }
    var tradeables: [Item] { BinderSwapCore.tradeables(collection: collection, sets: sets) }
}
