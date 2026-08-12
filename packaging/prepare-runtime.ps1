param(
    [Parameter(Mandatory = $true)]
    [string]$BuildRoot
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$resolvedBuildRoot = [IO.Path]::GetFullPath($BuildRoot)
$manifestPath = Join-Path $PSScriptRoot 'runtime-components.json'
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json

if ($manifest.schema_version -ne 1 -or $manifest.status -ne 'approved') {
    throw 'Runtime component policy is not approved.'
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-BuildChild {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    $prefix = $resolvedBuildRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw ('Refusing to modify a path outside the build directory: {0}' -f $resolved)
    }
    return $resolved
}

$cacheRoot = Assert-BuildChild (Join-Path $resolvedBuildRoot 'runtime-cache')
$runtimeRoot = Assert-BuildChild (Join-Path $resolvedBuildRoot ('runtime-' + $manifest.release))
$venvRoot = Assert-BuildChild (Join-Path $resolvedBuildRoot ('release-venv-' + $manifest.release))
New-Item -ItemType Directory -Force -Path $cacheRoot | Out-Null

$archivePath = Join-Path $cacheRoot $manifest.archive.file_name
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    Invoke-WebRequest -Uri $manifest.archive.url -OutFile $archivePath -UseBasicParsing
}
if ((Get-Sha256 $archivePath) -ne $manifest.archive.sha256) {
    throw ('Pinned runtime archive hash mismatch: {0}' -f $archivePath)
}

$licensePath = Join-Path $cacheRoot $manifest.combined_license.file_name
if (-not (Test-Path -LiteralPath $licensePath -PathType Leaf)) {
    Invoke-WebRequest -Uri $manifest.combined_license.url -OutFile $licensePath -UseBasicParsing
}
if ((Get-Sha256 $licensePath) -ne $manifest.combined_license.sha256) {
    throw ('Pinned runtime license hash mismatch: {0}' -f $licensePath)
}

$markerPath = Join-Path $runtimeRoot 'VERIFIED-ARCHIVE-SHA256.txt'
if (Test-Path -LiteralPath $runtimeRoot) {
    Remove-Item -LiteralPath (Assert-BuildChild $runtimeRoot) -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
& tar -xf $archivePath -C $runtimeRoot
if ($LASTEXITCODE -ne 0) { throw 'Pinned runtime extraction failed.' }
[IO.File]::WriteAllText(
    $markerPath,
    $manifest.archive.sha256 + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false)
)

$basePython = Join-Path $runtimeRoot 'python\python.exe'
foreach ($entry in $manifest.critical_files) {
    $path = Join-Path (Join-Path $runtimeRoot 'python') $entry.path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw ('Pinned runtime file is missing: {0}' -f $entry.path)
    }
    if ((Get-Sha256 $path) -ne $entry.sha256) {
        throw ('Pinned runtime file hash mismatch: {0}' -f $entry.path)
    }
}

$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    if (Test-Path -LiteralPath $venvRoot) {
        Remove-Item -LiteralPath (Assert-BuildChild $venvRoot) -Recurse -Force
    }
    & $basePython -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) { throw 'Pinned release virtual environment creation failed.' }
}

$actualBase = (& $venvPython -c 'import sys; print(sys.base_prefix)').Trim()
$expectedBase = [IO.Path]::GetFullPath((Join-Path $runtimeRoot 'python'))
if (-not $actualBase.Equals($expectedBase, [StringComparison]::OrdinalIgnoreCase)) {
    throw ('Release virtual environment uses an unapproved base runtime: {0}' -f $actualBase)
}

Write-Output $venvPython
