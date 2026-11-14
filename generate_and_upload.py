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
VIDEO_IDEA = os.environ.get("VIDEO_IDEA", "").strip()
VIDEO_COUNT = max(1, min(int(os.environ.get("VIDEO_COUNT", "1")), 5))
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "Auto-Detect from Idea").strip()

if DRY_RUN:
    print("=== DRY RUN MODE ENABLED (Skipping image gen, FFmpeg render, YouTube upload & topics.json update) ===")

CHANNEL_CONFIG = {
    "Bhakti Marg": {
        "env_secret": "YT_TOKEN_BHAKTI_MARG",
        "niche_desc": "Hindu spirituality, sacred temples, deities, mantras, and devotional mythology",
        "style_guide": "Reverent, mystical, devotional storytelling with sacred temple lighting and divine cosmic aesthetics."
    },
    "Biography of Hindu Saints": {
        "env_secret": "YT_TOKEN_HINDU_SAINTS",
        "niche_desc": "Life stories, miracles, teachings, and spiritual journeys of Hindu saints, yogis, and gurus",
        "style_guide": "Biographical, inspiring, historically grounded storytelling highlighting the saint's life, ashram, and core spiritual message."
    },
    "The Lean Bites": {
        "env_secret": "YT_TOKEN_LEAN_BITES",
        "niche_desc": "High-protein vegetarian and egg-inclusive diets, muscle-building nutrition, healthy low-glycemic recipes, and fat-loss science",
        "style_guide": "Crisp, practical, science-backed nutrition storytelling with appetizing macro-friendly food photography and clean vibrant visuals."
    },
    "I am Abhinanden": {
        "env_secret": "YOUTUBE_TOKEN_JSON",
        "niche_desc": "General stories, personal insights, experiments, and miscellaneous educational topics",
        "style_guide": "Engaging, clear, modern storytelling with high-contrast cinematic visuals."
    }
}

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

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def resolve_channel(idea_text):
    if TARGET_CHANNEL in CHANNEL_CONFIG:
        return TARGET_CHANNEL
    route_prompt = f"""
    Classify this video idea into the SINGLE best matching YouTube channel from these 4 options:
    1. "Bhakti Marg" -> Hindu spirituality, gods/goddesses, temples, rituals, Puranic stories.
    2. "Biography of Hindu Saints" -> Biographies, life stories, and teachings of specific saints, sages, or gurus (e.g., Bamakhepa, Neem Karoli Baba, Ramakrishna, Vivekananda, Adi Shankaracharya).
    3. "The Lean Bites" -> High-protein diet, vegetarian/egg protein meals, nutrition, fitness food, healthy recipes.
    4. "I am Abhinanden" -> Anything else (tech, general facts, personal tests, miscellaneous).

    Video Idea: "{idea_text}"
    Return ONLY valid JSON: {{"channel": "Exact Channel Name"}}
    """
    resp = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=route_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    chosen = json.loads(resp.text).get("channel", "I am Abhinanden")
    return chosen if chosen in CHANNEL_CONFIG else "I am Abhinanden"

def get_youtube_client(channel_name):
    secret_env = CHANNEL_CONFIG[channel_name]["env_secret"]
    raw_token = os.environ.get(secret_env, "").strip()
    if not raw_token:
        raise RuntimeError(f"Missing GitHub secret '{secret_env}' required for channel '{channel_name}'.")

    # Supports both full JSON object AND plain "1//0..." refresh token string
    if raw_token.startswith("{"):
        token_info = json.loads(raw_token)
    else:
        base_info = json.loads(os.environ["YOUTUBE_TOKEN_JSON"])
        token_info = {
            "token": "",
            "refresh_token": raw_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": base_info["client_id"],
            "client_secret": base_info["client_secret"],
            "scopes": ["https://www.googleapis.com/auth/youtube.upload"]
        }

    creds = Credentials.from_authorized_user_info(token_info)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)

with open("topics.json", "r", encoding="utf-8") as f:
    topics = json.load(f)

env_lang = os.environ.get("TARGET_LANGUAGE", "Hindi").strip()
selected_lang = env_lang if env_lang in VOICE_MAP else "Hindi"

