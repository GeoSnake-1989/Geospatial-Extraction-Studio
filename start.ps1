$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendPython = Join-Path $root 'backend\.venv\Scripts\python.exe'
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$frontendNode = if ($nodeCommand) { $nodeCommand.Source } else { 'C:\Users\jake_\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' }
$vite = Join-Path $root 'frontend\node_modules\vite\bin\vite.js'
$logDirectory = Join-Path $root 'data\logs'
$portFile = Join-Path $root '.ges-backend-port'
$configuredBackendPort = $env:GES_BACKEND_PORT
$configuredBackendPortNumber = $null
if ($configuredBackendPort) {
    try {
        $configuredBackendPortNumber = [int]$configuredBackendPort
    } catch {
        throw 'GES_BACKEND_PORT must be a valid TCP port number.'
    }
    if ($configuredBackendPortNumber -lt 1 -or $configuredBackendPortNumber -gt 65535) {
        throw 'GES_BACKEND_PORT must be between 1 and 65535.'
    }
}

function Test-GESPortAvailable {
    param([int]$Port)
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        try { $listener.Stop() } catch { }
    }
}

function Start-GESProcess {
    param(
        [string]$FilePath,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$StandardOutput,
        [string]$StandardError
    )

    # ProcessStartInfo avoids a Windows PowerShell Start-Process failure when
    # the parent environment contains differently-cased duplicate variables.
    $command = '"' + $FilePath + '" ' + $Arguments + ' 1>"' + $StandardOutput + '" 2>"' + $StandardError + '"'
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = 'cmd.exe'
    $info.Arguments = '/d /s /c "' + $command + '"'
    $info.WorkingDirectory = $WorkingDirectory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    return [System.Diagnostics.Process]::Start($info)
}

function Get-GESListeningProcessIds {
    param([int[]]$Ports)

    $netstat = Join-Path $env:SystemRoot 'System32\netstat.exe'
    & $netstat -ano -p tcp | ForEach-Object {
        if ($_ -match '^\s*TCP\s+(?<address>\S+):(?<port>\d+)\s+\S+\s+LISTENING\s+(?<pid>\d+)\s*$') {
            $port = [int]$Matches.port
            if ($port -in $Ports) {
                [int]$Matches.pid
            }
        }
    }
}

if (-not (Test-Path $backendPython)) {
    throw 'Backend environment is missing. Follow the first-time setup in README.md.'
}
if (-not (Test-Path $vite)) {
    throw 'Frontend packages are missing. Run pnpm install in the frontend folder.'
}
if (-not (Test-Path $frontendNode)) { throw 'Node.js was not found. Install Node.js 20 or newer.' }
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

$existingBackendPorts = @()
if (Test-Path -LiteralPath $portFile) {
    try {
        $recordedBackendPort = [int](Get-Content -LiteralPath $portFile -Raw).Trim()
        if ($recordedBackendPort -ge 1 -and $recordedBackendPort -le 65535) {
            $existingBackendPorts += $recordedBackendPort
        }
    } catch {
        # Ignore an unreadable or stale port record and continue with other candidates.
    }
}
$existingBackendPorts += @(
    @($configuredBackendPortNumber, 8000) | Where-Object { $null -ne $_ }
)

try {
    $existingFrontend = Invoke-WebRequest 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 2
} catch {
    $existingFrontend = $null
}
if ($existingFrontend -and $existingFrontend.StatusCode -eq 200) {
    foreach ($candidatePort in ($existingBackendPorts | Select-Object -Unique)) {
        try {
            $existingHealth = Invoke-RestMethod "http://127.0.0.1:$candidatePort/api/health" -TimeoutSec 2
            if (
                $existingHealth.status -eq 'ok' -and
                $existingHealth.service -eq 'Geospatial Extraction Studio'
            ) {
                Write-Host 'Geospatial Extraction Studio is already running at http://127.0.0.1:5173' -ForegroundColor Green
                Write-Host "Backend API is using port $candidatePort."
                exit 0
            }
        } catch {
            # This candidate is not a running Geospatial Extraction Studio backend.
        }
    }
}

$backendPort = if ($null -ne $configuredBackendPortNumber) { $configuredBackendPortNumber } else { 8000 }
if ($null -eq $configuredBackendPortNumber) {
    while ($backendPort -le 8020 -and -not (Test-GESPortAvailable -Port $backendPort)) {
        $backendPort++
    }
}
if ($null -eq $configuredBackendPortNumber -and $backendPort -gt 8020) {
    throw 'Geospatial Extraction Studio could not find an available backend port between 8000 and 8020.'
}
if (-not (Test-GESPortAvailable -Port $backendPort)) {
    throw "Geospatial Extraction Studio backend port $backendPort is already in use."
}
$env:GES_BACKEND_PORT = [string]$backendPort
$backendHealthUrl = "http://127.0.0.1:$backendPort/api/health"

$backendArguments = "-m uvicorn app.main:app --host 127.0.0.1 --port $backendPort"
$backend = Start-GESProcess -FilePath $backendPython -Arguments $backendArguments -WorkingDirectory (Join-Path $root 'backend') -StandardOutput (Join-Path $logDirectory 'backend.log') -StandardError (Join-Path $logDirectory 'backend-error.log')
$frontendArguments = "`"$vite`" --host 127.0.0.1 --port 5173"
$frontend = Start-GESProcess -FilePath $frontendNode -Arguments $frontendArguments -WorkingDirectory (Join-Path $root 'frontend') -StandardOutput (Join-Path $logDirectory 'frontend.log') -StandardError (Join-Path $logDirectory 'frontend-error.log')

$pidFile = Join-Path $root '.ges-pids'
@($backend.Id, $frontend.Id) | Set-Content $pidFile
$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $health = Invoke-RestMethod $backendHealthUrl -TimeoutSec 1
        $page = Invoke-WebRequest 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 1
        if ($health.status -eq 'ok' -and $page.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 300
    }
}

if (-not $ready) {
    $failedProcessIds = @($backend.Id, $frontend.Id) + @(
        Get-GESListeningProcessIds -Ports @($backendPort, 5173)
    )
    $failedProcessIds |
        Where-Object { $_ } |
        Select-Object -Unique |
        ForEach-Object { Stop-Process -Id $_ -ErrorAction SilentlyContinue }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    throw 'Geospatial Extraction Studio did not become ready. See data\logs\backend-error.log and frontend-error.log.'
}

# The launch wrappers redirect output through cmd.exe. Record both wrapper PIDs
# and the actual listening service PIDs so stop.ps1 cannot leave child services
# holding the application directory open.
$listenerProcessIds = @(Get-GESListeningProcessIds -Ports @($backendPort, 5173) | Select-Object -Unique)
if ($listenerProcessIds.Count -lt 2) {
    $failedProcessIds = @($backend.Id, $frontend.Id) + $listenerProcessIds
    $failedProcessIds |
        Where-Object { $_ } |
        Select-Object -Unique |
        ForEach-Object { Stop-Process -Id $_ -ErrorAction SilentlyContinue }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    throw 'Geospatial Extraction Studio started, but its service processes could not be identified.'
}

@($backend.Id, $frontend.Id) + $listenerProcessIds |
    Where-Object { $_ } |
    Select-Object -Unique |
    Set-Content $pidFile

Set-Content -Path $portFile -Value $backendPort
Write-Host 'Geospatial Extraction Studio is ready at http://127.0.0.1:5173' -ForegroundColor Green
Write-Host "Backend API selected port $backendPort."
Write-Host 'Run .\stop.ps1 when you are finished.'
