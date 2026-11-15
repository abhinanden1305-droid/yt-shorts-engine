import os
import json
import subprocess
from datetime import datetime, timezone, timedelta
from PIL import Image
import gspread
from google import genai
from google.genai import types
from google.cloud import texttospeech
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
VIDEO_IDEA = os.environ.get("VIDEO_IDEA", "").strip()
VIDEO_COUNT = max(1, min(int(os.environ.get("VIDEO_COUNT", "3")), 5))
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "Auto-Detect from Idea").strip()
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
CHARACTER_REF_PATH = "character.png"

if DRY_RUN:
    print("=== DRY RUN MODE ENABLED (Skipping image gen, FFmpeg render, YouTube upload & Sheet tick) ===")

CHANNEL_CONFIG = {
    "Bhakti Marg": {
        "env_secret": "YT_TOKEN_BHAKTI_MARG",
        "niche_desc": "Hindu spirituality, sacred temples, deities, mantras, and devotional mythology",
        "style_guide": "Reverent, mystical, devotional storytelling with sacred temple lighting and divine cosmic aesthetics.",
        "character_style": "wearing traditional saffron and cream silk devotional kurta with subtle tilak and rudraksha beads, standing in a warm diya-lit ancient Hindu temple courtyard"
    },
    "Biography of Hindu Saints": {
        "env_secret": "YT_TOKEN_HINDU_SAINTS",
        "niche_desc": "Life stories, miracles, teachings, and spiritual journeys of Hindu saints, yogis, and gurus",
        "style_guide": "Biographical, inspiring, historically grounded storytelling highlighting the saint's life, ashram, and core spiritual message.",
        "character_style": "wearing a serene off-white khadi linen kurta with a warm, wise storyteller expression, seated in a peaceful Himalayan ashram library at golden hour"
    },
    "The Lean Bites": {
        "env_secret": "YT_TOKEN_LEAN_BITES",
        "niche_desc": "High-protein vegetarian and egg-inclusive diets, muscle-building nutrition, healthy low-glycemic recipes, and fat-loss science",
        "style_guide": "Crisp, practical, science-backed nutrition storytelling with appetizing macro-friendly food photography and clean vibrant visuals.",
        "character_style": "wearing a crisp modern fitted dark-olive athletic t-shirt with an energetic, trustworthy nutrition coach demeanor, standing in a bright modern kitchen with fresh high-protein ingredients"
    },
    "I am Abhinanden": {
        "env_secret": "YOUTUBE_TOKEN_JSON",
        "niche_desc": "General stories, personal insights, experiments, and miscellaneous educational topics",
        "style_guide": "Engaging, clear, modern storytelling with high-contrast cinematic visuals.",
        "character_style": "wearing smart-casual modern jacket in a sleek, warmly lit studio background"
    }
}

SHEET_TABS = ["Bhakti Marg", "Biography of Hindu Saints", "The Lean Bites"]

VOICE_MAP = {
    "Hindi": {
        "tts_code": "hi-IN",
        "voice_name": "hi-IN-Neural2-B",
        "font": "Noto Sans Devanagari",
        "script_instruction": "Write in natural, engaging spoken Hindi (Devanagari script), keeping #Shorts in English."
    },
    "English": {
        "tts_code": "en-IN",
        "voice_name": "en-IN-Neural2-D",
        "font": "Noto Sans",
        "script_instruction": "Write in natural, gripping Indian English."
    },
    "Bengali": {
        "tts_code": "bn-IN",
        "voice_name": "bn-IN-Wavenet-B",
        "font": "Noto Sans Bengali",
        "script_instruction": "Write in natural, engaging spoken Bengali (Bengali script), keeping #Shorts in English."
    }
}

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
character_ref_img = Image.open(CHARACTER_REF_PATH) if os.path.exists(CHARACTER_REF_PATH) else None
if character_ref_img:
    print(f"Loaded character reference image: {CHARACTER_REF_PATH}")

def get_sheets_client():
    if not GOOGLE_SHEET_ID:
        return None
    sa_creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(sa_creds)
    return gc.open_by_key(GOOGLE_SHEET_ID)