batch_items = []
if VIDEO_IDEA:
    routed_channel = resolve_channel(VIDEO_IDEA)
    print(f"Idea '{VIDEO_IDEA}' routed to channel: [{routed_channel}] | Count: {VIDEO_COUNT}")
    if VIDEO_COUNT == 1:
        item = {"channel": routed_channel, "niche": VIDEO_IDEA, "topic": VIDEO_IDEA, "language": selected_lang, "status": "pending"}
        topics.append(item)
        batch_items.append(item)
    else:
        split_prompt = (
            f"Break this broad video idea for the YouTube channel '{routed_channel}' "
            f"({CHANNEL_CONFIG[routed_channel]['niche_desc']}) into {VIDEO_COUNT} distinct, "
            f"non-overlapping, high-retention YouTube Shorts topics: '{VIDEO_IDEA}'. "
            "Return ONLY a JSON array of strings."
        )
        split_resp = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=split_prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        for sub in json.loads(split_resp.text)[:VIDEO_COUNT]:
            item = {"channel": routed_channel, "niche": VIDEO_IDEA, "topic": sub, "language": selected_lang, "status": "pending"}
            topics.append(item)
            batch_items.append(item)
else:
    pending = [t for t in topics if t.get("status") == "pending"]
    if not pending:
        fallback_channel = TARGET_CHANNEL if TARGET_CHANNEL in CHANNEL_CONFIG else "Bhakti Marg"
        niche_desc = CHANNEL_CONFIG[fallback_channel]["niche_desc"]
        print(f"Queue empty — generating {VIDEO_COUNT} fresh topics for [{fallback_channel}]...")
        existing_titles = [t["topic"] for t in topics]
        refill_prompt = (
            f"Generate {VIDEO_COUNT} unique, high-retention YouTube Shorts topics for '{fallback_channel}' "
            f"({niche_desc}) that are NOT in this list: {json.dumps(existing_titles)}. "
            "Return ONLY a JSON array of strings."
        )
        refill_resp = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=refill_prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        new_topics = [
            {"channel": fallback_channel, "niche": niche_desc, "topic": title, "language": selected_lang, "status": "pending"}
            for title in json.loads(refill_resp.text)[:VIDEO_COUNT]
        ]
        topics.extend(new_topics)
        pending = new_topics
    batch_items = pending[:VIDEO_COUNT]

# Validate GCP TTS and all target YouTube channel tokens upfront
tts_client = texttospeech.TextToSpeechClient()
yt_clients = {}
for item in batch_items:
    ch = item.get("channel") or resolve_channel(item["topic"])
    item["channel"] = ch
    if ch not in yt_clients:
        print(f"Validating YouTube OAuth token for channel: [{ch}]...")
        yt_clients[ch] = get_youtube_client(ch)

