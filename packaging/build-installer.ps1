param(
    [string]$Python = (Join-Path $PSScriptRoot '..\backend\.venv\Scripts\python.exe'),
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
$version = '0.4.0'

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
    '--native-manifest', (Join-Path $projectRoot 'packaging\native-components.json'),
    '--output', (Join-Path $installerBuildRoot 'licenses')
)
if ($EngineeringBuild) { $licenseArguments += '--allow-unverified-native' }
& $Python @licenseArguments
if ($LASTEXITCODE -ne 0) { throw 'Installer copyright/license preflight failed.' }

$previousConsoleBuild = $env:GES_BUILD_CONSOLE
if ($EngineeringBuild) { $env:GES_BUILD_CONSOLE = '1' } else { Remove-Item Env:GES_BUILD_CONSOLE -ErrorAction SilentlyContinue }
try {
    & $Python -m PyInstaller --noconfirm --clean --distpath $binaryRoot --workpath (Join-Path $installerBuildRoot 'pyinstaller') (Join-Path $projectRoot 'packaging\GeospatialExtractionStudio.spec')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
} finally {
    $env:GES_BUILD_CONSOLE = $previousConsoleBuild
}

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
    exit 0
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

$outputRoot = if ($EngineeringBuild) { $installerBuildRoot } else { $releaseRoot }
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$output = Join-Path $outputRoot "Geospatial-Extraction-Studio-Setup-$version.exe"
if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Force }
& $makensisPath "/DAPP_SOURCE=$binaryApp" "/DOUTPUT_FILE=$output" "/DAPP_VERSION=$version" "/DLICENSE_FILE=$(Join-Path $projectRoot 'LICENSE')" (Join-Path $projectRoot 'packaging\installer.nsi')
if ($LASTEXITCODE -ne 0) { throw 'NSIS installer build failed.' }

$hash = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
$hashPath = "$output.sha256"
[IO.File]::WriteAllText($hashPath, "$hash  $([IO.Path]::GetFileName($output))`r`n", [Text.UTF8Encoding]::new($false))
Write-Output "Created installer: $output"
Write-Output "Created checksum: $hashPath"
if ($EngineeringBuild) {
    Write-Warning 'This engineering installer was built with unresolved native-library review items and was not placed in release/.'
}