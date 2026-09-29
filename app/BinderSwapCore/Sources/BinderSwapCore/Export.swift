// Exporting a wish list (spec §6.7.1, Premium).
//
// Byte-for-byte identical to the Python reference: spec/vectors/wishlist_export.json
// pins the output of both. CSV is for spreadsheets and shopping; text is for
// Messages and Discord, where an attachment cannot be read in the thread.

import Foundation

/// name, set_name and number_label per card id. The rules layer holds no card
/// names, so the caller supplies them.
public typealias CardMeta = [String: [String: String]]

public let wishlistColumns = ["card_id", "name", "set", "number", "priority",
                              "source", "quantity", "owned_elsewhere"]

private func row(_ w: Wish, _ meta: CardMeta) -> [String: String] {
    let m = meta[w.cardID] ?? [:]
    return [
        "card_id": w.cardID,
        "name": m["name"] ?? "",
        "set": m["set_name"] ?? "",
        "number": m["number_label"] ?? "",
        "priority": w.priority,
        "source": w.source,
        "quantity": String(w.quantity),
        "owned_elsewhere": w.ownedElsewhere.joined(separator: ";"),
    ]
}

private func csvCell(_ v: String) -> String {
    guard v.contains(",") || v.contains("\"") || v.contains("\n") else { return v }
    return "\"" + v.replacingOccurrences(of: "\"", with: "\"\"") + "\""
}

public func wishlistCSV(_ wishes: [Wish], meta: CardMeta) -> String {
    var out = [wishlistColumns.joined(separator: ",")]
    for w in wishes {
        let r = row(w, meta)
        out.append(wishlistColumns.map { csvCell(r[$0] ?? "") }.joined(separator: ","))
    }
    return out.joined(separator: "\n") + "\n"
}

public func wishlistText(_ wishes: [Wish], meta: CardMeta, setName: String? = nil) -> String {
    if wishes.isEmpty { return "Nothing missing." }
    let head = setName.map { "\($0) — need \(wishes.count):" } ?? "Need \(wishes.count):"
    var lines = [head]
    for w in wishes {
        let r = row(w, meta)
        let bits = [r["name"] ?? "", r["number"] ?? ""].filter { !$0.isEmpty }
        var line = "  " + (bits.isEmpty ? w.cardID : bits.joined(separator: " "))
        if setName == nil, let s = r["set"], !s.isEmpty { line += " (\(s))" }
        if w.quantity > 1 { line += " x\(w.quantity)" }
        if !w.ownedElsewhere.isEmpty { line += "  [have a copy elsewhere]" }
        lines.append(line)
    }
    return lines.joined(separator: "\n") + "\n"
}
