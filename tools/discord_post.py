"""Post Soulstruct Blender (Team Cereus) update notes to the team's Discord channel through a webhook.

Updates ship by pushing to `main`: the Stan's Tools updater fast-forwards every install to `origin/main`. So each
push is a release, and `.github/workflows/discord-changelog.yml` runs this script for it.

Notes for a push `BEFORE..AFTER`:
- CHANGELOG.md entries that are new in that range (whole bullets, sub-bullets kept), grouped by their `###` heading.
- Otherwise, the subjects of user-facing commits (`feat`, `fix`, `perf`) in that range.
A push with neither (docs, tests, CI, submodule bumps only) posts nothing.

The webhook URL is a secret: the `DISCORD_WEBHOOK` repo secret in CI, or a file outside every checkout locally
(`--webhook-file`, default `S:/soulstruct-blender-dist/discord-webhook.txt`). It is never printed.

    python tools/discord_post.py --range 22b4d31..6192403             # preview only
    python tools/discord_post.py --range 22b4d31..6192403 --post      # sends it
    python tools/discord_post.py --check                              # checks the webhook, posts nothing
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_WEBHOOK_FILE = Path("S:/soulstruct-blender-dist/discord-webhook.txt")
REPO_URL = "https://github.com/team-cereus/soulstruct-blender"
# Discord's edge rejects some default agents with a 403.
USER_AGENT = f"SoulstructBlenderTeamCereusPublisher/1.0 (+{REPO_URL})"
USER_FACING = re.compile(r"^(feat|fix|perf)(\(([^)]*)\))?!?:\s*(.+)$")
EMBED_LIMIT = 4000  # description limit is 4096
SCOPE_NAMES = {
    "stan-tools": "Stan's Tools", "flver": "FLVER", "animation": "Animation", "control-rig": "Control Rig",
    "nr-unpack": "Nightreign unpacker", "addon": "Add-on", "msb": "MSB", "hkx": "HKX",
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def changelog_at(rev: str) -> str:
    try:
        return git("show", f"{rev}:CHANGELOG.md")
    except subprocess.CalledProcessError:
        return ""


def bullets(changelog: str) -> list[tuple[str, str]]:
    """(heading, bullet) for every top-level bullet in the changelog, sub-bullets and wrapped lines included.
    Headings are '<version> / <### group>' so the same text under a new version still counts as one entry."""
    out = []
    version = group = ""
    current = None  # type: list[str] | None
    for line in changelog.splitlines():
        if line.startswith("## "):
            version, group, current = line[3:].strip(), "", None
        elif line.startswith("### "):
            group, current = line[4:].strip(), None
        elif line.startswith("- "):
            current = [line]
            out.append((f"{version}/{group}", current))
        elif current is not None and line.startswith("  ") and line.strip():
            current.append(line)
        else:
            current = None
    return [(h, "\n".join(b)) for h, b in out]


def to_discord(bullet: str) -> str:
    """Join hard-wrapped Markdown lines so Discord shows each bullet as one line."""
    items = []  # type: list[list]
    for line in bullet.splitlines():
        m = re.match(r"^(\s*)- (.*)$", line)
        if m:
            items.append([len(m.group(1)) // 2, m.group(2).strip()])
        else:
            items[-1][1] += " " + line.strip()
    return "\n".join(f"{'  ' * depth}- {text}" for depth, text in items)


def new_changelog_entries(before: str, after: str) -> dict[str, list[str]]:
    old = {b for _, b in bullets(changelog_at(before))}
    groups = {}  # type: dict[str, list[str]]
    for heading, b in bullets(changelog_at(after)):
        if b not in old:
            groups.setdefault(heading.split("/", 1)[1] or "Changes", []).append(to_discord(b))
    return groups


def commit_entries(rev_range: str) -> dict[str, list[str]]:
    groups = {"Added": [], "Fixed": [], "Changed": []}  # type: dict[str, list[str]]
    for subject in reversed(git("log", "--no-merges", "--format=%s", rev_range).splitlines()):
        m = USER_FACING.match(subject)
        if not m:
            continue
        kind, scope, text = m.group(1), m.group(3), m.group(4)
        text = text[0].upper() + text[1:]
        if scope:
            text = f"{SCOPE_NAMES.get(scope, scope)}: {text}"
        groups[{"feat": "Added", "fix": "Fixed", "perf": "Changed"}[kind]].append(f"- {text}")
    return {k: v for k, v in groups.items() if v}


def build_messages(before: str, after: str) -> list[dict]:
    groups = new_changelog_entries(before, after) or commit_entries(f"{before}..{after}")
    if not groups:
        return []
    short = git("rev-parse", "--short", after).strip()
    sections = [f"**{name}**\n" + "\n".join(items) for name, items in groups.items()]
    # Split into embeds of at most EMBED_LIMIT characters, never inside a bullet.
    chunks, chunk = [], ""
    for section in sections:
        for piece in re.split(r"\n(?=- )", section):
            if len(piece) > EMBED_LIMIT:
                piece = piece[: EMBED_LIMIT - 1] + "…"
            if chunk and len(chunk) + 1 + len(piece) > EMBED_LIMIT:
                chunks.append(chunk)
                chunk = piece
            else:
                sep = "\n\n" if piece.startswith("**") else "\n"  # blank line before each ### group
                chunk = f"{chunk}{sep}{piece}" if chunk else piece
    chunks.append(chunk)
    compare = f"{REPO_URL}/compare/{git('rev-parse', '--short', before).strip()}...{short}"
    messages = []
    for i, text in enumerate(chunks):
        embed = {"color": 0xD58A3A, "description": text, "footer": {"text": f"Team Cereus · {short}"}}
        if i == 0:
            embed["title"] = "Soulstruct Blender update"
            embed["url"] = compare
        if i == len(chunks) - 1:
            embed["fields"] = [{
                "name": "How to update",
                "value": f"Restart Blender: Stan's Tools updates itself. Fresh install: [installer]({REPO_URL}/tree/main/installer).",
            }]
        # parse: [] so nothing in the notes can ever ping anyone.
        messages.append({"allowed_mentions": {"parse": []}, "embeds": [embed]})
    return messages


def webhook(args) -> str:
    url = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not url:
        path = Path(args.webhook_file)
        if not path.is_file():
            sys.exit(f"discord: no DISCORD_WEBHOOK and no {path}")
        url = path.read_text(encoding="utf-8-sig").strip()
    return url


def request(url: str, method: str, body: dict | None = None) -> dict | None:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/json",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            # Reported by status only, so the URL never reaches a log.
            if e.code != 429 or attempt == 3:
                raise SystemExit(f"discord answered HTTP {e.code}") from None
            time.sleep(3)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--range", help="BEFORE..AFTER (BEFORE may be empty or all zeros for a new branch)")
    parser.add_argument("--post", action="store_true", help="send it (default: print the payload)")
    parser.add_argument("--check", action="store_true", help="check the webhook, post nothing")
    parser.add_argument("--webhook-file", default=str(DEFAULT_WEBHOOK_FILE))
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.check:
        info = request(webhook(args), "GET")
        print(f"webhook ok: name='{info.get('name')}' channel={info.get('channel_id')}")
        return
    if not args.range or ".." not in args.range:
        parser.error("give --range BEFORE..AFTER or --check")
    before, after = args.range.split("..", 1)
    if not before.strip("0") or subprocess.run(
        ["git", "-C", str(REPO), "cat-file", "-e", f"{before}^{{commit}}"], capture_output=True
    ).returncode != 0:
        before = f"{after}^"  # new branch, or force push from a commit we don't have: the pushed commit alone
    messages = build_messages(before, after)
    if not messages:
        print("discord: nothing user-facing in this push; nothing posted")
        return
    if not args.post:
        print(json.dumps(messages, indent=2, ensure_ascii=False))
        return
    url = webhook(args)
    for msg in messages:
        request(url + ("&" if "?" in url else "?") + "wait=true", "POST", msg)
        time.sleep(1.5)
    print(f"discord: posted {len(messages)} message(s) for {args.range}")


if __name__ == "__main__":
    main()
