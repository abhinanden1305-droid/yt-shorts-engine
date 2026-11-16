import os
import subprocess
from PIL import Image
from google import genai
from google.genai import types
from google.cloud import texttospeech

# Ensure GEMINI_API_KEY and GOOGLE_APPLICATION_CREDENTIALS are set in your environment
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
tts_client = texttospeech.TextToSpeechClient()

# Auto-detect optional character reference & background music in current directory
character_ref_img = None
bgm_path = None
for fname in os.listdir("."):
    low = fname.lower()
    if low.startswith("character.") and low.endswith((".png", ".jpg", ".jpeg", ".webp")):
        character_ref_img = Image.open(fname)
        print(f"Loaded character reference: {fname}")
    elif low == "bgm.mp3":
        bgm_path = fname
        print(f"Loaded background music: {fname}")

CHAPTERS = [
    {
        "title": "01. The $0/Month Multi-Channel Shorts Architecture",
        "use_character": True,
        "visual_prompt": (
            "Widescreen 16:9 clean modern tech studio backdrop showing glowing holographic workflow diagrams "
            "connecting a spreadsheet icon, cloud automation gears, and three YouTube play buttons, dark navy and gold accents, 8k quality, strictly no text"
        ),
        "narration": (
            "What if you could run three separate YouTube Shorts channels—in three different languages, with a consistent AI host, "
            "custom scripts, animated visuals, and studio voiceovers—publishing six Shorts every single day for literally zero dollars a month? "
            "No expensive SaaS subscriptions, no Make or Zapier bills, and no keeping your laptop running overnight. "
            "Over the last few days, I built this exact pipeline from scratch using four free tools: Google Sheets as our mission control, "
            "GitHub Actions as our free cloud server, Google's Gemini models for scripting and scene generation, and Google Cloud Text-to-Speech "
            "plus FFmpeg to assemble and upload the final vertical videos automatically. In this complete walkthrough, I will show you every step "
            "from a blank screen to a fully automated, twice-a-day multi-channel publishing machine."
        )
    },
    {
        "title": "02. Step 1: Google Cloud Project, APIs & Service Account",
        "use_character": False,
        "visual_prompt": (
            "Widescreen 16:9 sleek futuristic isometric illustration of cloud server infrastructure with three glowing API keycards "
            "and a secure golden shield lock, clean dark slate background, cinematic lighting, 8k quality, strictly no text"
        ),
        "narration": (
            "Everything starts in Google Cloud Console. First, create a clean project—let's call it shorts-pipeline—and link your billing account "
            "so you unlock the generous free monthly tiers. Next, head to the API Library and enable three exact APIs: Cloud Text-to-Speech API "
            "for our Neural2 voices, Google Sheets API so our automation bot can read episodes and tick checkboxes, and YouTube Data API v3 "
            "for automated uploads. Now we need two types of credentials. First, go to IAM and Admin, then Service Accounts, create a bot account "
            "called shorts-bot, and download its JSON key file. Copy that service account's email address—that is how our Python script logs into "
            "Google Sheets securely without a browser. Second, configure your OAuth Consent Screen as External, add your email as a Test User, "
            "add the youtube.upload scope, and create a Web Application OAuth Client ID with developers.google.com/oauthplayground as the authorized "
            "redirect URI. Save both your Client ID and Client Secret."
        )
    },
    {
        "title": "03. Step 2: Gemini API Key & Google Sheet Series Planner",
        "use_character": False,
        "visual_prompt": (
            "Widescreen 16:9 ultra-clean modern digital workspace illustration featuring an organized green grid spreadsheet "
            "with glowing checkmarks connected to an AI neural crystal, soft studio lighting, 8k quality, strictly no text"
        ),
        "narration": (
            "Next, jump over to Google AI Studio, click Get API Key, and attach it to the exact same Google Cloud project. That single key gives us "
            "access to Gemini Flash for structured JSON storyboarding and Gemini Flash Image for painting our vertical scenes. Now let's build the "
            "control center: a Google Sheet called YouTube Shorts Series Planner. Create one tab for each YouTube channel—in my case, Bhakti Marg, "
            "Biography of Hindu Saints, and The Lean Bites. Across Row 1 of every tab, set up seven columns: Column A is Published with interactive "
            "checkboxes inserted down the column, Column B is Series Name, Column C is Episode Title, Column D is Language—Hindi, English, or Bengali—"
            "Columns E and F are left blank for the auto-filled YouTube link and publish date, and Column G is Custom Script. Finally, click Share "
            "and give Editor access to your service account email."
        )
    },
    {
        "title": "04. Step 3: Multi-Channel YouTube OAuth Refresh Tokens",
        "use_character": False,
        "visual_prompt": (
            "Widescreen 16:9 digital security concept showing three glowing golden access tokens unlocking three separate red video broadcast screens, "
            "sleek dark studio background, dramatic lighting, 8k quality, strictly no text"
        ),
        "narration": (
            "Here is the trick that makes multi-channel publishing seamless. Open Google OAuth 2.0 Playground in a fresh browser tab, click the gear "
            "icon in the top right, check Use your own OAuth credentials, and paste your Client ID and Client Secret. Under Step 1, expand YouTube "
            "Data API v3 and select the youtube.upload scope directly from the list. When you click Authorize APIs, Google shows a channel selector "
            "screen. Pick Channel 1, allow access, and click Exchange authorization code for tokens to copy your long-lived refresh token starting "
            "with 1 slash slash 0. Then open a fresh OAuth Playground tab and repeat the exact same flow for Channel 2 and Channel 3. Each YouTube "
            "channel gets its own independent refresh token stored safely as a secret."
        )
    },
    {
        "title": "05. Step 4: GitHub Actions & Twice-Daily Cron Schedule",
        "use_character": False,
        "visual_prompt": (
            "Widescreen 16:9 modern cloud automation illustration showing an automated clockwork gear triggering a Python code pipeline inside a "
            "dark-mode developer server rack at 6 AM and 6 PM, glowing cyan and emerald accents, 8k quality, strictly no text"
        ),
        "narration": (
            "Now let's move our engine to the cloud for free. Create a GitHub repository called yt-shorts-engine and store all your keys inside "
            "Repository Secrets: your Gemini API key, your Service Account JSON, your Google Sheet ID, and your three channel refresh tokens. "
            "Inside the workflow YAML file, we configure an Ubuntu runner to install Python, FFmpeg, and Noto multilingual fonts so Hindi and Bengali "
            "subtitles render cleanly without broken boxes. Look at the schedule trigger: cron 30 0 and cron 30 12 in UTC—which translates to 6:00 AM IST "
            "and 6:00 PM IST every single day. Each run processes one episode per channel, totaling six Shorts a day, while using only around 400 "
            "minutes out of GitHub's 2,000 free monthly Linux minutes."
        )
    },
    {
        "title": "06. Step 5: Consistent Male AI Host Across All 3 Channels",
        "use_character": False,
        "visual_prompt": (
            "Widescreen 16:9 split-screen triptych studio showcase showing three distinct cinematic themes: a warm diya-lit temple courtyard on the left, "
            "a peaceful Himalayan ashram library in the center, and a bright modern healthy kitchen on the right, 8k quality, strictly no text"
        ),
        "narration": (
            "To give all three channels a recognizable human anchor without filming every day, I exported a single base male character portrait from "
            "Google Flow and uploaded it to the root of our GitHub repository. In our Python script, Scene 1—our opening hook—locks onto that exact "
            "facial identity using an eye-level 50-millimeter waist-up framing, while automatically styling him for each channel: a traditional saffron "
            "silk kurta in a diya-lit temple for Bhakti Marg, a calm khadi linen kurta in a Himalayan ashram for Biography of Hindu Saints, and an "
            "athletic crew-neck in a modern kitchen for The Lean Bites. Scenes 2 through 6 then cut into dynamic B-roll with alternating pan-and-zoom "
            "motion, paired with male Neural2 voiceovers, bold high-contrast subtitles, and subtle background music."
        )
    },
    {
        "title": "07. Step 6: Batching Episodes with Claude & Live Automated Run",
        "use_character": False,
        "visual_prompt": (
            "Widescreen 16:9 clean modern productivity scene showing an AI chat assistant outputting structured data rows that flow seamlessly into "
            "a cloud video rendering pipeline, warm cinematic lighting, 8k quality, strictly no text"
        ),
        "narration": (
            "How do we keep the content queue full? Once a week, I run a structured prompt in Claude that outputs a clean seven-column Markdown table "
            "with 100-to-115-word spoken narration scripts in Column G. I highlight the rows, press Copy, click into Google Sheets, and press Paste—"
            "every episode snaps straight into Columns A through G with unchecked boxes. When GitHub Actions runs—either automatically at 6:00 AM and "
            "6:00 PM or on-demand—it grabs the next unchecked episode from each tab, renders the video, uploads it as Unlisted so you can do a quick "
            "review in YouTube Studio, pastes the Shorts link into Column E, stamps today's date in Column F, and ticks the checkbox in Column A."
        )
    },
    {
        "title": "08. Quotas, Scaling Limits & Next Steps",
        "use_character": True,
        "visual_prompt": (
            "Widescreen 16:9 sleek modern studio backdrop with subtle upward growth charts and glowing checkmarks, warm golden-hour lighting, "
            "8k quality, strictly no text"
        ),
        "narration": (
            "One important tip before you scale: a single Google Cloud project gives you 10,000 YouTube API quota units per day, and each upload costs "
            "1,600 units—meaning six Shorts a day fits right inside the zero-dollar free limit. If you ever want to scale beyond six videos a day, "
            "or set up a second set of channels for another family member, simply create a separate Google Cloud project and GitHub repository so "
            "you get another independent 2,000 GitHub minutes and 10,000 daily YouTube API units. Everything runs hands-free while you sleep. "
            "Drop a comment below with the niche you're automating next, and subscribe for more end-to-end AI automation builds!"
        )
    }
]

