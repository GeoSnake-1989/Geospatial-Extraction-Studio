param(
    [switch]$SkipDependencyInstall,
    [switch]$EngineeringBuild,
    [switch]$SkipNsis
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$buildRoot = Join-Path $projectRoot 'build'
$installerBuildRoot = Join-Path $buildRoot 'installer'
$binaryRoot = Join-Path $buildRoot 'binary'
$binaryApp = Join-Path $binaryRoot 'GeospatialExtractionStudio'
$smokeData = Join-Path $buildRoot 'smoke-data'
$releaseRoot = Join-Path $projectRoot 'release'
$version = '0.4.6'
$expectedReleaseTag = "v$version"

function Get-GESReleaseSourceState {
    $revisionOutput = @(& git -C $projectRoot rev-parse --verify HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $revisionOutput.Count -eq 0) {
        throw 'A committed Git revision is required before publishing an installer.'
    }
    $revision = ([string]$revisionOutput[0]).Trim()

    $workingState = @(& git -C $projectRoot status --porcelain --untracked-files=all 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not inspect the Git working tree before publishing.'
    }
    if ($workingState.Count -gt 0) {
        throw 'Refusing to publish an installer from a dirty working tree.'
    }

    $releaseTags = @(& git -C $projectRoot tag --points-at $revision 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not inspect release tags before publishing.'
    }
    if ($expectedReleaseTag -notin $releaseTags) {
        throw "Refusing to publish revision $revision without tag $expectedReleaseTag."
    }

    [pscustomobject]@{
        revision = $revision
        tag = $expectedReleaseTag
    }
}

$releaseSourceState = if (-not $EngineeringBuild -and -not $SkipNsis) {
    Get-GESReleaseSourceState
} else {
    $null
}

function Remove-GESBuildDirectory {
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

$runtimeOutput = & (Join-Path $PSScriptRoot 'prepare-runtime.ps1') -BuildRoot $buildRoot
$Python = [string]($runtimeOutput | Select-Object -Last 1)
$runtimeManifestPath = Join-Path $projectRoot 'packaging\runtime-components.json'
$runtimeManifest = Get-Content -Raw -LiteralPath $runtimeManifestPath | ConvertFrom-Json
$runtimeLicensePath = Join-Path (Join-Path $buildRoot 'runtime-cache') $runtimeManifest.combined_license.file_name
$runtimeArchivePath = Join-Path (Join-Path $buildRoot 'runtime-cache') $runtimeManifest.archive.file_name
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python executable not found: $Python"
}
$pnpm = (Get-Command pnpm.cmd -ErrorAction Stop).Source

Remove-GESBuildDirectory $installerBuildRoot
Remove-GESBuildDirectory $binaryRoot
Remove-GESBuildDirectory $smokeData
New-Item -ItemType Directory -Force -Path $installerBuildRoot,$binaryRoot,$smokeData | Out-Null

$previousCI = $env:CI
$env:CI = 'true'
try {
    & $pnpm --dir (Join-Path $projectRoot 'frontend') build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend production build failed.' }
} finally {
    $env:CI = $previousCI
}

if (-not $SkipDependencyInstall) {
    & $Python -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'backend\requirements-installer.lock.txt') -r (Join-Path $projectRoot 'backend\requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Installer dependency installation failed.' }
}

$licenseArguments = @(
    (Join-Path $projectRoot 'packaging\collect_licenses.py'),
    '--requirements', (Join-Path $projectRoot 'backend\requirements-installer.lock.txt'),
    '--python-manifest', (Join-Path $projectRoot 'packaging\python-components.json'),
    '--native-manifest', (Join-Path $projectRoot 'packaging\native-components.json'),
    '--runtime-manifest', $runtimeManifestPath,
    '--runtime-license', $runtimeLicensePath,
    '--output', (Join-Path $installerBuildRoot 'licenses')
)
if ($EngineeringBuild) { $licenseArguments += '--allow-unverified-native' }
& $Python @licenseArguments
if ($LASTEXITCODE -ne 0) { throw 'Installer copyright/license preflight failed.' }

$previousConsoleBuild = $env:GES_BUILD_CONSOLE
$previousBuildPath = $env:PATH
$systemRoot = $env:SystemRoot
if (-not $systemRoot) { throw 'SystemRoot is required for a reproducible Windows release build.' }
$approvedBuildPath = @(
    (Split-Path -Parent $Python),
    (Join-Path $systemRoot 'System32'),
    $systemRoot
) | Select-Object -Unique
$env:PATH = $approvedBuildPath -join [IO.Path]::PathSeparator
try {
    if ($EngineeringBuild) { $env:GES_BUILD_CONSOLE = '1' } else { Remove-Item Env:GES_BUILD_CONSOLE -ErrorAction SilentlyContinue }
    & $Python -m PyInstaller --noconfirm --clean --distpath $binaryRoot --workpath (Join-Path $installerBuildRoot 'pyinstaller') (Join-Path $projectRoot 'packaging\GeospatialExtractionStudio.spec')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
} finally {
    $env:GES_BUILD_CONSOLE = $previousConsoleBuild
    $env:PATH = $previousBuildPath
}