def fmt_ass_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int((sec - int(sec)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

for batch_idx, current_item in enumerate(batch_items, start=1):
    ch_name = current_item["channel"]
    ch_cfg = CHANNEL_CONFIG[ch_name]
    topic_title = current_item["topic"]
    item_lang = env_lang if env_lang in VOICE_MAP else current_item.get("language", "Hindi")
    item_cfg = VOICE_MAP.get(item_lang, VOICE_MAP["Hindi"])

    print(f"\n--- [{batch_idx}/{len(batch_items)}] Channel: {ch_name} | Lang: {item_lang} | Topic: {topic_title} ---")

    script_prompt = f"""
    Create a gripping, high-retention 45-second YouTube Short script with a 4-to-5-scene visual storyboard.
    Target Channel: "{ch_name}" ({ch_cfg['niche_desc']})
    Visual & Tone Style: {ch_cfg['style_guide']}
    Specific Topic: "{topic_title}"
    Language Rule: {item_cfg["script_instruction"]}

    Guidelines:
    - Hook (0-5s): A bold opening question, surprising fact, or dramatic revelation.
    - Body (5-38s): Vivid, fast-paced storytelling with clear, authentic takeaways.
    - Closing CTA (38-45s): Memorable final thought and a natural prompt inviting viewers to comment.
    - Break the visual progression into 4 or 5 distinct chronological scenes (minimum 3, maximum 5) matching the narration flow, keeping consistent style across all scenes.

    Return ONLY valid JSON with these exact keys:
    {{
      "yt_title": "Catchy title under 70 chars including #Shorts and 1 niche hashtag",
      "yt_description": "2-sentence engaging summary + 4 relevant hashtags including #Shorts",
      "yt_tags": ["tag1", "tag2", "tag3", "tag4", "Shorts"],
      "narration": "Clean spoken narration text ONLY (no stage directions, no brackets, ~105-115 words)",
      "scene_prompts": [
        "Scene 1 (Hook): Vertical 9:16 ultra-detailed cinematic visual in English matching '{topic_title}', {ch_cfg['style_guide']}, 8k quality, strictly no text, letters, or watermarks",
        "Scene 2 (Setup): Vertical 9:16 ultra-detailed cinematic visual in English continuing the story with consistent style, 8k quality, strictly no text, letters, or watermarks",
        "Scene 3 (Climax): Vertical 9:16 ultra-detailed cinematic visual in English showing the peak moment, 8k quality, strictly no text, letters, or watermarks",
        "Scene 4 (Resolution): Vertical 9:16 ultra-detailed cinematic visual in English showing the powerful ending takeaway, 8k quality, strictly no text, letters, or watermarks"
      ]
    }}
    """

    story_resp = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=script_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    story_data = json.loads(story_resp.text)
    scene_prompts = story_data.get("scene_prompts", [])[:5]
    if len(scene_prompts) < 3:
        raise RuntimeError(f"Expected at least 3 scene prompts, got {len(scene_prompts)}")

    print("Title:", story_data["yt_title"])
    print(f"Scenes planned: {len(scene_prompts)}")

    if DRY_RUN:
        print("Narration preview:", story_data["narration"][:140] + "...")
        continue

    scene_images = []
    for s_idx, prompt in enumerate(scene_prompts, start=1):
        print(f"  Painting Scene {s_idx}/{len(scene_prompts)}...")
        img_resp = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="9:16"),
            ),
        )
        img_path = f"b{batch_idx}_scene_{s_idx}.png"
        saved = False
        for part in img_resp.candidates[0].content.parts:
            if part.inline_data is not None:
                with open(img_path, "wb") as f:
                    f.write(part.inline_data.data)
                saved = True
                break
        if not saved:
            raise RuntimeError(f"No image bytes returned for batch {batch_idx} scene {s_idx}.")
        scene_images.append(img_path)

    print(f"  Synthesizing {item_lang} voiceover...")
    synthesis_input = texttospeech.SynthesisInput(text=story_data["narration"])
    voice = texttospeech.VoiceSelectionParams(
        language_code=item_cfg["tts_code"],
        name=item_cfg["voice_name"],
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=0.97,
    )
    tts_response = tts_client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    audio_path = f"b{batch_idx}_voiceover.mp3"
    with open(audio_path, "wb") as f:
        f.write(tts_response.audio_content)

    probe = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_path
    ]).decode().strip()
    duration = float(probe)

    words = story_data["narration"].split()
    chunk_size = 4
    chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    time_per_chunk = duration / max(len(chunks), 1)

    ass_path = f"b{batch_idx}_subtitles.ass"
    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{item_cfg['font']},54,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,70,70,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        for c_idx, chunk in enumerate(chunks, start=1):
            start_t = fmt_ass_time((c_idx - 1) * time_per_chunk)
            end_t = fmt_ass_time(min(c_idx * time_per_chunk, duration))
            f.write(f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{chunk}\n")

    print(f"  Rendering {len(scene_images)} animated scenes...")
    total_video_duration = duration + 0.5
    scene_duration = total_video_duration / len(scene_images)
    scene_frames = int(scene_duration * 30) + 5

    clip_files = []
    for s_idx, img_path in enumerate(scene_images, start=1):
        clip_path = f"b{batch_idx}_clip_{s_idx}.mp4"
        zoom_expr = "min(zoom+0.0008,1.15)" if s_idx % 2 == 1 else "max(1.15-0.0008*on,1.0)"
        scene_vf = (
            f"scale=2160:3840,"
            f"zoompan=z='{zoom_expr}':d={scene_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30"
        )
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", img_path,
            "-vf", scene_vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-t", f"{scene_duration:.3f}",
            clip_path
        ], check=True)
        clip_files.append(clip_path)

    concat_list = f"b{batch_idx}_clips.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for clip in clip_files:
            f.write(f"file '{clip}'\n")

    stitched_video = f"b{batch_idx}_stitched.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list,
        "-c", "copy",
        stitched_video
    ], check=True)

    output_video = f"b{batch_idx}_final_short.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-i", stitched_video,
        "-i", audio_path,
        "-vf", f"ass={ass_path}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_video
    ], check=True)

    print(f"  Uploading to [{ch_name}] as Unlisted...")
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
    request = yt_clients[ch_name].videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    video_id = response["id"]
    print(f"  UNLISTED UPLOAD READY on [{ch_name}]! https://youtube.com/shorts/{video_id}")

    current_item["status"] = "published"
    current_item["language"] = item_lang
    current_item["scenes_generated"] = len(scene_images)
    current_item["video_id"] = video_id

if DRY_RUN:
    print("\nDRY RUN PASSED! All target channel tokens validated at $0.00 cost.")
    raise SystemExit(0)

with open("topics.json", "w", encoding="utf-8") as f:
    json.dump(topics, f, indent=2, ensure_ascii=False)
