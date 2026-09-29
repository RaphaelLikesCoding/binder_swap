// The .bspk pack is written by Python and read by Swift, so it is a contract
// between two languages. These check Swift against values Python produced --
// not against Swift's own idea of what it wrote, which would pass even if both
// sides were wrong in the same way.

import Foundation
import Testing
@testable import BinderSwapCore

private let packsDir = vectorsDir.appendingPathComponent("packs")

private func expected() throws -> [String: Any] {
    let d = try Data(contentsOf: packsDir.appendingPathComponent("fixture.json"))
    return try JSONSerialization.jsonObject(with: d) as! [String: Any]
}

@Test func readsTheHeaderPythonWrote() throws {
    let pack = try IndexPack(contentsOf: packsDir.appendingPathComponent("fixture.bspk"))
    let want = try expected()["header"] as! [String: Any]
    #expect(pack.embedderID == want["embedder"] as! String)
    #expect(pack.count == want["count"] as! Int)
    #expect(pack.dim == want["dim"] as! Int)
    #expect(pack.header.idBytes == want["id_bytes"] as! Int)
}

@Test func readsTheIdsInOrderAndUnpadded() throws {
    let pack = try IndexPack(contentsOf: packsDir.appendingPathComponent("fixture.bspk"))
    let wantIDs = try expected()["ids"] as! [String]
    #expect(pack.ids == wantIDs)
    // Ids are NUL-padded to a fixed width on disk; none of that may survive.
    for id in pack.ids { #expect(!id.contains("\0")) }
}

@Test func readsTheSameFloatsPythonStored() throws {
    let pack = try IndexPack(contentsOf: packsDir.appendingPathComponent("fixture.bspk"))
    let want = (try expected()["row2"] as! [Double]).map(Float.init)
    let got = pack.vector(2)
    #expect(got.count == want.count)
    for (g, w) in zip(got, want) {
        #expect(abs(g - w) < 1e-4, "float16 round trip differs: \(g) vs \(w)")
    }
}

@Test func searchAgreesWithPythonOnOrderAndScores() throws {
    let pack = try IndexPack(contentsOf: packsDir.appendingPathComponent("fixture.bspk"))
    let want = try expected()["search"] as! [[Any]]
    let got = pack.search(pack.vector(2), k: 5)
    #expect(got.count == want.count)
    for (g, w) in zip(got, want) {
        #expect(g.id == w[0] as! String, "order differs")
        #expect(abs(g.score - Float((w[1] as! NSNumber).doubleValue)) < 1e-3,
                "score for \(g.id): \(g.score) vs \(w[1])")
    }
    // A card is its own nearest neighbour at cosine 1.
    #expect(got[0].id == pack.ids[2])
    #expect(abs(got[0].score - 1.0) < 1e-3)
}

@Test func refusesAPackFromADifferentEmbedder() throws {
    let pack = try IndexPack(contentsOf: packsDir.appendingPathComponent("fixture.bspk"))
    #expect(throws: Never.self) { try pack.requireEmbedder("classic-v1") }
    #expect(throws: IndexPackError.self) { try pack.requireEmbedder("some-other-model") }
}

@Test func rejectsAFileThatIsNotAPack() throws {
    let tmp = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("not-a-pack.bspk")
    try Data("hello".utf8).write(to: tmp)
    defer { try? FileManager.default.removeItem(at: tmp) }
    #expect(throws: IndexPackError.self) { try IndexPack(contentsOf: tmp) }
}
