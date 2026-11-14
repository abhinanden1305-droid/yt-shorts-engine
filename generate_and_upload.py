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
    token_info = json.loads(raw_token)
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
    ch = item