def fmt_ass_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int((sec - int(sec)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

chapter_clips = []

for idx, ch in enumerate(CHAPTERS, start=1):
    print(f"\n=== Building Chapter {idx}/{len(CHAPTERS)}: {ch['title']} ===")

    # 1. Synthesize Chapter Narration (Male Indian English Neural2)
    synthesis_input = texttospeech.SynthesisInput(text=ch["narration"])
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-IN",
        name="en-IN-Neural2-B",
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=0.98,
    )
    tts_resp = tts_client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    audio_file = f"tut_ch_{idx}.mp3"
    with open(audio_file, "wb") as f:
        f.write(tts_resp.audio_content)

    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_file
    ]).decode().strip())

    # 2. Generate 16:9 Widescreen Visual
    if ch["use_character"] and character_ref_img is not None:
        prompt = (
            f"SUBJECT LOCK: Keep the exact facial identity, glasses/eyes, nose, jawline, and likeness of the Indian man in the reference image. "
            f"Widescreen 16:9 medium waist-up shot filmed at eye level on a 50mm lens, wearing a smart-casual dark jacket in a modern YouTube creator studio, "
            f"speaking engagingly toward the camera. Background: {ch['visual_prompt']}"
        )
        gen_contents = [character_ref_img, prompt]
    else:
        gen_contents = ch["visual_prompt"]

    img_resp = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=gen_contents,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="16:9"),
        ),
    )
    img_file = f"tut_ch_{idx}.png"
    for part in img_resp.candidates[0].content.parts:
        if part.inline_data is not None:
            with open(img_file, "wb") as f:
                f.write(part.inline_data.data)
            break

    # 3. Generate Chapter Banner + Clean Lower-Third Subtitles (ASS)
    ass_file = f"tut_ch_{idx}.ass"
    words = ch["narration"].split()
    chunk_size = 8
    chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    time_per_chunk = duration / max(len(chunks), 1)

    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Banner,Noto Sans,46,&H0000E5FF,&H00FFFFFF,&H00000000,&HAA000000,-1,0,0,0,100,100,0,0,3,14,0,7,60,60,45,1
