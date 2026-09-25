import os
import asyncio
import edge_tts

# Default output directory: C:\AI_project\output
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

import datetime

def format_time(time_in_100ns):
    # Convert 100-nanosecond units to milliseconds
    total_ms = time_in_100ns / 10000
    hours = int(total_ms / (1000 * 60 * 60))
    minutes = int((total_ms / (1000 * 60)) % 60)
    seconds = int((total_ms / 1000) % 60)
    milliseconds = int(total_ms % 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

async def _generate_audio_async(text: str, output_path: str, voice: str):
    communicate = edge_tts.Communicate(text, voice)
    
    boundaries = []
    
    with open(output_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] in ["SentenceBoundary", "WordBoundary"]:
                boundaries.append(chunk)
                
    # If edge-tts returns WordBoundary, use them. Otherwise, interpolate from SentenceBoundary.
    words = []
    word_boundaries = [b for b in boundaries if b["type"] == "WordBoundary"]
    
    if word_boundaries:
        words = word_boundaries
    else:
        # Interpolate from SentenceBoundary
        sentence_boundaries = [b for b in boundaries if b["type"] == "SentenceBoundary"]
        for sb in sentence_boundaries:
            offset = sb["offset"]
            duration = sb["duration"]
            sentence_text = sb["text"]
            
            sentence_words = sentence_text.split()
            if not sentence_words:
                continue
                
            total_chars = sum(len(w) for w in sentence_words)
            current_offset = offset
            
            for w in sentence_words:
                w_duration = int((len(w) / total_chars) * duration)
                words.append({
                    "offset": current_offset,
                    "duration": w_duration,
                    "text": w
                })
                current_offset += w_duration

    # Generate SRT
    srt_content = ""
    for i, w in enumerate(words):
        start_time = format_time(w["offset"])
        end_time = format_time(w["offset"] + w["duration"])
        # Some padding for spacing
        text = w["text"].strip()
        srt_content += f"{i+1}\n{start_time} --> {end_time}\n{text}\n\n"

    # Save SRT file alongside audio
    srt_path = output_path.replace(".mp3", ".srt")
    with open(srt_path, "w", encoding="utf-8") as srt_file:
        srt_file.write(srt_content)
        
    return output_path, srt_path

def generate_audio(text: str, output_path: str = None, voice: str = "en-US-ChristopherNeural"):
    """
    Generates an audio file from the given text using edge-tts.
    Saves the output to C:\\AI_project\\output\\ or the specified path.
    Returns (audio_path, vtt_path)
    """
    if not text:
        print("Error: Empty text provided for audio generation.")
        return None, None

    if not output_path:
        output_path = os.path.join(OUTPUT_DIR, "audio.mp3")
    else:
        # Ensure the directory for the custom output path exists
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    
    print(f"Generating audio with voice '{voice}' to {output_path}...")
    try:
        audio_p, vtt_p = asyncio.run(_generate_audio_async(text, output_path, voice))
        print(f"Successfully generated audio: {audio_p} and subtitles: {vtt_p}")
        return audio_p, vtt_p
    except Exception as e:
        print(f"Error generating audio with edge-tts: {e}")
        return None, None

if __name__ == "__main__":
    # Test execution
    test_text = "Hello! This is a test of the new edge text to speech implementation."
    test_output = os.path.join(OUTPUT_DIR, "test_audio.mp3")
    generate_audio(test_text, test_output)
