import random
import csv
import os
import sys
from datetime import datetime, timedelta

# Optional extras
try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    from youtubesearchpython import VideosSearch
except ImportError:
    VideosSearch = None


# === CONFIG ===
KEYWORDS = ["full stack", "mern stack", "mern", "website","website development","web development"]
VIDEO_LIMIT = 10
FEEDBACK_FILE = "yt_feedback.csv"
MIN_DURATION = 60  # Skip Shorts
BACKEND = "yt_dlp"  # yt_dlp | youtubesearch
LANG_WHITELIST = ["en", "hi"]  # English, Hindi


# === Summarizer ===
def get_transcript_summary(video_id):
    """Try to fetch transcript and summarize it."""
    if YouTubeTranscriptApi is None:
        return None
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=LANG_WHITELIST)
        text = " ".join([t["text"] for t in transcript[:40]])  # first ~40 lines
        return summarize_text(text)
    except Exception:
        return None


def summarize_text(text, max_len=220):
    """Very simple summarizer: cut + compress sentences."""
    sentences = text.replace("\n", " ").split(". ")
    if len(sentences) > 4:
        sentences = sentences[:4]
    summary = ". ".join(sentences)
    return summary[:max_len] + ("..." if len(summary) > max_len else "")


# === Fetch videos using yt_dlp ===
def fetch_videos_yt_dlp(keywords, limit=10):
    if yt_dlp is None:
        print("❌ yt_dlp not installed. Run: pip install yt-dlp")
        sys.exit(1)

    all_videos = []
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for kw in keywords:
            search = f"ytsearch{limit}:{kw}"
            try:
                results = ydl.extract_info(search, download=False)
            except Exception as e:
                print(f"⚠️ Error fetching {kw}: {e}")
                continue
            for e in results.get("entries", []):
                duration = e.get("duration") or 0
                if duration < MIN_DURATION:
                    continue
                # Language check (yt_dlp sometimes provides "language" field)
                lang = e.get("language")
                if lang and lang.split("-")[0] not in LANG_WHITELIST:
                    continue
                vid = {
                    "keyword": kw,
                    "title": e.get("title", "No Title"),
                    "link": f"https://www.youtube.com/watch?v={e['id']}",
                    "id": e["id"],
                    "channel": e.get("channel", "Unknown"),
                    "description": e.get("description", "") or "",
                    "duration": duration,
                    "upload_date": e.get("upload_date"),  # YYYYMMDD
                    "language": lang or "unknown",
                }
                all_videos.append(vid)
    return all_videos


# === Fetch videos using youtubesearchpython ===
def fetch_videos_ytsp(keywords, limit=10):
    if VideosSearch is None:
        print("❌ youtubesearchpython not installed. Run: pip install youtube-search-python")
        sys.exit(1)

    all_videos = []
    for kw in keywords:
        try:
            search = VideosSearch(kw, limit=limit)
            results = search.result()["result"]
        except Exception as e:
            print(f"⚠️ Error fetching {kw}: {e}")
            continue
        for v in results:
            duration_str = v.get("duration", "0:00")
            try:
                parts = list(map(int, duration_str.split(":")))
                duration = sum(x * 60**i for i, x in enumerate(reversed(parts)))
            except:
                duration = 0
            if duration < MIN_DURATION:
                continue
            vid = {
                "keyword": kw,
                "title": v.get("title", "No Title"),
                "link": v.get("link", ""),
                "id": v.get("id", ""),
                "channel": v.get("channel", {}).get("name", "Unknown"),
                "description": (v.get("descriptionSnippet") or [{}])[0].get("text", ""),
                "duration": duration,
                "upload_date": None,
                "language": "unknown",
            }
            all_videos.append(vid)
    return all_videos


# === Load feedback ===
def load_feedback():
    if not os.path.isfile(FEEDBACK_FILE):
        return {}
    feedback = {}
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            feedback[row["link"]] = row
    return feedback


