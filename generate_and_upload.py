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

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
if DRY_RUN:
    print("=== DRY RUN MODE ENABLED (Skipping image gen, FFmpeg render, YouTube upload & topics.json update) ===")

# Language configuration map (Neural2 voices)
VOICE_MAP = {
    "Hindi": {
        "tts_code": "hi-IN",
        "voice_name": "hi-IN-Neural2-B",
        "font": "Noto Sans Devanagari",
        "script_instruction": "Write the narration, yt_title, and yt_description in natural, engaging spoken Hindi (Devanagari script), keeping #Shorts in English."
    },
    "English": {
        "tts_code": "en-IN",
        "voice_name": "en-IN-Neural2-D",
        "font": "Noto Sans",
        "script_instruction": "Write the narration, yt_title, and yt_description in natural, gripping Indian English."
    },
    "Bengali": {
        "tts_code": "bn-IN",
        "voice_name": "bn-IN-Wavenet-B",
        "font": "Noto Sans Bengali",
        "script_instruction": "Write the narration, yt_title, and yt_description in natural, engaging spoken Bengali (Bengali script), keeping #Shorts in English."
    }
}

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
        model="gemini-3.8-flash",
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

# Priority: GitHub workflow dropdown (if manually triggered) -> item's "language" in topics.json -> default "Hindi"
env_lang = os.environ.get("TARGET_LANGUAGE", "").strip()
selected_lang = env_lang if env_lang in VOICE_MAP else current_item.get("language", "Hindi")
if selected_lang not in VOICE_MAP:
    selected_lang = "Hindi"

lang_cfg = VOICE_MAP[selected_lang]
print(f"Selected [{niche_name}] | Language: {selected_lang} | Topic: {topic_title}")

# 3. Generate Niche-Adapted Script, Visual Direction, and Metadata
script_prompt = f"""
Create a gripping, high-retention 45-second YouTube Short script.
Niche: "{niche_name}"
Topic: "{topic_title}"
Language Rule: {lang_cfg["script_instruction"]}

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
  "image_prompt": "Vertical 9:16 ultra-detailed cinematic illustration in English matching '{niche_name}' and '{topic_title}', dramatic lighting, rich composition, 8k digital art, strictly no text, letters, or watermarks"
}}
"""

story_resp = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=script_prompt,
    config=types.GenerateContentConfig(response_mime_type="application/json"),
)
story_data = json.loads(story_resp.text)
print("Generated Title:", story_data["yt_title"])
print("Generated Narration:", story_data["narration"])

# 4. Verify Credentials & Stop Early if Dry Run
if DRY_RUN:
    print("Validating GCP Service Account & YouTube OAuth Refresh Token...")
    tts_client = texttospeech.TextToSpeechClient()
    token_info = json.loads(os.environ["YOUTUBE_TOKEN_JSON"])
    creds = Credentials.from_authorized_user_info(token_info)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    print(f"DRY RUN PASSED! Language={selected_lang}, Gemini 3.8 Flash, GCP credentials & YouTube token are valid ($0.00 cost).")
    raise SystemExit(0)

# 5. Generate 9:16 Vertical Artwork via Gemini Native Image Generation
print("Generating 9:16 artwork...")
img_resp = client.models.generate_content(
    model="gemini-2.5-flash-image",
    contents=story_data["image_prompt"],
    config=types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio="9:16"),
    ),
)
img_path = "frame.png"
image_saved = False
for part in img_resp.candidates[0].content.parts:
    if part.inline_data is not None:
        with open(img_path, "wb") as f:
            f.write(part.inline_data.data)
        image_saved = True
        break

if not image_saved:
    raise RuntimeError("No image bytes were returned by gemini-2.5-flash-image.")

# 6. Generate Neural Voiceover via Google Cloud TTS
print(f"Synthesizing {selected_lang} voiceover ({lang_cfg['voice_name']})...")
tts_client = texttospeech.TextToSpeechClient()
synthesis_input = texttospeech.SynthesisInput(text=story_data["narration"])
voice = texttospeech.VoiceSelectionParams(
    language_code=lang_cfg["tts_code"],
    name=lang_cfg["voice_name"],
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

# 7. Measure Audio Duration & Build Timed ASS Subtitles (Exact 1080x1920 Safe Zone)
probe = subprocess.check_output([
    "ffprobe", "-v", "error", "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1", audio_path
]).decode().strip()
duration = float(probe)

words = story_data["narration"].split()
chunk_size = 4
chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
time_per_chunk = duration / max(len(chunks), 1)

def fmt_ass_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int((sec - int(sec)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

ass_path = "subtitles.ass"
ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{lang_cfg['font']},54,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,70,70,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

with open(ass_path, "w", encoding="utf-8") as f:
    f.write(ass_header)
    for idx, chunk in enumerate(chunks, start=1):
        start_t = fmt_ass_time((idx - 1) * time_per_chunk)
        end_t = fmt_ass_time(min(idx * time_per_chunk, duration))
        f.write(f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{chunk}\n")

# 8. Render Vertical 1080x1920 MP4 with Ken Burns Slow Zoom + Burned Subtitles
print("Rendering final Short with FFmpeg...")
output_video = "final_short.mp4"
total_frames = int(duration * 30) + 30
vf_filter = (
    f"scale=2160:3840,"
    f"zoompan=z='min(zoom+0.0005,1.15)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
    f"ass={ass_path}"
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

# 9. Upload Directly to YouTube Shorts
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

# 10. Mark Topic as Published
current_item["status"] = "published"
current_item["language"] = selected_lang
current_item["video_id"] = video_id
with open("topics.json", "w", encoding="utf-8") as f:
    json.dump(topics, f, indent=2, ensure_ascii=False)
