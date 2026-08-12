import { copyFileSync, mkdirSync, readFileSync, realpathSync, rmSync, statSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = resolve(frontendRoot, '..')
const outputRoot = process.argv[2] ? resolve(frontendRoot, process.argv[2]) : resolve(frontendRoot, 'dist')
const legalDocuments = ['LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'CONTENT_PROVENANCE.md', 'ASSET_LICENSES.md']

for (const fileName of legalDocuments) {
  const source = resolve(projectRoot, fileName)
  const destination = resolve(outputRoot, fileName)
  if (statSync(source).size === 0) throw new Error(`Legal source document is empty: ${fileName}`)
  copyFileSync(source, destination)
  if (statSync(destination).size !== statSync(source).size) {
    throw new Error(`Legal document was not copied completely: ${fileName}`)
  }
}

const notices = readFileSync(resolve(projectRoot, 'THIRD_PARTY_NOTICES.md'), 'utf8')
const reactDomRoot = realpathSync(resolve(frontendRoot, 'node_modules', 'react-dom'))
const runtimePackages = [
  { displayName: 'Leaflet', packageName: 'leaflet', root: resolve(frontendRoot, 'node_modules', 'leaflet') },
  { displayName: 'Lucide React / Lucide Icons', packageName: 'lucide-react', root: resolve(frontendRoot, 'node_modules', 'lucide-react') },
  { displayName: 'React', packageName: 'react', root: resolve(frontendRoot, 'node_modules', 'react') },
  { displayName: 'React DOM', packageName: 'react-dom', root: reactDomRoot },
  { displayName: 'Scheduler', packageName: 'scheduler', root: resolve(reactDomRoot, '..', 'scheduler') },
  { displayName: 'three.js', packageName: 'three', root: resolve(frontendRoot, 'node_modules', 'three') },
]

const licensesRoot = resolve(outputRoot, 'third-party-licenses', 'frontend')
rmSync(licensesRoot, { recursive: true, force: true })

for (const runtimePackage of runtimePackages) {
  const packageRoot = realpathSync(runtimePackage.root)
  const metadata = JSON.parse(readFileSync(resolve(packageRoot, 'package.json'), 'utf8'))
  const tableEntry = `| ${runtimePackage.displayName} | ${metadata.version} |`
  if (!notices.includes(tableEntry)) {
    throw new Error(`THIRD_PARTY_NOTICES.md is missing ${runtimePackage.packageName}@${metadata.version}`)
  }

  const source = resolve(packageRoot, 'LICENSE')
  const destinationRoot = resolve(licensesRoot, runtimePackage.packageName)
  const destination = resolve(destinationRoot, 'LICENSE')
  mkdirSync(destinationRoot, { recursive: true })
  copyFileSync(source, destination)
  if (statSync(destination).size !== statSync(source).size) {
    throw new Error(`License was not copied completely: ${runtimePackage.packageName}`)
  }
}

console.log(
  `Verified ${legalDocuments.length} Geospatial Extraction Studio documents and ${runtimePackages.length} frontend package licenses in ${outputRoot}`,
)
