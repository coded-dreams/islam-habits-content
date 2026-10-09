"""Checks every video in videos.json still plays embedded, via YouTube's oEmbed endpoint.

Never edits videos.json - choosing a replacement needs a person. Writes `dead-videos.md` listing
the slots whose videos are gone, private or no longer embeddable (the workflow turns that into an
issue); exit code 0 either way, non-zero only if the check itself could not run.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADERS = {"User-Agent": "islam-habits-content-checker (+https://github.com/coded-dreams/islam-habits-content)"}


def status(video_id):
    watch = f"https://www.youtube.com/watch?v={video_id}"
    url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(watch, safe="")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            return e.code
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(5)
                continue
            raise
    return None


def main():
    with open(os.path.join(ROOT, "videos.json"), encoding="utf-8") as f:
        slots = json.load(f)["slots"]
    reasons = {401: "embedding disabled", 403: "embedding disabled", 404: "removed or private", 400: "invalid id"}
    dead = []
    checked = {}
    for slot, entry in slots.items():
        for video in entry.get("videos", []):
            vid = video.get("id")
            if vid not in checked:
                checked[vid] = status(vid)
                time.sleep(0.2)
            code = checked[vid]
            if code != 200:
                title = video.get("title") or ""
                dead.append(f"- `{slot}`: [{vid}](https://www.youtube.com/watch?v={vid}) {title} - {reasons.get(code, f'HTTP {code}')}")
    print(f"Checked {len(checked)} videos, {len(dead)} problem entries")
    path = os.path.join(ROOT, "dead-videos.md")
    if dead:
        with open(path, "w", encoding="utf-8") as f:
            f.write("These videos.json entries no longer play in the app. Replace each with a new pick "
                    "(the app shows the slot's bundled video or placeholder meanwhile):\n\n" + "\n".join(dead) + "\n")
    elif os.path.exists(path):
        os.remove(path)


if __name__ == "__main__":
    main()