# === Save feedback ===
def save_feedback(video, feedback, summary=None):
    file_exists = os.path.isfile(FEEDBACK_FILE)
    with open(FEEDBACK_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "keyword", "title", "link", "channel",
            "duration", "feedback", "summary", "upload_date", "language"
        ])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now().isoformat(),
            "keyword": video["keyword"],
            "title": video["title"],
            "link": video["link"],
            "channel": video["channel"],
            "duration": video["duration"],
            "feedback": feedback,
            "summary": summary or "",
            "upload_date": video.get("upload_date", ""),
            "language": video.get("language", ""),
        })


# === Pick video smartly ===
def pick_video(videos, feedback_memory):
    candidates = [v for v in videos if v["link"] not in feedback_memory]
    if not candidates:
        return None

    weights = []
    for v in candidates:
        base = 1
        # Keyword boost
        for fb in feedback_memory.values():
            if fb["keyword"] == v["keyword"]:
                if fb["feedback"] == "definitely":
                    base += 3
                elif fb["feedback"] == "maybe":
                    base += 1
                elif fb["feedback"] == "never":
                    base = 0
        # Recency boost (last 6 months)
        if v.get("upload_date"):
            try:
                upload_dt = datetime.strptime(v["upload_date"], "%Y%m%d")
                if upload_dt > datetime.now() - timedelta(days=180):
                    base += 2
            except:
                pass
        weights.append(base)

    candidates = [v for v, w in zip(candidates, weights) if w > 0]
    weights = [w for w in weights if w > 0]

    if not candidates:
        return None
    return random.choices(candidates, weights=weights, k=1)[0]


# === Main loop ===
def interactive_loop(videos):
    feedback_memory = load_feedback()

    while True:
        video = pick_video(videos, feedback_memory)
        if not video:
            print("\n🎉 No more new videos to recommend. Come back later!")
            break

        # Try AI summary
        summary = get_transcript_summary(video["id"]) or summarize_text(
            video.get("description") or video["title"]
        )

        print("\n🎥 Recommended Video:")
        print("Title:", video["title"])
        print("Channel:", video["channel"])
        print("Duration:", f"{video['duration']}s")
        if video.get("upload_date"):
            print("Uploaded:", video["upload_date"])
        print("Language:", video.get("language", "unknown"))
        print("Link:", video["link"])
        print("Summary:", summary, "\n")

        feedback = input("Do you want to watch it? (never/maybe/definitely/quit): ").strip().lower()
        if feedback == "quit":
            break
        elif feedback in ["never", "maybe", "definitely"]:
            save_feedback(video, feedback, summary)
            feedback_memory[video["link"]] = video | {"feedback": feedback}
            print("✅ Feedback saved!\n")
        else:
            print("⚠️ Invalid input. Try again.")


if __name__ == "__main__":
    if BACKEND == "yt_dlp":
        videos = fetch_videos_yt_dlp(KEYWORDS, limit=VIDEO_LIMIT)
    else:
        videos = fetch_videos_ytsp(KEYWORDS, limit=VIDEO_LIMIT)

    interactive_loop(videos)
import random
import csv
import os
import sys
from datetime import datetime

# Try backend imports
try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    from youtubesearchpython import VideosSearch
except ImportError:
    VideosSearch = None

# === CONFIG ===
KEYWORDS = ["mern stack", "full stack", "web development", "website development"]
VIDEO_LIMIT = 10
FEEDBACK_FILE = "yt_feedback.csv"
MIN_DURATION = 60  # Skip Shorts (<60s)
BACKEND = "yt_dlp"  # options: yt_dlp | youtubesearch


# === Fetch videos using yt_dlp ===
def fetch_videos_yt_dlp(keywords, limit=10):
    if yt_dlp is None:
        print("❌ yt_dlp not installed. Run: pip install yt-dlp")
        sys.exit(1)

    all_videos = []
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for kw in keywords:
            search = f"ytsearch{limit}:{kw}"
            try:
                results = ydl.extract_info(search, download=False)
            except Exception as e:
                print(f"⚠️ Error fetching {kw}: {e}")
                continue
            for e in results.get("entries", []):
                duration = e.get("duration") or 0
                if duration < MIN_DURATION:
                    continue
                all_videos.append({
                    "keyword": kw,
                    "title": e.get("title", "No Title"),
                    "link": f"https://www.youtube.com/watch?v={e['id']}",
                    "channel": e.get("channel", "Unknown"),
                    "description": e.get("description", "") or "",
                    "duration": duration,
                })
    return all_videos


