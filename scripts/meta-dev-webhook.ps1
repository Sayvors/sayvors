# Helper: start ngrok http tunnel for local Meta webhook development.
# Prints the webhook callback URL and verify-token hint. Requires ngrok.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\meta-dev-webhook.ps1
# Optional: pass an explicit ngrok binary path:  -ngrokPath C:\tools\ngrok.exe

param(
    [string]$ngrokPath = "ngrok",
    [int]$port = 8000,
    [string]$repoRoot = (Get-Location).Path
)

# Resolve ngrok to a real file path:
#   1. If the caller passed an explicit path, use it as-is.
#   2. Otherwise prefer `ngrok` on PATH (the downloaded binary, e.g. a
#      winget-added WindowsApps alias) and resolve to its Source path.
#   3. Fall back to the WinGet\Packages folder if PATH hasn't caught up yet.
$winGetNgrok = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter "ngrok.exe" -Recurse -Depth 4 -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if ($ngrokPath -eq "ngrok") {
    $onPath = Get-Command ngrok -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
    if ($onPath) { $ngrokPath = $onPath }
    elseif ($winGetNgrok) { $ngrokPath = $winGetNgrok }
}

Write-Host "Using ngrok: $ngrokPath" -ForegroundColor DarkGray
if (-not (Test-Path $ngrokPath)) {
    Write-Host "ngrok binary not found at '$ngrokPath'." -ForegroundColor Red
    Write-Host "Install it, e.g.:  winget install ngrok.ngrok   or   choco install ngrok -y" -ForegroundColor Yellow
    exit 1
}

# ngrok logs its startup to a temp file so we can show the real error if it dies.
$ngrokLog = Join-Path $env:TEMP "ngrok-meta-dev-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
$errFile = "$ngrokLog.err"

Write-Host "Starting ngrok tunnel on port $port ..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $ngrokPath -ArgumentList "http", $port, "--log", "stdout", "--log-format", "logfmt", "--log-level", "info" -WindowStyle Normal -RedirectStandardOutput $ngrokLog -RedirectStandardError $errFile -PassThru

# ngrok exposes its local status API on 127.0.0.1:4040.
$callback = $null
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 1000
    if ($proc.HasExited) {
        # ngrok died before a tunnel came up — stop and show why.
        Write-Host ""
        Write-Host "ngrok exited immediately (code $($proc.ExitCode))." -ForegroundColor Red
        Write-Host "--- ngrok log ---" -ForegroundColor DarkGray
        Get-Content $ngrokLog, $errFile -ErrorAction SilentlyContinue | Select-Object -Last 15 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
        Write-Host "-----------------" -ForegroundColor DarkGray
        Write-Host "Common fixes:" -ForegroundColor Yellow
        Write-Host "  1. Update the agent:                       $ngrokPath update" -ForegroundColor Yellow
        Write-Host "  2. Add your authtoken (dashboard.ngrok.com):  $ngrokPath config add-authtoken <TOKEN>" -ForegroundColor Yellow
        exit 1
    }
    try {
        $tunnels = (Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2).tunnels
        $https = $tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1
        if ($https) { $callback = $https.public_url; break }
    } catch {
        # ngrok not up yet
    }
}

if (-not $callback) {
    Write-Host "Timed out waiting for an ngrok URL." -ForegroundColor Red
    exit 1
}

$envFile = Join-Path $repoRoot "services\api\.env"
$token = ""
if (Test-Path $envFile) {
    $tokenLine = (Get-Content $envFile | Where-Object { $_ -match '^\s*META_WEBHOOK_VERIFY_TOKEN\s*=' }) | Select-Object -First 1
    if ($tokenLine) { $token = ($tokenLine -split '=', 2)[1].Trim().Trim('"', "'") }
}

Write-Host ""
Write-Host "ngrok is UP: $callback" -ForegroundColor Green
Write-Host "Meta webhook callback URL:" -ForegroundColor Cyan
Write-Host "  $callback/api/v1/meta/webhooks" -ForegroundColor Cyan
Write-Host ""
Write-Host "Add this domain to ALLOWED_HOSTS in services\api\.env, e.g.:" -ForegroundColor Yellow
$domain = $callback -replace '^https://', ''
Write-Host ('  ALLOWED_HOSTS=["localhost","127.0.0.1","{0}"]' -f $domain) -ForegroundColor Yellow
if ($token) {
    Write-Host ""
    Write-Host "Verify token (from services\api\.env): $token" -ForegroundColor Yellow
    Write-Host "Paste BOTH into the Meta Dashboard webhook configuration." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "META_WEBHOOK_VERIFY_TOKEN is not set in services\api\.env - set it first." -ForegroundColor Red
}
Write-Host ""
Write-Host "ngrok is running in its own window. Ctrl+C there to stop it." -ForegroundColor Cyan
Write-Host "Waiting for ngrok to exit ..." -ForegroundColor DarkGray

$proc.WaitForExit()