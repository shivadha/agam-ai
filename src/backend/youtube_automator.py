
from moviepy.editor import ImageSequenceClip, AudioFileClip
import os

from src.backend.script_gen import generate_video_content
from src.backend.voice_gen import generate_audio as generate_tts_audio

# --- Script Generation ---
def generate_script(topic_title):
    """
    Generates a script for a YouTube video based on the topic title using OpenRouter.
    """
    content = generate_video_content(topic_title)
    return content.get("script", f"Welcome everyone! Today, we're talking about {topic_title}.")

# --- Audio Generation ---
def generate_audio(script_text, output_path="output/audio.mp3"):
    """
    Generates an audio file from the given script text using edge-tts.
    """
    return generate_tts_audio(script_text, output_path)

# --- Placeholder for Image Generation ---
def generate_images(topic_title, num_images=5, output_dir="output/images"):
    """
    Generates a sequence of images for the video.
    NOTE: This is a placeholder. You would integrate a free text-to-image API here.
    For now, it creates dummy placeholder images.
    """
    print("Generating images...")
    os.makedirs(output_dir, exist_ok=True)
    # Create dummy images for now
    from PIL import Image, ImageDraw, ImageFont
    image_paths = []
    for i in range(num_images):
        path = os.path.join(output_dir, f"image_{i}.png")
        img = Image.new('RGB', (1280, 720), color = 'grey')
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except IOError:
            font = ImageFont.load_default()
        d.text((10,10), f"{topic_title} - Scene {i+1}", fill=(255,255,0), font=font)
        img.save(path)
        image_paths.append(path)
    print(f"{num_images} images saved to {output_dir}")
    return image_paths

# --- Video Generation ---
def create_video(image_paths, audio_path, output_path="output/final_video.mp4"):
    """
    Creates a video from a list of image paths and an audio file.
    """
    print("Creating video...")
    if not image_paths or not audio_path:
        print("Error: Missing images or audio for video creation.")
        return None
    
    audio_clip = AudioFileClip(audio_path)
    # Set the duration of each image frame based on the audio duration
    frame_duration = audio_clip.duration / len(image_paths)
    
    clip = ImageSequenceClip(image_paths, durations=[frame_duration] * len(image_paths))
    clip = clip.set_audio(audio_clip)
    clip.write_videofile(output_path, codec='libx264', fps=24)
    print(f"Video saved to {output_path}")
    return output_path