$licenseRoot = Join-Path $installerBuildRoot 'licenses'
& $Python (Join-Path $projectRoot 'packaging\audit_frozen_binary.py') `
    '--application' $binaryApp `
    '--license-bundle' $licenseRoot `
    '--installed-license-bundle' (Join-Path $binaryApp '_internal\licenses') `
    '--runtime-manifest' $runtimeManifestPath `
    '--runtime-license' $runtimeLicensePath `
    '--runtime-archive' $runtimeArchivePath `
    '--build-manifest' (Join-Path $projectRoot 'packaging\build-components.json') `
    '--native-report' (Join-Path $licenseRoot 'THIRD_PARTY_COMPONENTS.json') `
    '--pyz-toc' (Join-Path $installerBuildRoot 'pyinstaller\GeospatialExtractionStudio\PYZ-00.toc') `
    '--exe-toc' (Join-Path $installerBuildRoot 'pyinstaller\GeospatialExtractionStudio\EXE-00.toc') `
    '--frontend-manifest' (Join-Path $projectRoot 'packaging\frontend-components.json')
if ($LASTEXITCODE -ne 0) { throw 'Final frozen-binary copyright/license audit failed.' }

$smokePort = $null
foreach ($candidate in 18010..18030) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $candidate)
    try {
        $listener.Start()
        $smokePort = $candidate
        break
    } catch {
        continue
    } finally {
        try { $listener.Stop() } catch { }
    }
}
if ($null -eq $smokePort) { throw 'No port was available for the frozen-application smoke test.' }

$previousBrowser = $env:GES_NO_BROWSER
$previousPort = $env:GES_BACKEND_PORT
$previousData = $env:ELEVATION_DATA_DIR
$env:GES_NO_BROWSER = '1'
$env:GES_BACKEND_PORT = [string]$smokePort
$env:ELEVATION_DATA_DIR = $smokeData
$process = $null
try {
    $process = Start-Process -FilePath (Join-Path $binaryApp 'GeospatialExtractionStudio.exe') -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $smokeData 'launcher-stdout.log') -RedirectStandardError (Join-Path $smokeData 'launcher-stderr.log')
    $healthy = $false
    foreach ($attempt in 1..80) {
        if ($process.HasExited) { break }
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$smokePort/api/health" -TimeoutSec 1
            $page = Invoke-WebRequest "http://127.0.0.1:$smokePort/" -UseBasicParsing -TimeoutSec 1
            if ($health.status -eq 'ok' -and $page.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        } catch { }
        Start-Sleep -Milliseconds 250
    }
    if (-not $healthy) {
        $details = if (Test-Path -LiteralPath (Join-Path $smokeData 'logs\launcher-error.log')) { Get-Content -LiteralPath (Join-Path $smokeData 'logs\launcher-error.log') -Raw } elseif ($process.HasExited) { $stderr = if (Test-Path (Join-Path $smokeData 'launcher-stderr.log')) { Get-Content (Join-Path $smokeData 'launcher-stderr.log') -Raw } else { '' }; "Process exited with code $($process.ExitCode). $stderr" } else { 'No launcher error log was produced.' }
        throw "Frozen-application smoke test failed. $details"
    }
} finally {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    $env:GES_NO_BROWSER = $previousBrowser
    $env:GES_BACKEND_PORT = $previousPort
    $env:ELEVATION_DATA_DIR = $previousData
}

if ($SkipNsis) {
    Write-Output "Created and smoke-tested one-folder application: $binaryApp"
    return
}

$makensis = Get-Command makensis.exe -ErrorAction SilentlyContinue
$makensisPath = if ($makensis) { $makensis.Source } else { $null }
if (-not $makensisPath) {
    foreach ($candidate in @(
        "$env:ProgramFiles\NSIS\makensis.exe",
        "${env:ProgramFiles(x86)}\NSIS\makensis.exe"
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $makensisPath = $candidate
            break
        }
    }
}
if (-not $makensisPath) {
    throw 'NSIS makensis.exe was not found. Install NSIS or rerun with -SkipNsis to build only the onedir application.'
}

$buildPolicy = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'packaging\build-components.json') | ConvertFrom-Json
$nsisPolicy = @($buildPolicy.external_components | Where-Object { $_.name -eq 'nsis' })
if ($nsisPolicy.Count -ne 1) { throw 'Build policy must contain exactly one NSIS record.' }
$nsisPolicy = $nsisPolicy[0]
$nsisVersion = (& $makensisPath /VERSION | Select-Object -First 1).Trim()
$nsisHash = (Get-FileHash -LiteralPath $makensisPath -Algorithm SHA256).Hash.ToLowerInvariant()
$nsisLicense = Join-Path $projectRoot $nsisPolicy.license_path
$nsisLicenseHash = if (Test-Path -LiteralPath $nsisLicense -PathType Leaf) {
    (Get-FileHash -LiteralPath $nsisLicense -Algorithm SHA256).Hash.ToLowerInvariant()
} else { '' }
$installerScript = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'packaging\installer.nsi')
if ($nsisVersion -ne $nsisPolicy.version_output -or
    $nsisHash -ne $nsisPolicy.executable_sha256 -or
    $nsisLicenseHash -ne $nsisPolicy.license_sha256 -or
    $installerScript -notmatch "(?m)^SetCompressor $([regex]::Escape($nsisPolicy.compressor))\r?$") {
    throw 'NSIS version, executable, license evidence, or compressor differs from the approved build policy.'
}

$outputRoot = if ($EngineeringBuild) { $installerBuildRoot } else { $releaseRoot }
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$output = Join-Path $outputRoot "Geospatial-Extraction-Studio-Setup-$version.exe"
$hashPath = "$output.sha256"
$provenancePath = [IO.Path]::ChangeExtension($output, '.provenance.json')
foreach ($staleBinaryArtifact in @($output, $hashPath, $provenancePath)) {
    if (Test-Path -LiteralPath $staleBinaryArtifact) {
        Remove-Item -LiteralPath $staleBinaryArtifact -Force
    }
}

if (-not $EngineeringBuild) {
    $verifiedSourceState = Get-GESReleaseSourceState
    if ($verifiedSourceState.revision -ne $releaseSourceState.revision) {
        throw 'The source revision changed during the release build; restart from a clean tagged revision.'
    }
}

& $makensisPath "/DAPP_SOURCE=$binaryApp" "/DOUTPUT_FILE=$output" "/DAPP_VERSION=$version" "/DLICENSE_FILE=$(Join-Path $projectRoot 'LICENSE')" (Join-Path $projectRoot 'packaging\installer.nsi')
if ($LASTEXITCODE -ne 0) { throw 'NSIS installer build failed.' }

$hash = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText($hashPath, "$hash  $([IO.Path]::GetFileName($output))`r`n", [Text.UTF8Encoding]::new($false))

$applicationSourceProvenance = $null
if (-not $EngineeringBuild) {
    $sourceArchive = Join-Path $releaseRoot "Geospatial-Extraction-Studio-source-$version.zip"
    $sourceArchiveChecksum = "$sourceArchive.sha256"
    foreach ($staleSourceArtifact in @($sourceArchive, $sourceArchiveChecksum)) {
        if (Test-Path -LiteralPath $staleSourceArtifact) {
            Remove-Item -LiteralPath $staleSourceArtifact -Force
        }
    }
    try {
        & (Join-Path $projectRoot 'package-source.ps1') -Destination $sourceArchive
    } catch {
        Remove-Item -LiteralPath $output,$hashPath -Force -ErrorAction SilentlyContinue
        throw
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $sourceArchive -PathType Leaf)) {
        Remove-Item -LiteralPath $output,$hashPath -Force -ErrorAction SilentlyContinue
        throw 'Matching source archive creation failed; the installer is not publishable.'
    }
    $sourceArchiveHash = (Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    $applicationSourceProvenance = [ordered]@{
        revision = $releaseSourceState.revision
        tag = $releaseSourceState.tag
        archive = [IO.Path]::GetFileName($sourceArchive)
        archive_sha256 = $sourceArchiveHash
    }
}

$provenance = [ordered]@{
    format = 'Geospatial Extraction Studio installer provenance 1'
    status = 'approved'
    installer = [ordered]@{ path = [IO.Path]::GetFileName($output); sha256 = $hash }
}
if ($applicationSourceProvenance) {
    $provenance.application_source = $applicationSourceProvenance
}
$provenance.builder = [ordered]@{
        name = 'NSIS'
        version = $nsisPolicy.version
        version_output = $nsisVersion
        executable_sha256 = $nsisHash
        license = $nsisPolicy.license
        license_sha256 = $nsisLicenseHash
        compressor = $nsisPolicy.compressor
}
[IO.File]::WriteAllText($provenancePath, ($provenance | ConvertTo-Json -Depth 5) + "`r`n", [Text.UTF8Encoding]::new($false))
Write-Output "Created installer: $output"
Write-Output "Created checksum: $hashPath"
if ($applicationSourceProvenance) {
    Write-Output "Created matching source archive: $sourceArchive"
}
Write-Output "Created provenance: $provenancePath"
if ($EngineeringBuild) {
    Write-Warning 'This engineering installer was built with unresolved native-library review items and was not placed in release/.'
}