Style: Caption,Noto Sans,44,&H00FFFFFF,&H0000E5FF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,1,3,2,2,120,120,55,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 1,0:00:00.00,{fmt_ass_time(duration)},Banner,,0,0,0,,  {ch['title']}  
"""
    with open(ass_file, "w", encoding="utf-8") as f:
        f.write(ass_header)
        for c_idx, chunk in enumerate(chunks, start=1):
            st = fmt_ass_time((c_idx - 1) * time_per_chunk)
            et = fmt_ass_time(min(c_idx * time_per_chunk, duration))
            f.write(f"Dialogue: 0,{st},{et},Caption,,0,0,0,,{chunk}\n")

    # 4. Render 1920x1080 Chapter Clip with Subtle Zoom + Overlays
    clip_dur = duration + 0.6
    frames = int(clip_dur * 30) + 5
    z_expr = "min(zoom+0.0005,1.10)" if idx % 2 == 1 else "max(1.10-0.0005*on,1.0)"
    vf = (
        f"scale=3840:2160,"
        f"zoompan=z='{z_expr}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=30,"
        f"ass={ass_file}"
    )
    clip_file = f"tut_clip_{idx}.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", img_file,
        "-i", audio_file,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{clip_dur:.3f}",
        clip_file
    ], check=True)
    chapter_clips.append(clip_file)

# 5. Concatenate All Chapters Into Final 1080p YouTube Video
with open("tut_concat.txt", "w", encoding="utf-8") as f:
    for c in chapter_clips:
        f.write(f"file '{c}'\n")

raw_merged = "tut_merged_raw.mp4"
subprocess.run([
    "ffmpeg", "-y",
    "-f", "concat", "-safe", "0", "-i", "tut_concat.txt",
    "-c", "copy",
    raw_merged
], check=True)

final_output = "youtube_tutorial_1080p.mp4"
if bgm_path:
    subprocess.run([
        "ffmpeg", "-y",
        "-i", raw_merged,
        "-stream_loop", "-1", "-i", bgm_path,
        "-filter_complex", "[1:a]volume=0.10[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        final_output
    ], check=True)
else:
    os.replace(raw_merged, final_output)

print(f"\nSUCCESS! Full 1080p YouTube tutorial exported to: {final_output}")
