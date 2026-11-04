#!/usr/bin/env python3
"""Refresh GitHub stats for every agent in agents.yaml and regenerate README.md.

Usage:
  python scripts/update.py            # fetch stats from GitHub, update data/, rebuild README
  python scripts/update.py --offline  # rebuild README from cached data/stats.json only
  python scripts/update.py --check    # validate agents.yaml (used on pull requests)

Set GITHUB_TOKEN for higher rate limits (the GitHub Action does this automatically).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
AGENTS_FILE = ROOT / "agents.yaml"
STATS_FILE = ROOT / "data" / "stats.json"
HISTORY_FILE = ROOT / "data" / "history.jsonl"
TEMPLATE_FILE = ROOT / "templates" / "README.template.md"
README_FILE = ROOT / "README.md"

API = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")

# Order here is the order sections appear in the README.
CATEGORIES = {
    "terminal": ("🖥️ Terminal agents", "Run in your shell and work directly on your files."),
    "ide": ("🧩 IDE agents & editors", "Live inside your editor as an extension, or are the editor."),
    "autonomous": ("🤖 Autonomous & issue-solving agents", "Take a task or GitHub issue and work through it largely on their own."),
    "app-builder": ("🏗️ App & codebase builders", "Generate whole applications or codebases from a description."),
    "multi-agent": ("👥 Multi-agent software teams", "Several role-playing agents collaborate like a software team."),
}
INTERFACES = {"terminal", "ide", "web", "desktop"}
REQUIRED = ("name", "repo", "description", "category", "interface", "models")
MAX_DESCRIPTION = 120

ACTIVE_DAYS = 90     # last commit within this many days -> Active
SLOWING_DAYS = 180   # within this many days -> Slowing; older -> Inactive
TRENDING_WINDOW_DAYS = 35
TRENDING_MIN_AGE_DAYS = 6
TRENDING_COUNT = 5

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


# ── Loading & validation ─────────────────────────────────────────────

def load_agents() -> list[dict]:
    with AGENTS_FILE.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("agents") or []


def validate(agents: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for i, a in enumerate(agents, 1):
        label = f"entry {i} ({a.get('name', '?')})"
        for field in REQUIRED:
            if not a.get(field):
                errors.append(f"{label}: missing '{field}'")
        unknown = set(a) - set(REQUIRED) - {"local"}
        if unknown:
            errors.append(f"{label}: unknown field(s) {sorted(unknown)}")
        repo = str(a.get("repo", ""))
        if repo and not REPO_RE.match(repo):
            errors.append(f"{label}: repo must look like owner/name, got '{repo}'")
        key = repo.lower()
        if key in seen:
            errors.append(f"{label}: duplicate of {seen[key]}")
        seen[key] = label
        if a.get("category") and a["category"] not in CATEGORIES:
            errors.append(f"{label}: category must be one of {list(CATEGORIES)}")
        iface = a.get("interface")
        if iface is not None:
            if not isinstance(iface, list) or not set(iface) <= INTERFACES:
                errors.append(f"{label}: interface must be a list drawn from {sorted(INTERFACES)}")
        desc = str(a.get("description", ""))
        if len(desc) > MAX_DESCRIPTION:
            errors.append(f"{label}: description is {len(desc)} chars (max {MAX_DESCRIPTION})")
        if "local" in a and not isinstance(a["local"], bool):
            errors.append(f"{label}: local must be true or false")
    return errors


# ── GitHub API ───────────────────────────────────────────────────────

class NotFound(Exception):
    pass


def gh_get(path: str) -> dict | list:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "live-coding-agents-updater",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{API}{path}", headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(path) from e
            if e.code in (403, 429, 500, 502, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def fetch_stats(repo: str) -> dict:
    info = gh_get(f"/repos/{repo}")
    full_name = info["full_name"]
    branch = info.get("default_branch") or "main"
    last_commit = None
    try:
        commits = gh_get(f"/repos/{full_name}/commits?per_page=1&sha={branch}")
        if commits:
            last_commit = commits[0]["commit"]["committer"]["date"][:10]
    except NotFound:
        pass  # empty repository
    lic = info.get("license") or {}
    spdx = lic.get("spdx_id")
    return {
        "full_name": full_name,
        "stars": info.get("stargazers_count"),
        "forks": info.get("forks_count"),
        "open_issues": info.get("open_issues_count"),
        "archived": bool(info.get("archived")),
        "license": spdx if spdx and spdx != "NOASSERTION" else (lic.get("name") or None),
        "last_commit": last_commit or (info.get("pushed_at") or "")[:10] or None,
        "missing": False,
    }


def warn(msg: str) -> None:
    # "::warning::" shows up as an annotation in GitHub Actions; harmless elsewhere.
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "warning: "
    print(f"{prefix}{msg}", file=sys.stderr)


def fix_renames(renames: dict[str, str]) -> None:
    """Rewrite moved repos in agents.yaml in place, keeping comments and layout."""
    text = AGENTS_FILE.read_text(encoding="utf-8")
    for old, new in renames.items():
        text = re.sub(rf"(^\s*repo:\s*){re.escape(old)}\s*$", rf"\g<1>{new}", text,
                      flags=re.MULTILINE | re.IGNORECASE)
    AGENTS_FILE.write_text(text, encoding="utf-8")


def refresh(agents: list[dict], cached: dict) -> tuple[dict, dict[str, str]]:
    stats: dict[str, dict] = {}
    renames: dict[str, str] = {}
    for a in agents:
        repo = a["repo"]
        try:
            s = fetch_stats(repo)
            if s["full_name"].lower() != repo.lower():
                warn(f"{repo} has moved to {s['full_name']}; updating agents.yaml")
                renames[repo] = s["full_name"]
            stats[s["full_name"]] = s
            print(f"  ✓ {repo}: {s['stars']} stars, last commit {s['last_commit']}")
        except NotFound:
            warn(f"{repo} not found on GitHub (deleted or private?) — consider removing it")
            prev = dict(cached.get(repo, {}))
            prev["missing"] = True
            stats[repo] = prev
        except Exception as e:  # network trouble: keep the last good numbers
            warn(f"{repo}: could not fetch stats ({e}); keeping cached values")
            if repo in cached:
                stats[repo] = cached[repo]
    return stats, renames


# ── History & trending ───────────────────────────────────────────────

def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    rows = []
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def save_history(history: list[dict], today: dt.date, stats: dict) -> list[dict]:
    snapshot = {
        "date": today.isoformat(),
        "stars": {repo: s["stars"] for repo, s in stats.items() if s.get("stars") is not None},
    }
    if not snapshot["stars"]:
        return history
    history = [h for h in history if h["date"] != snapshot["date"]] + [snapshot]
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text("".join(json.dumps(h, sort_keys=True) + "\n" for h in history), encoding="utf-8")
    return history


def trending(history: list[dict], today: dt.date, stats: dict) -> tuple[list[tuple[str, int]], int]:
    """Star gains since the oldest snapshot inside the trending window."""
    window = [
        h for h in history
        if TRENDING_MIN_AGE_DAYS <= (today - dt.date.fromisoformat(h["date"])).days <= TRENDING_WINDOW_DAYS
    ]
    if not window:
        return [], 0
    base = min(window, key=lambda h: h["date"])
    days = (today - dt.date.fromisoformat(base["date"])).days
    gains = []
    for repo, s in stats.items():
        old = base["stars"].get(repo)
        if old is not None and s.get("stars") is not None and s["stars"] > old:
            gains.append((repo, s["stars"] - old))
    gains.sort(key=lambda g: -g[1])
    return gains[:TRENDING_COUNT], days


# ── Rendering ────────────────────────────────────────────────────────

def status(s: dict, today: dt.date) -> str:
    if s.get("missing"):
        return "⚠️ Not found"
    if s.get("archived"):
        return "🪦 Archived"
    lc = s.get("last_commit")
    if not lc:
        return "—"
    age = (today - dt.date.fromisoformat(lc)).days
    if age <= ACTIVE_DAYS:
        return "🟢 Active"
    if age <= SLOWING_DAYS:
        return "🟡 Slowing"
    return "🔴 Inactive"


def fmt_stars(n) -> str:
    if n is None:
        return "—"
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_tables(agents: list[dict], stats: dict, today: dt.date) -> str:
    out = []
    for key, (title, blurb) in CATEGORIES.items():
        group = [a for a in agents if a["category"] == key]
        if not group:
            continue
        group.sort(key=lambda a: (-(stats.get(a["repo"], {}).get("stars") or -1), a["name"].lower()))
        out.append(f"## {title}\n\n{blurb}\n")
        out.append("| Agent | What it does | Interface | Models | Local | ⭐ Stars | License | Last commit | Status |")
        out.append("|---|---|---|---|:---:|---:|---|---|---|")
        for a in group:
            s = stats.get(a["repo"], {})
            local = {True: "✅", False: "—"}.get(a.get("local"), "—")
            out.append("| " + " | ".join([
                f"[{cell(a['name'])}](https://github.com/{a['repo']})",
                cell(a["description"]),
                ", ".join(a["interface"]),
                cell(a["models"]),
                local,
                fmt_stars(s.get("stars")),
                cell(s.get("license") or "—"),
                s.get("last_commit") or "—",
                status(s, today),
            ]) + " |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def render_summary(agents: list[dict], stats: dict, today: dt.date) -> str:
    counts: dict[str, int] = {}
    for a in agents:
        label = status(stats.get(a["repo"], {}), today)
        counts[label] = counts.get(label, 0) + 1
    order = ["🟢 Active", "🟡 Slowing", "🔴 Inactive", "🪦 Archived", "⚠️ Not found", "—"]
    parts = [f"{label} **{counts[label]}**" for label in order if counts.get(label)]
    return (
        f"**{len(agents)} agents** tracked · last refreshed **{today.isoformat()}**\n\n"
        + " · ".join(parts) + "\n"
    )


def render_trending(gains: list[tuple[str, int]], days: int, agents: list[dict]) -> str:
    if not gains:
        return "_Trending appears once the weekly updater has a week or more of star history._\n"
    names = {a["repo"]: a["name"] for a in agents}
    lines = [f"Biggest star gains over the last {days} days:\n"]
    for i, (repo, gain) in enumerate(gains, 1):
        lines.append(f"{i}. [{names.get(repo, repo)}](https://github.com/{repo}) — **+{gain:,}** ⭐")
    return "\n".join(lines) + "\n"


def replace_marker(text: str, name: str, content: str) -> str:
    marker = f"<!-- {name} -->"
    if marker not in text:
        raise SystemExit(f"template is missing the {marker} marker")
    return text.replace(marker, content.rstrip("\n"))


def build_readme(agents, stats, gains, days, today) -> str:
    text = TEMPLATE_FILE.read_text(encoding="utf-8")
    text = replace_marker(text, "SUMMARY", render_summary(agents, stats, today))
    text = replace_marker(text, "TRENDING", render_trending(gains, days, agents))
    text = replace_marker(text, "TABLES", render_tables(agents, stats, today))
    header = "<!-- Generated by scripts/update.py. Edit agents.yaml or templates/README.template.md instead. -->\n"
    return header + text


# ── Main ─────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="only validate agents.yaml")
    mode.add_argument("--offline", action="store_true", help="rebuild README from cached stats")
    parser.add_argument("--today", help=argparse.SUPPRESS)  # for tests
    args = parser.parse_args()

    agents = load_agents()
    errors = validate(agents)
    if errors:
        print("agents.yaml has problems:", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1
    if args.check:
        print(f"agents.yaml is valid ({len(agents)} agents).")
        return 0

    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    cached = json.loads(STATS_FILE.read_text(encoding="utf-8")) if STATS_FILE.exists() else {}
    history = load_history()

    if args.offline:
        stats = cached
    else:
        print(f"Fetching stats for {len(agents)} agents…")
        stats, renames = refresh(agents, cached)
        if renames:
            fix_renames(renames)
            agents = load_agents()
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATS_FILE.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        history = save_history(history, today, stats)

    gains, days = trending(history, today, stats)
    README_FILE.write_text(build_readme(agents, stats, gains, days, today), encoding="utf-8")
    print(f"README.md rebuilt with {len(agents)} agents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
