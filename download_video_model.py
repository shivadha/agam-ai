"""
Download AI Video Models for ComfyUI + PulseForge
Target folder: c:\\AI_project\\ComfyUI\\models\\checkpoints
"""
import sys
import os
from huggingface_hub import hf_hub_download

TARGET_DIR = os.path.join(os.path.dirname(__file__), "ComfyUI", "models", "checkpoints")
os.makedirs(TARGET_DIR, exist_ok=True)

MODELS = {
    "1": {
        "name": "LTX-Video 0.9.5 (Recommended for 6GB RTX 3060 - Fast & Compact ~5.3GB)",
        "repo_id": "Lightricks/LTX-Video",
        "filename": "ltx-video-2b-v0.9.5.safetensors"
    },
    "2": {
        "name": "Wan 2.1 I2V 1.3B FP8 (High Quality, 6GB-friendly ~3.5GB)",
        "repo_id": "Kijai/WanVideo_comfy",
        "filename": "Wan2_1_I2V_1.3B_bf16.safetensors"
    },
    "3": {
        "name": "Wan 2.1 I2V 14B 480P (Full 14B Model, 14GB+ VRAM/RAM required)",
        "repo_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
        "filename": "split_files/diffusion_models/wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors"
    },
    "4": {
        "name": "DreamShaper 8 (100% Free Local AI Image Generator for 6GB RTX 3060 - ~2GB)",
        "repo_id": "Lykon/DreamShaper",
        "filename": "DreamShaper_8_pruned.safetensors"
    }
}

def download(choice="1"):
    model = MODELS.get(choice, MODELS["1"])
    print(f"\n=======================================================")
    print(f"Downloading: {model['name']}")
    print(f"Repository:  {model['repo_id']}")
    print(f"File:        {model['filename']}")
    print(f"Destination: {TARGET_DIR}")
    print(f"=======================================================\n")
    try:
        dest_path = hf_hub_download(
            repo_id=model["repo_id"],
            filename=model["filename"],
            local_dir=TARGET_DIR,
            local_dir_use_symlinks=False
        )
        print(f"\n✅ SUCCESS! Downloaded to: {dest_path}")
        print("ComfyUI and PulseForge will now detect this model!")
    except Exception as e:
        print(f"\n❌ Error downloading model: {e}")

if __name__ == "__main__":
    choice = sys.argv[1] if len(sys.argv) > 1 else "1"
    download(choice)
