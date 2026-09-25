@echo off
echo ========================================================
echo Select AI Video Model to Download into ComfyUI:
echo [1] LTX-Video 0.9.5 (Recommended for RTX 3060 6GB - ~5.3GB)
echo [2] Wan 2.1 I2V 1.3B (Wan Image-to-Video 1.3B - ~3.5GB)
echo [3] Wan 2.1 I2V 14B 480P (Full 14B Model - ~14GB)
echo [4] DreamShaper 8 (100% Free Local AI Image Generator - ~2GB)
echo ========================================================
set /p choice="Enter choice [1, 2, 3, or 4] (default 1): "
if "%choice%"=="" set choice=1
python download_video_model.py %choice%
pause
