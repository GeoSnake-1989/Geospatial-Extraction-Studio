$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFiles = @('.ges-pids') |
    ForEach-Object { Join-Path $root $_ } |
    Where-Object { Test-Path -LiteralPath $_ }
if (-not $pidFiles) {
    Write-Host 'No Geospatial Extraction Studio process file was found.'
    exit 0
}

Get-Content -LiteralPath $pidFiles | Select-Object -Unique | ForEach-Object {
    $processId = [int]$_
    & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}
Remove-Item -LiteralPath $pidFiles -Force
@('.ges-backend-port') | ForEach-Object {
    Remove-Item -LiteralPath (Join-Path $root $_) -Force -ErrorAction SilentlyContinue
}
Write-Host 'Geospatial Extraction Studio stopped.' -ForegroundColor Green
