import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFileSync, mkdirSync, readFileSync, rmSync, statSync } from 'node:fs'
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
const policy = JSON.parse(readFileSync(resolve(projectRoot, 'packaging', 'frontend-components.json'), 'utf8'))
if (policy.schema_version !== 1 || policy.status !== 'approved') {
  throw new Error('Frontend component policy is not approved')
}
const sha256 = (path) => createHash('sha256').update(readFileSync(path)).digest('hex')
const lockfile = resolve(frontendRoot, 'pnpm-lock.yaml')
if (sha256(lockfile) !== policy.lockfile_sha256) {
  throw new Error('Frontend lockfile changed without an approved component-policy update')
}
const graphResult = spawnSync(
  'pnpm',
  ['list', '--prod', '--depth', 'Infinity', '--json'],
  { cwd: frontendRoot, encoding: 'utf8', shell: process.platform === 'win32' },
)
if (graphResult.status !== 0) {
  throw new Error(`Unable to read locked frontend production graph: ${graphResult.stderr}`)
}
const graph = JSON.parse(graphResult.stdout)[0]
const discovered = new Map()
const visit = (dependencies = {}) => {
  for (const [name, component] of Object.entries(dependencies)) {
    const key = `${name}@${component.version}`
    discovered.set(key, { name, ...component })
    visit(component.dependencies)
  }
}
visit(graph.dependencies)
const approved = new Map(policy.components.map((component) => [`${component.name}@${component.version}`, component]))
const unapproved = [...discovered.keys()].filter((key) => !approved.has(key)).sort()
const missing = [...approved.keys()].filter((key) => !discovered.has(key)).sort()
if (unapproved.length || missing.length) {
  throw new Error(
    `Frontend production graph differs from approved policy; unapproved=${unapproved.join(',')}; missing=${missing.join(',')}`,
  )
}

const licensesRoot = resolve(outputRoot, 'third-party-licenses', 'frontend')
rmSync(licensesRoot, { recursive: true, force: true })

for (const [key, runtimePackage] of [...discovered.entries()].sort()) {
  const approval = approved.get(key)
  const packageRoot = runtimePackage.path
  const metadata = JSON.parse(readFileSync(resolve(packageRoot, 'package.json'), 'utf8'))
  if (metadata.name !== approval.name || metadata.version !== approval.version || metadata.license !== approval.license) {
    throw new Error(`Frontend package metadata differs from approved policy: ${key}`)
  }
  const tableEntry = `| ${approval.display_name} | ${metadata.version} |`
  if (!notices.includes(tableEntry)) {
    throw new Error(`THIRD_PARTY_NOTICES.md is missing ${key}`)
  }

  const source = resolve(packageRoot, approval.license_file)
  if (sha256(source) !== approval.license_sha256) {
    throw new Error(`Frontend package license hash differs from approved policy: ${key}`)
  }
  const destinationRoot = resolve(licensesRoot, approval.name)
  const destination = resolve(destinationRoot, approval.license_file)
  mkdirSync(destinationRoot, { recursive: true })
  copyFileSync(source, destination)
  if (statSync(destination).size !== statSync(source).size) {
    throw new Error(`License was not copied completely: ${key}`)
  }
}

copyFileSync(
  resolve(projectRoot, 'packaging', 'frontend-components.json'),
  resolve(outputRoot, 'FRONTEND_COMPONENT_POLICY.json'),
)

console.log(
  `Verified ${legalDocuments.length} Geospatial Extraction Studio documents and ${discovered.size} locked frontend package licenses in ${outputRoot}`,
)
