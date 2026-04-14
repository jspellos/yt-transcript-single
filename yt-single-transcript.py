"""
YouTube Transcript Grabber — Streamlit App
============================================
Paste a YouTube URL, get a downloadable markdown transcript.
Uses yt-dlp for both metadata and captions — no API key needed.

Setup:
  pip install streamlit yt-dlp anthropic
  streamlit run yt_transcript_app.py
"""

import re
import subprocess
import tempfile
import os
from datetime import datetime

import streamlit as st
import anthropic


# ── Page config ──────────────────────────────────────────────
st.set_page_config(
    page_title="YouTube Transcript Grabber",
    page_icon="🎬",
    layout="centered",
)

# ── Minimal custom styling ───────────────────────────────────
st.markdown("""
<style>
    .stApp { max-width: 720px; margin: 0 auto; }
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

st.title("🎬 YouTube Transcript Grabber")
st.caption("Paste a YouTube URL below to extract the transcript as a downloadable markdown file.")


# ── Helpers ──────────────────────────────────────────────────

# Anthropic API key — set here or as environment variable ANTHROPIC_API_KEY
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")


def generate_synopsis(transcript: str, title: str) -> str | None:
    """Send the transcript to Claude Haiku for a 50-word synopsis."""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        # Send first ~2,000 words to keep it fast and cheap
        words = transcript.split()
        excerpt = " ".join(words[:2000])

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": (
                    f"Here is the transcript of a YouTube video titled \"{title}\".\n\n"
                    f"{excerpt}\n\n"
                    "Write a synopsis of this video in exactly 50 words. "
                    "Be specific about what is covered — no filler phrases. "
                    "Return only the synopsis, nothing else."
                ),
            }],
        )
        return response.content[0].text.strip()
    except Exception:
        return None

def extract_video_id(url: str) -> str | None:
    """Pull the video ID from various YouTube URL formats."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/|/embed/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',
    ]
    for p in patterns:
        m = re.search(p, url.strip())
        if m:
            return m.group(1)
    return None


def fetch_metadata(video_id: str) -> dict | None:
    """Use yt-dlp to grab video metadata (no download)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        result = subprocess.run(
            [
                "python", "-m", "yt_dlp",
                "--dump-json",
                "--skip-download",
                "--no-warnings",
                url,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None

        import json
        data = json.loads(result.stdout)
        duration_sec = data.get("duration", 0)
        if duration_sec >= 3600:
            dur = f"{duration_sec // 3600}h {(duration_sec % 3600) // 60}m"
        elif duration_sec >= 60:
            dur = f"{duration_sec // 60}m {duration_sec % 60}s"
        else:
            dur = f"{duration_sec}s"

        upload_date = data.get("upload_date", "")
        if upload_date:
            upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

        return {
            "title": data.get("title", "Unknown"),
            "channel": data.get("channel", data.get("uploader", "Unknown")),
            "upload_date": upload_date,
            "duration": dur,
            "view_count": f"{data.get('view_count', 0):,}",
            "url": url,
        }
    except Exception:
        return None


def fetch_transcript(video_id: str) -> str | None:
    """Use yt-dlp to download auto-generated captions and return clean text."""
    url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmp:
        out_template = os.path.join(tmp, "subs")
        try:
            result = subprocess.run(
                [
                    "python", "-m", "yt_dlp",
                    "--write-auto-sub",
                    "--sub-lang", "en",
                    "--skip-download",
                    "--sub-format", "vtt",
                    "--no-warnings",
                    "-o", out_template,
                    url,
                ],
                capture_output=True, text=True, timeout=60,
            )

            # Find the VTT file
            vtt_path = None
            for f in os.listdir(tmp):
                if f.endswith(".vtt"):
                    vtt_path = os.path.join(tmp, f)
                    break

            if not vtt_path:
                return None

            return vtt_to_plain_text(vtt_path)

        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None


def vtt_to_plain_text(vtt_path: str) -> str:
    """Convert a VTT subtitle file to clean plain text."""
    with open(vtt_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Remove VTT header
    content = re.sub(r"WEBVTT\n.*?\n\n", "", content, flags=re.DOTALL)
    # Remove timestamp lines
    content = re.sub(
        r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}.*\n", "", content
    )
    # Remove markup tags
    content = re.sub(r"<[^>]+>", "", content)

    # De-duplicate overlapping caption lines
    seen = set()
    unique = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            unique.append(stripped)

    # Group into paragraphs (~10 lines each)
    text = ""
    for i, line in enumerate(unique):
        text += line + " "
        if (i + 1) % 10 == 0:
            text += "\n\n"

    return text.strip()


def build_markdown(meta: dict, transcript: str, synopsis: str = None) -> str:
    """Assemble the final markdown content."""
    lines = [
        f"# {meta['title']}",
        "",
        f"**Channel:** {meta['channel']}",
        f"**Published:** {meta['upload_date']}",
        f"**Duration:** {meta['duration']}",
        f"**Views:** {meta['view_count']}",
        f"**URL:** {meta['url']}",
        "",
    ]
    if synopsis:
        lines += [
            f"**Synopsis:** {synopsis}",
            "",
        ]
    lines += [
        "---",
        "",
        "## Transcript",
        "",
        transcript,
    ]
    return "\n".join(lines)


# ── UI ───────────────────────────────────────────────────────

url_input = st.text_input(
    "YouTube URL",
    placeholder="https://www.youtube.com/watch?v=...",
    label_visibility="collapsed",
)

go = st.button("Get Transcript", type="primary", use_container_width=True)

if go:
    if not url_input.strip():
        st.error("Please paste a YouTube URL above.")
    else:
        video_id = extract_video_id(url_input)
        if not video_id:
            st.error("That doesn't look like a valid YouTube URL. Check the link and try again.")
        else:
            with st.spinner("Fetching video info…"):
                meta = fetch_metadata(video_id)

            if not meta:
                st.error("Couldn't retrieve video details. The video may be private, age-restricted, or the URL may be incorrect.")
            else:
                st.success(f"**{meta['title']}**  \n{meta['channel']}  ·  {meta['duration']}  ·  {meta['view_count']} views")

                with st.spinner("Extracting transcript — this may take a moment…"):
                    transcript = fetch_transcript(video_id)

                if not transcript:
                    st.error("No English captions available for this video. The creator may not have enabled auto-generated subtitles.")
                else:
                    # Generate a 50-word synopsis
                    synopsis = None
                    if ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "YOUR_API_KEY_HERE":
                        with st.spinner("Generating synopsis…"):
                            synopsis = generate_synopsis(transcript, meta["title"])
                        if synopsis:
                            st.info(f"**Synopsis:** {synopsis}")

                    md_content = build_markdown(meta, transcript, synopsis)

                    # Build a clean filename
                    safe_title = re.sub(r'[<>:"/\\|?*]', "", meta["title"])[:80]
                    filename = f"{meta['upload_date']}_{meta['channel']}_{safe_title}.md"

                    st.download_button(
                        label="⬇️  Download Transcript (.md)",
                        data=md_content,
                        file_name=filename,
                        mime="text/markdown",
                        use_container_width=True,
                    )

                    with st.expander("Preview transcript"):
                        st.markdown(md_content)