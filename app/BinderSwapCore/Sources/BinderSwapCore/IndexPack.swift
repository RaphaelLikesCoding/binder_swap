// Reading a .bspk index pack (SPEC §9), written by
// pipeline/binderswap/images/pack.py.
//
// The reference index is a numpy .npz and Swift has no numpy, so the app needs
// a format both sides can read. This one is memory-mapped and used in place:
// no parse step, no 40 MB of objects allocated to search 40 MB of vectors.

import Foundation

public struct IndexPackHeader: Codable, Sendable {
    public let embedder: String
    public let count: Int
    public let dim: Int
    public let dtype: String
    public let idBytes: Int
    enum CodingKeys: String, CodingKey {
        case embedder, count, dim, dtype, idBytes = "id_bytes"
    }
}

public enum IndexPackError: Error, CustomStringConvertible {
    case notAPack, truncated, unsupportedDType(String), embedderMismatch(String, String)
    public var description: String {
        switch self {
        case .notAPack: "not a BSPK index pack"
        case .truncated: "index pack is truncated"
        case .unsupportedDType(let d): "unsupported vector dtype: \(d)"
        case .embedderMismatch(let a, let b):
            "index built by \(a) but the recogniser uses \(b); rebuild the pack"
        }
    }
}

/// A card index, memory-mapped from disk.
public struct IndexPack: Sendable {
    public let header: IndexPackHeader
    public let ids: [String]
    private let data: Data
    private let vectorOffset: Int

    public var count: Int { header.count }
    public var dim: Int { header.dim }
    public var embedderID: String { header.embedder }

    static let magic = Data([0x42, 0x53, 0x50, 0x4B, 0, 0, 0, 1])   // "BSPK\0\0\0\1"

    public init(contentsOf url: URL) throws {
        // Mapped, not read: the vectors are the file, and the OS can page them.
        let data = try Data(contentsOf: url, options: .mappedIfSafe)
        guard data.count > 12, data.prefix(8) == Self.magic else { throw IndexPackError.notAPack }
        let headerLength = Int(data.withUnsafeBytes { raw -> UInt32 in
            var v: UInt32 = 0
            withUnsafeMutableBytes(of: &v) { $0.copyBytes(from: UnsafeRawBufferPointer(rebasing: raw[8..<12])) }
            return UInt32(littleEndian: v)
        })
        guard data.count >= 12 + headerLength else { throw IndexPackError.truncated }
        let header = try JSONDecoder().decode(
            IndexPackHeader.self, from: data.subdata(in: 12..<(12 + headerLength)))
        guard header.dtype == "float16" else { throw IndexPackError.unsupportedDType(header.dtype) }

        let idsOffset = 12 + headerLength
        let idsSize = header.count * header.idBytes
        let vectorSize = header.count * header.dim * 2
        guard data.count >= idsOffset + idsSize + vectorSize else { throw IndexPackError.truncated }

        var ids: [String] = []
        ids.reserveCapacity(header.count)
        for i in 0..<header.count {
            let lo = idsOffset + i * header.idBytes
            var slice = data.subdata(in: lo..<(lo + header.idBytes))
            if let nul = slice.firstIndex(of: 0) { slice = slice.prefix(upTo: nul) }
            ids.append(String(decoding: slice, as: UTF8.self))
        }
        self.header = header
        self.ids = ids
        self.data = data
        self.vectorOffset = idsOffset + idsSize
    }

    /// Row `i` as Float32. Stored as float16 because that is what a phone wants
    /// to hold: 19,724 x 1024 is 40 MB rather than 80.
    public func vector(_ i: Int) -> [Float] {
        precondition(i >= 0 && i < header.count, "row \(i) out of range")
        let start = vectorOffset + i * header.dim * 2
        return data.withUnsafeBytes { raw in
            let base = raw.baseAddress!.advanced(by: start)
            let halves = UnsafeRawBufferPointer(start: base, count: header.dim * 2)
                .bindMemory(to: UInt16.self)
            return (0..<header.dim).map { Float(Float16(bitPattern: halves[$0])) }
        }
    }

    /// Cosine similarity against every row; vectors are stored L2-normalised,
    /// so this is a dot product.
    public func search(_ query: [Float], k: Int = 20) -> [(id: String, score: Float)] {
        precondition(query.count == header.dim, "query has \(query.count) dims, index has \(header.dim)")
        var scored: [(Int, Float)] = []
        scored.reserveCapacity(header.count)
        data.withUnsafeBytes { raw in
            let halves = UnsafeRawBufferPointer(
                start: raw.baseAddress!.advanced(by: vectorOffset),
                count: header.count * header.dim * 2
            ).bindMemory(to: UInt16.self)
            for row in 0..<header.count {
                let off = row * header.dim
                var dot: Float = 0
                for d in 0..<header.dim { dot += Float(Float16(bitPattern: halves[off + d])) * query[d] }
                scored.append((row, dot))
            }
        }
        scored.sort { $0.1 == $1.1 ? ids[$0.0] < ids[$1.0] : $0.1 > $1.1 }
        return scored.prefix(k).map { (ids[$0.0], $0.1) }
    }

    /// The recogniser refuses an index built by a different embedder, because
    /// the scores would be meaningless rather than merely wrong.
    public func requireEmbedder(_ id: String) throws {
        guard header.embedder == id else {
            throw IndexPackError.embedderMismatch(header.embedder, id)
        }
    }
}