def resolve_channel(idea_text):
    if TARGET_CHANNEL in CHANNEL_CONFIG:
        return TARGET_CHANNEL
    route_prompt = f"""
    Classify this video idea into the SINGLE best matching YouTube channel from these 4 options:
    1. "Bhakti Marg" -> Hindu spirituality, gods/goddesses, temples, rituals, Puranic stories.
    2. "Biography of Hindu Saints" -> Biographies, life stories, and teachings of specific saints, sages, or gurus.
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
    if creds.valid is False and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)

env_lang = os.environ.get("TARGET_LANGUAGE", "Hindi").strip()
selected_lang = env_lang if env_lang in VOICE_MAP else "Hindi"
spreadsheet = get_sheets_client()

batch_items = []
if VIDEO_IDEA:
    routed_channel = resolve_channel(VIDEO_IDEA)
    print(f"Manual Idea '{VIDEO_IDEA}' routed to [{routed_channel}] | Count: {VIDEO_COUNT}")
    if VIDEO_COUNT == 1:
        batch_items.append({"channel": routed_channel, "series": "", "topic": VIDEO_IDEA, "language": selected_lang, "custom_script": "", "sheet_ws": None, "row_num": None})
    else:
        split_prompt = (
            f"Break this broad video idea for '{routed_channel}' ({CHANNEL_CONFIG[routed_channel]['niche_desc']}) "
            f"into {VIDEO_COUNT} distinct, non-overlapping YouTube Shorts topics: '{VIDEO_IDEA}'. "
            "Return ONLY a JSON array of strings."
        )
        split_resp = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=split_prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        for sub in json.loads(split_resp.text)[:VIDEO_COUNT]:
            batch_items.append({"channel": routed_channel, "series": VIDEO_IDEA, "topic": sub, "language": selected_lang, "custom_script": "", "sheet_ws": None, "row_num": None})
elif spreadsheet:
    tabs_to_scan = [TARGET_CHANNEL] if TARGET_CHANNEL in SHEET_TABS else SHEET_TABS
    per_tab_queues = {}
    for tab_name in tabs_to_scan:
        ws = spreadsheet.worksheet(tab_name)
        rows = ws.get_all_values()
        unchecked = []
        for row_idx, row in enumerate(rows[1:], start=2):
            published_val = row[0].strip().upper() if len(row) > 0 else ""
            series_val = row[1].strip() if len(row) > 1 else ""
            episode_val = row[2].strip() if len(row) > 2 else ""
            lang_val = row[3].strip() if len(row) > 3 and row[3].strip() in VOICE_MAP else selected_lang
            custom_script_val = row[6].strip() if len(row) > 6 else ""
            if episode_val and published_val != "TRUE":
                unchecked.append({
                    "channel": tab_name,
                    "series": series_val,
                    "topic": f"{series_val} - {episode_val}" if series_val else episode_val,
                    "language": lang_val,
                    "custom_script": custom_script_val,
                    "sheet_ws": ws,
                    "row_num": row_idx
                })
        per_tab_queues[tab_name] = unchecked

    while len(batch_items) < VIDEO_COUNT and any(per_tab_queues.values()):
        for tab_name in tabs_to_scan:
            if per_tab_queues[tab_name] and len(batch_items) < VIDEO_COUNT:
                batch_items.append(per_tab_queues[tab_name].pop(0))

    if not batch_items:
        print("All episodes in the Google Sheet are already ticked (TRUE)! Add new rows to continue.")
        raise SystemExit(0)
else:
    raise RuntimeError("No VIDEO_IDEA provided and GOOGLE_SHEET_ID secret is not configured.")

tts_client = texttospeech.TextToSpeechClient()
yt_clients = {}
for item in batch_items:
    ch = item["channel"]
    if ch not in yt_clients:
        print(f"Validating YouTube OAuth token for channel: [{ch}]...")
        yt_clients[ch] = get_youtube_client(ch)

def fmt_ass_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int((sec - int(sec)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

ist_tz = timezone(timedelta(hours=5, minutes=30))
today_ist = datetime.now(ist_tz).strftime("%Y-%m-%d")

for batch_idx, current_item in enumerate(batch_items, start=1):
    ch_name = current_item["channel"]
    ch_cfg = CHANNEL_CONFIG[ch_name]
    series_name = current_item["series"]
    topic_title = current_item["topic"]
    item_lang = current_item["language"]
    custom_script = current_item["custom_script"]
    item_cfg = VOICE_MAP.get(item_lang, VOICE_MAP["Hindi"])

    print(f"\n--- [{batch_idx}/{len(batch_items)}] Channel: {ch_name} | Lang: {item_lang} | Episode: {topic_title} ---")

    if custom_script:
        print("Using your Custom Script from Column G!")
        script_prompt = f"""
        You are given a pre-written spoken narration script for a YouTube Short.
        Target Channel: "{ch_name}" ({ch_cfg['niche_desc']})
        Visual & Tone Style: {ch_cfg['style_guide']}
        Episode Topic: "{topic_title}"
        Pre-written Narration: "{custom_script}"
        Metadata Language Rule: {item_cfg["script_instruction"]}

        Create YouTube metadata (yt_title, yt_description, yt_tags) and 4 chronological visual scene prompts matching the exact flow of the Pre-written Narration above.

        Return ONLY valid JSON with these exact keys:
        {{
          "yt_title": "Catchy title under 70 chars including #Shorts and 1 niche hashtag",
          "yt_description": "2-sentence engaging summary + 4 relevant hashtags including #Shorts",
          "yt_tags": ["tag1", "tag2", "tag3", "tag4", "Shorts"],
          "scene_prompts": [
            "Scene 1 (Hook): Vertical 9:16 ultra-detailed cinematic visual in English matching the opening hook, {ch_cfg['style_guide']}, 8k quality, strictly no text, letters, or watermarks",
            "Scene 2 (Setup): Vertical 9:16 ultra-detailed cinematic visual in English matching the second part of the narration with consistent style, 8k quality, strictly no text, letters, or watermarks",
            "Scene 3 (Climax): Vertical 9:16 ultra-detailed cinematic visual in English matching the climax of the narration, 8k quality, strictly no text, letters, or watermarks",
            "Scene 4 (Resolution): Vertical 9:16 ultra-detailed cinematic visual in English matching the ending takeaway, {ch_cfg['style_guide']}, 8k quality, strictly no text, letters, or watermarks"
          ]
        }}
        """
    else:
        series_rule = (
            f'- Series Continuity: This video is an episode in the series "{series_name}". '
            f'Reference the series naturally in the hook and end with a crisp cliffhanger inviting viewers to follow for the next part.'
            if series_name else ""
        )
        script_prompt = f"""
        Create a gripping, high-retention 45-second YouTube Short script with a 4-scene visual storyboard.
        Target Channel: "{ch_name}" ({ch_cfg['niche_desc']})
        Visual & Tone Style: {ch_cfg['style_guide']}
        Episode Topic: "{topic_title}"
        Language Rule: Write the narration, yt_title, and yt_description — {item_cfg["script_instruction"]}

        Guidelines:
        {series_rule}
        - Hook (0-5s): A bold opening question, surprising fact, or dramatic revelation.
        - Body (5-38s): Vivid, fast-paced storytelling with clear, authentic takeaways.
        - Closing CTA (38-45s): Memorable final thought and a natural prompt inviting viewers to comment.
        - Break the visual progression into 4 distinct chronological scenes matching the narration flow, keeping consistent style across all scenes.

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
            "Scene 4 (Resolution): Vertical 9:16 ultra-detailed cinematic visual in English showing the powerful ending takeaway, {ch_cfg['style_guide']}, 8k quality, strictly no text, letters, or watermarks"
          ]
        }}
        """

    story_resp = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=script_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    story_data = json.loads(story_resp.text)
    final_narration = custom_script if custom_script else story_data["narration"]
    scene_prompts = story_data.get("scene_prompts", [])[:5]
    if len(scene_prompts) < 3:
        raise RuntimeError(f"Expected at least 3 scene prompts, got {len(scene_prompts)}")

    print("Title:", story_data["yt_title"])
    print(f"Scenes planned: {len(scene_prompts)}")

    if DRY_RUN:
        print("Narration preview:", final_narration[:140] + "...")
        continue

    scene_images = []
    for s_idx, prompt in enumerate(scene_prompts, start=1):
        use_character = character_ref_img is not None and s_idx in (1, len(scene_prompts))
        if use_character:
            print(f"  Painting Scene {s_idx}/{len(scene_prompts)} with [{ch_name}] styled character...")
            char_prompt = (
                f"Maintain the exact facial identity, features, and likeness of the person in the attached reference image. "
                f"Show this exact person as an engaging host presenting directly to the camera, {ch_cfg['character_style']}. "
                f"Scene context: {prompt}. Vertical 9:16 framing, medium close-up portrait, 8k cinematic lighting, strictly no text or watermarks."
            )
            gen_contents = [character_ref_img, char_prompt]
        else:
            print(f"  Painting Scene {s_idx}/{len(scene_prompts)}...")
            gen_contents = prompt

        img_resp = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=gen_contents,
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
    synthesis_input = texttospeech.SynthesisInput(text=final_narration)
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

    words = final_narration.split()
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
    short_url = f"https://youtube.com/shorts/{video_id}"
    print(f"  UNLISTED UPLOAD READY on [{ch_name}]! {short_url}")

    if current_item["sheet_ws"] and current_item["row_num"]:
        ws = current_item["sheet_ws"]
        r = current_item["row_num"]
        ws.update(f"A{r}", [[True]], value_input_option="USER_ENTERED")
        ws.update(f"E{r}:F{r}", [[short_url, today_ist]], value_input_option="USER_ENTERED")
        print(f"  Ticked checkbox in Google Sheet tab '{ch_name}' Row {r}!")

if DRY_RUN:
    print(f"\nDRY RUN PASSED! Queued {len(batch_items)} episode(s) from Google Sheet ($0.00 cost).")
    raise SystemExit(0)
