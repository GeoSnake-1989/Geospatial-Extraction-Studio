param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$buildRoot = Join-Path $projectRoot 'build'
$binaryApp = Join-Path $buildRoot 'binary\GeospatialExtractionStudio'
$portableBuildRoot = Join-Path $buildRoot 'portable'
$releaseRoot = Join-Path $projectRoot 'release'
$version = '0.4.5'
$expectedTag = "v$version"
$archiveName = "Geospatial-Extraction-Studio-Portable-$version.zip"
$archivePath = Join-Path $releaseRoot $archiveName
$checksumPath = "$archivePath.sha256"
$provenancePath = Join-Path $releaseRoot "Geospatial-Extraction-Studio-Portable-$version.provenance.json"
$sourceArchive = Join-Path $releaseRoot "Geospatial-Extraction-Studio-source-$version.zip"
$sourceChecksum = "$sourceArchive.sha256"

function Get-ReleaseSourceState {
    $revision = (& git -C $projectRoot rev-parse --verify HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $revision) {
        throw 'A committed Git revision is required before publishing a portable package.'
    }
    $workingState = @(& git -C $projectRoot status --porcelain --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the Git working tree.' }
    if ($workingState.Count -gt 0) {
        throw 'Refusing to publish a portable package from a dirty working tree.'
    }
    $tags = @(& git -C $projectRoot tag --points-at $revision)
    if ($LASTEXITCODE -ne 0 -or $expectedTag -notin $tags) {
        throw "Refusing to publish revision $revision without tag $expectedTag."
    }
    [pscustomobject]@{ revision = $revision; tag = $expectedTag }
}

function Remove-PortableBuildDirectory {
    param([string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    $allowedPrefix = [IO.Path]::GetFullPath($buildRoot) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the build directory: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

$sourceState = Get-ReleaseSourceState
foreach ($path in @($archivePath, $checksumPath, $provenancePath, $sourceArchive, $sourceChecksum)) {
    if (Test-Path -LiteralPath $path) {
        throw "Refusing to overwrite an existing portable release artifact: $path"
    }
}

$buildArguments = @{ SkipNsis = $true }
if ($SkipDependencyInstall) { $buildArguments.SkipDependencyInstall = $true }
& (Join-Path $PSScriptRoot 'build-installer.ps1') @buildArguments
if ($LASTEXITCODE -ne 0) { throw 'Audited one-folder application build failed.' }
if (-not (Test-Path -LiteralPath (Join-Path $binaryApp 'GeospatialExtractionStudio.exe') -PathType Leaf)) {
    throw 'The smoke-tested one-folder application is missing.'
}

Remove-PortableBuildDirectory $portableBuildRoot
$stagingApp = Join-Path $portableBuildRoot "Geospatial-Extraction-Studio-Portable-$version"
New-Item -ItemType Directory -Force -Path $stagingApp,$releaseRoot | Out-Null
Copy-Item -Path (Join-Path $binaryApp '*') -Destination $stagingApp -Recurse -Force

$portableReadme = @"
Geospatial Extraction Studio $version - Portable Windows package

1. Extract the entire ZIP to a writable folder.
2. Run GeospatialExtractionStudio.exe. Do not move the EXE away from its _internal folder.
3. The application opens in your default browser and runs locally.

No installation, Python, Node.js, OpenAI connection, or administrator access is required.
Place search and data extraction still require internet access to their configured providers.
Application data is stored under %LOCALAPPDATA%\Geospatial Extraction Studio\data so that
large datasets remain available when the extracted application folder is replaced.

This package is unsigned. Windows may display an Unknown publisher or SmartScreen warning.
Verify the adjacent SHA-256 checksum before running the package.
"@
[IO.File]::WriteAllText(
    (Join-Path $stagingApp 'PORTABLE-README.txt'),
    $portableReadme.Trim() + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false)
)

Compress-Archive -LiteralPath $stagingApp -DestinationPath $archivePath -CompressionLevel Optimal
$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(
    $checksumPath,
    "$archiveHash  $archiveName$([Environment]::NewLine)",
    [Text.UTF8Encoding]::new($false)
)

& (Join-Path $projectRoot 'package-source.ps1') -Destination $sourceArchive
if ($LASTEXITCODE -ne 0) { throw 'Matching source archive creation failed.' }
$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceArchive).Hash.ToLowerInvariant()
$executableHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (
    Join-Path $stagingApp 'GeospatialExtractionStudio.exe'
)).Hash.ToLowerInvariant()

$verificationRoot = Join-Path $portableBuildRoot 'verification'
New-Item -ItemType Directory -Force -Path $verificationRoot | Out-Null
Expand-Archive -LiteralPath $archivePath -DestinationPath $verificationRoot
$verifiedApp = Join-Path $verificationRoot "Geospatial-Extraction-Studio-Portable-$version"
$verifiedExecutable = Join-Path $verifiedApp 'GeospatialExtractionStudio.exe'
if (-not (Test-Path -LiteralPath $verifiedExecutable -PathType Leaf)) {
    throw 'Portable archive verification failed: launcher is missing after extraction.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $verifiedExecutable).Hash.ToLowerInvariant() -ne $executableHash) {
    throw 'Portable archive verification failed: launcher digest changed after extraction.'
}

$provenance = [ordered]@{
    format = 'Geospatial Extraction Studio portable provenance 1'
    status = 'approved'
    package = [ordered]@{
        path = $archiveName
        sha256 = $archiveHash
        layout = 'PyInstaller onedir in a ZIP archive'
        executable_sha256 = $executableHash
    }
    application_source = [ordered]@{
        revision = $sourceState.revision
        tag = $sourceState.tag
        archive = [IO.Path]::GetFileName($sourceArchive)
        archive_sha256 = $sourceHash
    }
    verification = [ordered]@{
        frozen_application_smoke_test = 'passed'
        archive_extraction = 'passed'
        extracted_executable_digest = 'matched'
    }
}
[IO.File]::WriteAllText(
    $provenancePath,
    ($provenance | ConvertTo-Json -Depth 5) + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false)
)

Write-Output "Created portable application: $archivePath"
Write-Output "SHA-256: $archiveHash"
Write-Output "Provenance: $provenancePath"
