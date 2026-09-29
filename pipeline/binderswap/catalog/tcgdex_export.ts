// Exports raw card records from a checkout of github.com/tcgdex/cards-database.
//
// Usage: bun run tcgdex_export.ts <cards-database dir> <out.ndjson> [langs=en,ja]
//
// The TCGdex source files are TypeScript modules (one per card, set and serie),
// so the simplest faithful reader is to import them. Each output line is one
// (card, language) pair; normalization and validation happen in Python.

import { readdirSync, statSync, writeFileSync } from 'node:fs'
import { join, relative, basename } from 'node:path'

const [root, outPath, langArg] = process.argv.slice(2)
if (!root || !outPath) {
	console.error('usage: bun run tcgdex_export.ts <cards-database dir> <out.ndjson> [langs]')
	process.exit(2)
}
const langs = (langArg ?? 'en,ja').split(',')

// Pokémon TCG Pocket is a digital-only game; its "cards" are never in binders.
const EXCLUDED_SERIES = new Set(['tcgp'])

function* walk(dir: string): Generator<string> {
	for (const name of readdirSync(dir).sort()) {
		const p = join(dir, name)
		if (statSync(p).isDirectory()) yield* walk(p)
		else if (name.endsWith('.ts')) yield p
	}
}

function pick(obj: any, keys: string[]) {
	const out: any = {}
	for (const k of keys) if (obj?.[k] !== undefined) out[k] = obj[k]
	return out
}

const lines: string[] = []
let failures = 0
for (const folder of ['data', 'data-asia']) {
	const base = join(root, folder)
	for (const file of walk(base)) {
		// Card files live three levels down: <folder>/<serie>/<set>/<localId>.ts
		const rel = relative(base, file).split('/')
		if (rel.length !== 3) continue
		let card: any
		try {
			card = (await import(file)).default
		} catch (e) {
			failures++
			console.error(`import failed: ${file}: ${e}`)
			continue
		}
		if (!card?.set?.serie) continue
		const set = card.set
		const serie = set.serie
		if (EXCLUDED_SERIES.has(serie.id)) continue
		for (const lang of langs) {
			if (!card.name?.[lang]) continue
			lines.push(JSON.stringify({
				source: { repo: 'tcgdex/cards-database', path: `${folder}/${rel.join('/')}` },
				lang,
				localId: basename(file, '.ts'),
				serie: { id: serie.id, name: serie.name },
				set: pick(set, ['id', 'name', 'cardCount', 'releaseDate', 'abbreviations', 'thirdParty', 'tcgOnline']),
				card: pick(card, [
					'name', 'rarity', 'category', 'hp', 'types', 'stage', 'suffix', 'illustrator',
					'regulationMark', 'dexId', 'variants', 'thirdParty', 'trainerType', 'energyType',
				]),
			}))
		}
	}
}
writeFileSync(outPath, lines.join('\n') + '\n')
console.error(`exported ${lines.length} card-language records (${failures} import failures)`)
