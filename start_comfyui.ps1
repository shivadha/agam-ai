$Host.UI.RawUI.WindowTitle = "PulseForge - ComfyUI AI Video Engine"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  PulseForge - ComfyUI AI Video Engine (RTX 3060 6GB)   " -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan

$pyPath = "C:\Users\shiva\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $pyPath)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $pyPath = $cmd.Source }
}

# Check if port 8188 is already in use
$conn = Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    $pid8188 = $conn.OwningProcess
    Write-Host ""
    Write-Host "[*] ComfyUI is ALREADY RUNNING on http://127.0.0.1:8188 (PID: $pid8188)" -ForegroundColor Yellow
    Write-Host "[*] PulseForge is connected and ready for AI video generation!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  [1] Open ComfyUI in Browser (Default)"
    Write-Host "  [2] Restart ComfyUI (Stop existing instance and start fresh)"
    Write-Host "  [3] Exit"
    Write-Host ""
    $choice = Read-Host "Enter choice [1, 2, or 3] (default 1)"
    if ($choice -eq "2") {
        Write-Host "[*] Stopping previous ComfyUI (PID: $pid8188)..." -ForegroundColor Yellow
        Stop-Process -Id $pid8188 -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    } elseif ($choice -eq "3") {
        exit 0
    } else {
        Start-Process "http://127.0.0.1:8188"
        exit 0
    }
}

$comfyDir = Join-Path $PSScriptRoot "ComfyUI"
Set-Location $comfyDir
Write-Host "[*] Starting ComfyUI server at http://127.0.0.1:8188..." -ForegroundColor Cyan
Write-Host "[*] Mode: Dynamic Smart VRAM (RTX 3060 6GB Optimized)" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan

& $pyPath main.py --listen 127.0.0.1 --port 8188 --reserve-vram 0.8 --disable-mmap
