param(
    [string]$Destination = (Join-Path $PSScriptRoot '..\Geospatial-Extraction-Studio-source-0.4.0.zip')
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$destinationPath = [IO.Path]::GetFullPath($Destination)

$revisionOutput = & git -C $projectRoot rev-parse --verify HEAD
if ($LASTEXITCODE -ne 0) {
    throw 'A committed Git revision is required before creating a source release.'
}
$sourceRevision = ($revisionOutput | Select-Object -First 1).Trim()
$workingState = @(& git -C $projectRoot status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw 'Could not inspect the Git working tree.'
}
if ($workingState.Count -gt 0) {
    throw 'Refusing to package a dirty working tree; commit or remove source changes first.'
}
$releaseTags = @(& git -C $projectRoot tag --points-at $sourceRevision)
if ($LASTEXITCODE -ne 0) {
    throw 'Could not inspect release tags for the source revision.'
}
$releaseTag = ($releaseTags | Where-Object { $_ -eq 'v0.4.0' } | Select-Object -First 1)
if (-not $releaseTag) { $releaseTag = 'none' }

if ([IO.Path]::GetExtension($destinationPath) -ne '.zip') {
    throw 'The source release destination must use the .zip extension.'
}
if (Test-Path -LiteralPath $destinationPath) {
    throw "Refusing to overwrite an existing release archive: $destinationPath"
}

$stagingRoot = Join-Path ([IO.Path]::GetTempPath()) ("geospatial-extraction-studio-source-" + [guid]::NewGuid().ToString('N'))
$stagingProject = Join-Path $stagingRoot 'Geospatial-Extraction-Studio'

function Test-ReleaseFile {
    param([string]$RelativePath)

    $path = $RelativePath.Replace('\', '/')
    if ($path -match '(^|/)(\.git|\.agents|\.codex|\.pytest_cache|__pycache__)(/|$)') { return $false }
    if ($path -match '^\.pnpm-store(/|$)') { return $false }
    if ($path -match '^backend/\.venv(/|$)') { return $false }
    if ($path -match '^frontend/(node_modules|dist|\.pnpm-store|\.pnpm-cache)(/|$)') { return $false }
    if ($path -match '(^|/)(tmp|release|build)(/|$)') { return $false }
    if ($path -match '\.(pdf|pyc)$') { return $false }
    if ($path -match '(^|/)(\.ges-pids|\.ges-backend-port)$') { return $false }
    if ($path -eq 'frontend/tsconfig.node.tsbuildinfo') { return $false }
    if ($path -eq 'data/app.db') { return $false }
    if ($path -match '^data/(original|processed|cache|logs|exports)/' -and -not $path.EndsWith('/.gitkeep')) {
        return $false
    }
    return $true
}

try {
    New-Item -ItemType Directory -Path $stagingProject | Out-Null
    $trackedPaths = @(& git -C $projectRoot ls-files)
    if ($LASTEXITCODE -ne 0 -or $trackedPaths.Count -eq 0) {
        throw 'Could not enumerate files tracked by the source revision.'
    }
    foreach ($relativePath in $trackedPaths) {
        if (-not (Test-ReleaseFile -RelativePath $relativePath)) { continue }
        $file = Get-Item -LiteralPath (Join-Path $projectRoot $relativePath)
        $target = Join-Path $stagingProject $relativePath
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target
    }

    $revisionRecord = @(
        'Geospatial Extraction Studio source release'
        "Commit: $sourceRevision"
        "Tag: $releaseTag"
        'Contents: clean files tracked by the commit above'
    ) -join [Environment]::NewLine
    [IO.File]::WriteAllText(
        (Join-Path $stagingProject 'SOURCE-REVISION.txt'),
        "$revisionRecord$([Environment]::NewLine)",
        [Text.UTF8Encoding]::new($false)
    )

    $required = @(
        'LICENSE',
        'NOTICE',
        'THIRD_PARTY_NOTICES.md',
        'CONTENT_PROVENANCE.md',
        'ASSET_LICENSES.md',
        'SOURCE-REVISION.txt',
        'CONTRIBUTING.md',
        'backend\requirements.lock.txt',
        'backend\requirements-installer.lock.txt',
        'backend\requirements-build.txt',
        'packaging\README.md',
        'packaging\build-installer.ps1',
        'packaging\collect_licenses.py',
        'packaging\inspect_native_versions.py',
        'packaging\GeospatialExtractionStudio.spec',
        'packaging\installer.nsi',
        'packaging\native-components.json',
        'packaging\native-evidence-registry.json',
        'packaging\python-components.json',
        'packaging\visual-studio-entitlement.json',
        'packaging\native-source\README.md',
        'frontend\pnpm-lock.yaml'
    )
    foreach ($relativePath in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $stagingProject $relativePath) -PathType Leaf)) {
            throw "Required release file is missing: $relativePath"
        }
    }

    $evidenceRegistry = Get-Content -LiteralPath (
        Join-Path $stagingProject 'packaging\native-evidence-registry.json'
    ) -Raw | ConvertFrom-Json
    $evidencePaths = @(
        $evidenceRegistry.licenses.PSObject.Properties.Value.repository_path
        $evidenceRegistry.sources.PSObject.Properties.Value.repository_path
    )
    foreach ($repositoryPath in $evidencePaths) {
        if (-not (Test-Path -LiteralPath (Join-Path $stagingProject $repositoryPath) -PathType Leaf)) {
            throw "Native evidence referenced by the release is missing: $repositoryPath"
        }
    }

    $destinationParent = Split-Path -Parent $destinationPath
    if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
    }
    Compress-Archive -LiteralPath $stagingProject -DestinationPath $destinationPath -CompressionLevel Optimal
    $archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destinationPath).Hash.ToLower()
    $checksumPath = "$destinationPath.sha256"
    [IO.File]::WriteAllText(
        $checksumPath,
        "$archiveHash  $([IO.Path]::GetFileName($destinationPath))$([Environment]::NewLine)",
        [Text.UTF8Encoding]::new($false)
    )
    Write-Output "Created clean Geospatial Extraction Studio source archive: $destinationPath"
    Write-Output "SHA-256: $archiveHash"
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
