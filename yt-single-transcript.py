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
import tempfile
import os
from datetime import datetime

import streamlit as st
import anthropic
import yt_dlp


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

# Anthropic API key — checks Streamlit secrets first, then environment variable
ANTHROPIC_API_KEY = ""
try:
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def generate_summary(transcript: str, title: str) -> str | None:
    """Send the transcript to Claude Haiku for a 200-word summary and 3 key points."""
    if not ANTHROPIC_API_KEY:
        st.warning("No Anthropic API key found. Summary skipped.")
        return None
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        # Send first ~3,000 words for good coverage
        words = transcript.split()
        excerpt = " ".join(words[:3000])

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": (
                    f"Here is the transcript of a YouTube video titled \"{title}\".\n\n"
                    f"{excerpt}\n\n"
                    "Provide the following:\n\n"
                    "1. A summary of approximately 200 words. Be specific about what "
                    "is covered — no filler phrases.\n\n"
                    "2. Three bullet points reflecting the key takeaways from the video.\n\n"
                    "Format your response exactly like this:\n\n"
                    "## Summary\n\n"
                    "[200-word summary here]\n\n"
                    "## Key Takeaways\n\n"
                    "- [first key point]\n"
                    "- [second key point]\n"
                    "- [third key point]\n\n"
                    "Return only the formatted content above, nothing else."
                ),
            }],
        )
        return response.content[0].text.strip()
    except Exception as e:
        st.warning(f"Summary generation failed: {e}")
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
    """Use yt-dlp Python API to grab video metadata (no download)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)

        duration_sec = data.get("duration", 0) or 0
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
    except Exception as e:
        st.error(f"yt-dlp error: {e}")
        return None


def fetch_transcript(video_id: str) -> str | None:
    """Use yt-dlp Python API to download auto-generated captions and return clean text."""
    url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmp:
        out_template = os.path.join(tmp, "subs")
        try:
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["en"],
                "subtitlesformat": "vtt",
                "outtmpl": out_template,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Find the VTT file
            vtt_path = None
            for f in os.listdir(tmp):
                if f.endswith(".vtt"):
                    vtt_path = os.path.join(tmp, f)
                    break

            if not vtt_path:
                return None

            return vtt_to_plain_text(vtt_path)

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


def build_markdown(meta: dict, transcript: str, summary: str = None) -> str:
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
    if summary:
        lines += [
            summary,
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
                    # Generate summary with key takeaways
                    summary = None
                    if ANTHROPIC_API_KEY:
                        with st.spinner("Generating summary…"):
                            summary = generate_summary(transcript, meta["title"])

                    md_content = build_markdown(meta, transcript, summary)

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

                    if summary:
                        with st.expander("Summary"):
                            st.markdown(summary)