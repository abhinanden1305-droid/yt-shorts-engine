import os
import json
import subprocess
from google import genai
from google.genai import types
from google.cloud import texttospeech
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 1. Initialize Gemini Client
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# 2. Load or Auto-Replenish Topics
with open("topics.json", "r", encoding="utf-8") as f:
    topics = json.load(f)

pending = [t for t in topics if t.get("status") == "pending"]
if not pending:
    last_niche = topics[-1].get("niche", "Fascinating Facts & Storytelling") if topics else "Fascinating Facts & Storytelling"
    print(f"Queue empty — generating 5 fresh topics in niche: {last_niche}...")
    existing_titles = [t["topic"] for t in topics]
    refill_prompt = (
        f"Generate 5 unique, high-retention YouTube Shorts topics in the niche '{last_niche}' "
        f"that are NOT in this list: {json.dumps(existing_titles)}. "
        "Return ONLY a JSON array of strings."
    )
    refill_resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=refill_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    new_topics = [
        {"niche": last_niche, "topic": title, "status": "pending"}
        for title in json.loads(refill_resp.text)
    ]
    topics.extend(new_topics)
    pending = new_topics

current_item = pending[0]
niche_name = current_item.get("niche", "Storytelling & Facts")
topic_title = current_item["topic"]
print(f"Selected [{niche_name}]: {topic_title}")

# 3. Generate Niche-Adapted Script, Visual Direction, and Metadata
script_prompt = f"""
Create a gripping, high-retention 45-second YouTube Short script.
Niche: "{niche_name}"
Topic: "{topic_title}"

Guidelines:
- Match the tone, vocabulary, and emotional energy to the "{niche_name}" niche.
- Hook (0-5s): A bold opening question, surprising fact, or dramatic revelation.
- Body (5-38s): Vivid, fast-paced storytelling with clear takeaways.
- Closing CTA (38-45s): Memorable final thought and a natural prompt inviting viewers to comment.

Return ONLY valid JSON with these exact keys:
{{
  "yt_title": "Catchy title under 70 chars including #Shorts and 1 niche hashtag",
  "yt_description": "2-sentence engaging summary + 4 relevant hashtags including #Shorts",
  "yt_tags": ["tag1", "tag2", "tag3", "tag4", "Shorts"],
  "narration": "Clean spoken narration text ONLY (no stage directions, no brackets, ~105-115 words)",
  "image_prompt": "Vertical 9:16 ultra-detailed cinematic illustration matching '{niche_name}' and '{topic_title}', dramatic lighting, rich composition, 8k digital art, strictly no text, letters, or watermarks"
}}
"""

story_resp = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=script_prompt,
    config=types.GenerateContentConfig(response_mime_type="application/json"),
)
story_data = json.loads(story_resp.text)

# 4. Generate 9:16 Vertical Artwork via Imagen 3
print("Generating 9:16 artwork...")
img_resp = client.models.generate_images(
    model="imagen-3.0-generate-002",
    prompt=story_data["image_prompt"],
    config=types.GenerateImagesConfig(
        number_of_images=1,
        aspect_ratio="9:16",
        output_mime_type="image/jpeg",
    ),
)
img_path = "frame.jpg"
with open(img_path, "wb") as f:
    f.write(img_resp.generated_images[0].image.image_bytes)

# 5. Generate Neural Voiceover via Google Cloud TTS
print("Synthesizing voiceover...")
tts_client = texttospeech.TextToSpeechClient()
synthesis_input = texttospeech.SynthesisInput(text=story_data["narration"])
voice = texttospeech.VoiceSelectionParams(
    language_code="en-IN",
    name="en-IN-Neural2-D",
)
audio_config = texttospeech.AudioConfig(
    audio_encoding=texttospeech.AudioEncoding.MP3,
    speaking_rate=0.97,
)
tts_response = tts_client.synthesize_speech(
    input=synthesis_input, voice=voice, audio_config=audio_config
)
audio_path = "voiceover.mp3"
with open(audio_path, "wb") as f:
    f.write(tts_response.audio_content)

# 6. Measure Audio Duration & Build Timed SRT Subtitles
probe = subprocess.check_output([
    "ffprobe", "-v", "error", "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1", audio_path
]).decode().strip()
duration = float(probe)

words = story_data["narration"].split()
chunk_size = 5
chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
time_per_chunk = duration / max(len(chunks), 1)

def fmt_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

srt_path = "subtitles.srt"
with open(srt_path, "w", encoding="utf-8") as f:
    for idx, chunk in enumerate(chunks, start=1):
        start_t = fmt_time((idx - 1) * time_per_chunk)
        end_t = fmt_time(min(idx * time_per_chunk, duration))
        f.write(f"{idx}\n{start_t} --> {end_t}\n{chunk}\n\n")

# 7. Render Vertical 1080x1920 MP4 with Ken Burns Slow Zoom + Burned Subtitles
print("Rendering final Short with FFmpeg...")
output_video = "final_short.mp4"
total_frames = int(duration * 30) + 30
vf_filter = (
    f"scale=2160:3840,"
    f"zoompan=z='min(zoom+0.0005,1.15)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
    f"subtitles={srt_path}:force_style='Alignment=2,MarginV=260,FontName=DejaVu Sans,FontSize=15,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2'"
)

subprocess.run([
    "ffmpeg", "-y",
    "-loop", "1", "-i", img_path,
    "-i", audio_path,
    "-vf", vf_filter,
    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "192k",
    "-t", str(duration + 0.5),
    output_video
], check=True)

# 8. Upload Directly to YouTube Shorts
print("Uploading to YouTube...")
token_info = json.loads(os.environ["YOUTUBE_TOKEN_JSON"])
creds = Credentials.from_authorized_user_info(token_info)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())

youtube = build("youtube", "v3", credentials=creds)
body = {
    "snippet": {
        "title": story_data["yt_title"][:100],
        "description": story_data["yt_description"],
        "tags": story_data.get("yt_tags", ["Shorts"]),
        "categoryId": "22"
    },
    "status": {
        "privacyStatus": "unlisted",
        "selfDeclaredMadeForKids": False
    }
}

media = MediaFileUpload(output_video, chunksize=-1, resumable=True, mimetype="video/mp4")
request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
response = request.execute()
video_id = response["id"]
print(f"PUBLISHED! https://youtube.com/shorts/{video_id}")

# 9. Mark Topic as Published
current_item["status"] = "published"
current_item["video_id"] = video_id
with open("topics.json", "w", encoding="utf-8") as f:
    json.dump(topics, f, indent=2, ensure_ascii=False)
