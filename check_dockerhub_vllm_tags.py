#!/usr/bin/env python3
"""Docker Hub tag watchdog for voipmonitor/vllm.

Fetches the newest tags, records them in a SQLite DB (name -> seen),
and prints ONLY tags that were not seen before. Prints nothing when
there is nothing new (watchdog contract for no_agent cron delivery:
empty stdout = silent tick).

DB lives at ~/data/vllm_tags.db by default (overridable with $VLLM_DB).
Run once at setup to seed the baseline (prints nothing); every run
after that reports only genuinely new tags.
"""
import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone

REPO = "voipmonitor/vllm"
API = os.environ.get(
    "VLLM_API",
    "https://hub.docker.com/v2/repositories/{}/tags?page_size=100".format(REPO),
)
DB_PATH = os.environ.get("VLLM_DB", os.path.expanduser("~/data/vllm_tags.db"))
LOG_PATH = os.path.expanduser("~/data/vllm_tags.log")
MAX_PAGES = 10
REQUEST_TIMEOUT = 30


def log(msg):
    try:
        with open(LOG_PATH, "a") as f:
            f.write("{} {}\n".format(datetime.now(timezone.utc).isoformat(), msg))
    except OSError:
        pass


def fetch_page(page):
    """Return (results, has_next) or (None, False) on transient failure."""
    url = "{}&page={}".format(API, page)
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as resp:
            data = json.load(resp)
        return data.get("results") or [], bool(data.get("next"))
    except Exception as exc:  # noqa: BLE001 - transient API failure must not page the user
        log("fetch failed page {}: {}".format(page, exc))
        return None, False


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tags ("
        " name TEXT PRIMARY KEY,"
        " pushed TEXT,"
        " first_seen TEXT)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    def meta_get(key, default=None):
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def meta_set(key, value):
        conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    watermark = meta_get("newest_pushed", "") or ""
    now_iso = datetime.now(timezone.utc).isoformat()

    new_tags = []
    newest = watermark
    hit_old = False

    for page in range(1, MAX_PAGES + 1):
        results, has_next = fetch_page(page)
        if results is None:  # fetch failed -> behave like a quiet tick
            conn.close()
            log("aborting scan: fetch failed on page {}".format(page))
            return 0
        for t in results:
            name = t.get("name") or ""
            pushed = t.get("tag_last_pushed") or ""
            if pushed > newest:
                newest = pushed
            if not name:
                continue
            seen = conn.execute("SELECT 1 FROM tags WHERE name=?", (name,)).fetchone()
            if seen:
                continue
            new_tags.append((name, pushed))
            conn.execute(
                "INSERT OR IGNORE INTO tags(name,pushed,first_seen) VALUES(?,?,?)",
                (name, pushed, now_iso),
            )
        # API sorts newest-first; once we see a tag older than the
        # watermark, every later tag is older too -> stop paginating.
        if watermark and any((t.get("tag_last_pushed") or "") < watermark for t in results):
            hit_old = True
        if hit_old or not has_next:
            break

    conn.commit()
    if newest != watermark:
        meta_set("newest_pushed", newest)
    conn.commit()
    conn.close()

    if new_tags:
        new_tags.sort(key=lambda x: x[1], reverse=True)
        lines = ["{} new {}/{} image(s):".format(len(new_tags), REPO.split("/")[0], REPO.split("/")[1]), ""]
        for name, pushed in new_tags:
            ts = "unknown time"
            if pushed:
                # strip fractional seconds: 2026-08-15T12:34:56.789Z -> 2026-08-15 12:34:56 UTC
                ts = pushed.split(".")[0].replace("T", " ").replace("Z", "") + " UTC"
            url = "https://hub.docker.com/r/{}/tags?name={}".format(REPO, name)
            lines.append("• [{}]({}) — pushed {}".format(name, url, ts))
        lines.append("")
        lines.append("All tags: <https://hub.docker.com/r/{}/tags>".format(REPO))
        print("\n".join(lines))
        log("{} new: {}".format(len(new_tags), [n for n, _ in new_tags]))
    else:
        log("no new tags ({} scanned, watermark {})".format(len(new_tags), watermark))
    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
