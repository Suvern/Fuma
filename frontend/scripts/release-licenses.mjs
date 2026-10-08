import { readFile, writeFile } from 'node:fs/promises'

const root = new URL('../../', import.meta.url)
const dist = new URL('../dist/', import.meta.url)
const policy = JSON.parse(await readFile(new URL('scripts/license-policy.json', root), 'utf8'))
const packages = JSON.parse(await readFile(new URL('dependency-licenses.json', dist), 'utf8'))
if (!packages.length) throw new Error('The frontend dependency license inventory is empty')
for (const dependency of packages) {
  if (!policy.frontend.includes(dependency.identifier) || !dependency.text?.trim()) {
    throw new Error(`Review license metadata/text for ${dependency.name}@${dependency.version}`)
  }
}
for (const name of ['LICENSE', 'THIRD_PARTY_NOTICES.md']) {
  await writeFile(new URL(name, dist), await readFile(new URL(name, root)))
}
await writeFile(new URL('THIRD_PARTY_LICENSES.txt', dist), packages.map((dependency) =>
  `${dependency.name}@${dependency.version}\nLicense: ${dependency.identifier}\n\n${dependency.text}\n`
).join('\n========================================\n\n'))
console.log(`Included license texts for ${packages.length} bundled dependencies`)