# === Fetch videos using youtubesearchpython ===
def fetch_videos_ytsp(keywords, limit=10):
    if VideosSearch is None:
        print("❌ youtubesearchpython not installed. Run: pip install youtube-search-python")
        sys.exit(1)

    all_videos = []
    for kw in keywords:
        try:
            search = VideosSearch(kw, limit=limit)
            results = search.result()["result"]
        except Exception as e:
            print(f"⚠️ Error fetching {kw}: {e}")
            continue
        for v in results:
            duration_str = v.get("duration", "0:00")
            # Convert duration string to seconds
            try:
                parts = list(map(int, duration_str.split(":")))
                duration = sum(x * 60**i for i, x in enumerate(reversed(parts)))
            except:
                duration = 0
            if duration < MIN_DURATION:
                continue
            all_videos.append({
                "keyword": kw,
                "title": v.get("title", "No Title"),
                "link": v.get("link", ""),
                "channel": v.get("channel", {}).get("name", "Unknown"),
                "description": (v.get("descriptionSnippet") or [{}])[0].get("text", ""),
                "duration": duration,
            })
    return all_videos


# === Load feedback ===
def load_feedback():
    if not os.path.isfile(FEEDBACK_FILE):
        return {}
    feedback = {}
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            feedback[row["link"]] = row
    return feedback


# === Save feedback ===
def save_feedback(video, feedback):
    file_exists = os.path.isfile(FEEDBACK_FILE)
    with open(FEEDBACK_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "keyword", "title", "link", "channel", "duration", "feedback"
        ])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now().isoformat(),
            "keyword": video["keyword"],
            "title": video["title"],
            "link": video["link"],
            "channel": video["channel"],
            "duration": video["duration"],
            "feedback": feedback
        })


# === Pick video smartly ===
def pick_video(videos, feedback_memory):
    candidates = [v for v in videos if v["link"] not in feedback_memory]
    if not candidates:
        return None

    # Build weights
    weights = []
    for v in candidates:
        base = 1
        # Boost based on past feedback on the same keyword
        for fb in feedback_memory.values():
            if fb["keyword"] == v["keyword"]:
                if fb["feedback"] == "definitely":
                    base += 3
                elif fb["feedback"] == "maybe":
                    base += 1
                elif fb["feedback"] == "never":
                    base = 0  # exclude
        weights.append(base)

    # Filter out zero-weight
    candidates = [v for v, w in zip(candidates, weights) if w > 0]
    weights = [w for w in weights if w > 0]

    if not candidates:
        return None
    return random.choices(candidates, weights=weights, k=1)[0]


# === Main loop ===
def interactive_loop(videos):
    feedback_memory = load_feedback()

    while True:
        video = pick_video(videos, feedback_memory)
        if not video:
            print("\n🎉 No more new videos to recommend. Come back later!")
            break

        print("\n🎥 Recommended Video:")
        print("Title:", video["title"])
        print("Channel:", video["channel"])
        print("Duration:", f"{video['duration']/60}m")
        print("Link:", video["link"])
        if video["description"]:
            print("Description:", video["description"][:200], "...\n")

        feedback = input("Do you want to watch it? (n/m/y/q): ").strip().lower()
        if feedback == "q":
            break
        elif feedback in ["n", "m", "y"]:
            save_feedback(video, feedback)
            feedback_memory[video["link"]] = video | {"feedback": feedback}
            print("✅ Feedback saved!\n")
        else:
            print("⚠️ Invalid input. Try again.")


if __name__ == "__main__":
    if BACKEND == "yt_dlp":
        videos = fetch_videos_yt_dlp(KEYWORDS, limit=VIDEO_LIMIT)
    else:
        videos = fetch_videos_ytsp(KEYWORDS, limit=VIDEO_LIMIT)

    interactive_loop(videos)
