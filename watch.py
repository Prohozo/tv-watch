#!/usr/bin/env python3
"""Poll TradingView's support-portal problems feed and report what changed.

The feed is what renders the warning banner on https://www.tradingview.com/support/.
It is a public JSON endpoint, so this needs no browser and no credentials:

    GET https://www.tradingview.com/support/support-portal-problems/?language=en
    {"issues": [{"id": 2000375, "title": "...", "description": "...",
                 "show_on_chart": false}]}

State lives in state.json next to this file. Compare, write, and emit a report;
the caller (a GitHub Actions workflow) decides how to deliver it.

Exit status is always 0 unless the fetch itself failed -- "nothing changed" is a
normal outcome, not an error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

FEED = "https://www.tradingview.com/support/support-portal-problems/?language=en"
UA = "tv-watch/1.0 (+https://github.com/)"
TIMEOUT = 30
RETRIES = 3

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"

# Fields that count as a change. `show_on_chart` is included because TradingView
# flips it when an issue is escalated to the chart banner, which is a real
# severity signal even when the wording stays the same.
TRACKED = ("title", "description", "show_on_chart")


def fetch(url: str = FEED) -> list[dict]:
    """Return the issues array. Retries transient failures; raises on give-up.

    A miss must be loud rather than silently reported as "all clear", otherwise
    an outage at TradingView would look identical to a clean feed.
    """
    last: Exception | None = None
    for attempt in range(RETRIES):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last = exc
    else:
        raise RuntimeError(f"feed unreachable after {RETRIES} attempts: {last}")

    issues = payload.get("issues")
    if not isinstance(issues, list):
        raise RuntimeError(f"unexpected payload shape: {payload!r}")
    return issues


def load_state() -> dict:
    if not STATE.exists():
        return {"issues": {}, "heartbeat": ""}
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A corrupt state file would otherwise wedge the bot forever. Treat it as
        # a cold start: the next run re-reports whatever is live, which is noisy
        # once but self-healing.
        return {"issues": {}, "heartbeat": ""}
    data.setdefault("issues", {})
    data.setdefault("heartbeat", "")
    return data


def normalise(issues: list[dict]) -> dict[str, dict]:
    """Key issues by id, keeping only the tracked fields."""
    out: dict[str, dict] = {}
    for issue in issues:
        key = str(issue.get("id", issue.get("title", "")))
        out[key] = {f: issue.get(f) for f in TRACKED}
    return out


def diff(old: dict[str, dict], new: dict[str, dict]) -> dict[str, list]:
    added = [(k, new[k]) for k in new if k not in old]
    cleared = [(k, old[k]) for k in old if k not in new]
    changed = [(k, old[k], new[k]) for k in new if k in old and old[k] != new[k]]
    return {"added": added, "cleared": cleared, "changed": changed}


def week_stamp(now: dt.datetime) -> str:
    """ISO year-week.

    Written into state.json so the file changes at least weekly even when the
    feed is quiet. That weekly commit keeps the repo "active": GitHub disables
    scheduled workflows in repos with no commits for 60 days.
    """
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def render(delta: dict[str, list], live: dict[str, dict]) -> tuple[str, str]:
    """Return (title, markdown body) for the notification."""
    added, cleared, changed = delta["added"], delta["cleared"], delta["changed"]

    if added:
        headline = added[0][1]["title"] or "(untitled issue)"
        title = f"TradingView issue: {headline}"
    elif changed:
        title = f"TradingView issue updated: {changed[0][2]['title'] or '(untitled)'}"
    else:
        title = "TradingView issue cleared"
    title = title[:240]

    lines: list[str] = []
    for key, issue in added:
        lines.append(f"### 🔴 New — `{key}`\n")
        lines.append(f"**{issue['title']}**\n")
        lines.append(f"{issue['description']}\n")
        if issue.get("show_on_chart"):
            lines.append("> Shown on the chart banner, not just the support page.\n")
    for key, before, after in changed:
        lines.append(f"### 🟠 Updated — `{key}`\n")
        lines.append(f"**{after['title']}**\n")
        lines.append(f"{after['description']}\n")
        for field in TRACKED:
            if before.get(field) != after.get(field):
                lines.append(f"- `{field}`: `{before.get(field)}` → `{after.get(field)}`\n")
    for key, issue in cleared:
        lines.append(f"### 🟢 Cleared — `{key}`\n")
        lines.append(f"~~{issue['title']}~~\n")

    lines.append("\n---\n")
    lines.append(f"**Currently live: {len(live)} issue(s)**\n")
    for key, issue in live.items():
        flag = " *(on chart)*" if issue.get("show_on_chart") else ""
        lines.append(f"- `{key}` {issue['title']}{flag}\n")
    lines.append(f"\nSource: <{FEED}>\n")
    lines.append(f"Checked: {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}\n")

    return title, "".join(lines)


def emit_output(**kwargs: str) -> None:
    """Write step outputs for GitHub Actions; fall back to stdout when local."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        for key, value in kwargs.items():
            print(f"[{key}] {value}")
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in kwargs.items():
            if "\n" in value:
                fh.write(f"{key}<<__EOF__\n{value}\n__EOF__\n")
            else:
                fh.write(f"{key}={value}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report but do not write state.json")
    ap.add_argument("--show", action="store_true", help="print the live feed and exit")
    args = ap.parse_args()

    issues = fetch()
    live = normalise(issues)

    if args.show:
        print(json.dumps(issues, indent=2, ensure_ascii=False))
        return 0

    state = load_state()
    delta = diff(state["issues"], live)
    has_change = any(delta.values())

    if has_change:
        title, body = render(delta, live)
        print(f"CHANGE: {title}")
        print(body)
        emit_output(changed="true", title=title, body=body)
    else:
        print(f"no change ({len(live)} live issue(s))")
        emit_output(changed="false")

    if not args.dry_run:
        STATE.write_text(
            json.dumps(
                {"issues": live, "heartbeat": week_stamp(dt.datetime.now(dt.timezone.utc))},
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - the workflow surfaces this as a failed run
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
