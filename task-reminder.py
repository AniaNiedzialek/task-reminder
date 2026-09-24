#!/usr/bin/env python3
"""Ping me before my Mac Calendar events start.

Reads events straight from EventKit (the same API Calendar.app uses, so it sees
every account -- iCloud, Google, Exchange -- and expands recurring events
correctly) and fires a macOS notification a few minutes ahead of each one.

Usage:
    ./task-reminder.py                  # watch forever, notify before events
    ./task-reminder.py --list           # print what's coming up, notify nothing
    ./task-reminder.py --once           # one check-and-exit pass (for launchd)
    ./task-reminder.py --test-notify    # prove notifications reach the desktop
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from EventKit import EKEventStore, EKEntityTypeEvent
from Foundation import NSDate, NSDefaultRunLoopMode, NSRunLoop

# How many minutes before an event to ping. One notification per lead time.
DEFAULT_LEADS = [10, 1]
# Only events starting within this window are considered.
LOOKAHEAD_HOURS = 12
# Seconds between checks in watch mode.
DEFAULT_INTERVAL = 60

STATE_PATH = Path.home() / "Library/Application Support/task-reminder/state.json"
AUTHORIZED = 3  # EKAuthorizationStatusFullAccess (also .authorized pre-Sonoma)


# --------------------------------------------------------------------------
# Calendar access
# --------------------------------------------------------------------------

STATUS_NAMES = {
    0: "not determined (never asked)",
    1: "restricted (blocked by policy or MDM)",
    2: "denied",
    3: "full access",
    4: "write only (can add events, cannot read them)",
}


def auth_status() -> int:
    return EKEventStore.authorizationStatusForEntityType_(EKEntityTypeEvent)


def host_app() -> str:
    """Bundle id of the app macOS holds responsible for our permissions.

    TCC grants attach to the enclosing app -- Terminal, iTerm, VS Code -- never
    to the Python binary, so this is what actually needs approving.
    """
    return os.environ.get("__CFBundleIdentifier") or "unknown"


def request_access(store: EKEventStore, timeout: float = 120.0):
    """Ask for Calendar access. Returns (granted, error, timed_out).

    The run loop is the whole trick here: a CLI has no event loop, and without
    one macOS never presents the permission dialog and the completion handler
    never fires -- the request just hangs until it times out.
    """
    done = threading.Event()
    result = {"granted": False, "error": None}

    def handler(granted, error):
        result["granted"] = bool(granted)
        result["error"] = error
        done.set()

    if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(handler)  # macOS 14+
    else:
        store.requestAccessToEntityType_completion_(EKEntityTypeEvent, handler)

    loop = NSRunLoop.currentRunLoop()
    deadline = time.monotonic() + timeout
    while not done.is_set() and time.monotonic() < deadline:
        loop.runMode_beforeDate_(
            NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.1)
        )

    return result["granted"], result["error"], not done.is_set()


def access_help(timed_out: bool = False, error=None, requested: bool = False) -> str:
    status, app = auth_status(), host_app()
    lines = [
        "No Calendar access.",
        f"  status:     {status} - {STATUS_NAMES.get(status, 'unknown')}",
        f"  asking as:  {app}",
        "",
    ]
    if timed_out:
        lines += [
            "The permission dialog never appeared and the request never came back.",
            "Try running this from Terminal.app instead.",
        ]
    elif status in (1, 2):
        lines += [
            "macOS is holding a stored refusal for this app. Clear it, then rerun:",
            f"    tccutil reset Calendar {app}" if app != "unknown"
            else "    tccutil reset Calendar",
            "",
            "Or tick the app under:",
            "    System Settings > Privacy & Security > Calendars",
        ]
    elif status == 4:
        lines += [
            "This app can only add events, not read them. Grant full access under:",
            "    System Settings > Privacy & Security > Calendars",
        ]
    elif requested:
        # Asked, refused instantly, status never moved off notDetermined. macOS
        # only presents the prompt for an app whose Info.plist declares a
        # calendar usage string; without one the request dies silently.
        lines += [
            f"{app} requested access and macOS refused without showing a prompt.",
            "",
            "An app can only trigger the Calendar prompt if its Info.plist declares",
            "NSCalendarsUsageDescription (NSCalendarsFullAccessUsageDescription on",
            "macOS 14+). VS Code ships neither, so its built-in terminal can never",
            "read your calendar. Moving or re-signing the app does not change that.",
            "",
            "Run it from Terminal.app or iTerm instead:",
            f"    cd {os.getcwd()}",
            "    ./.venv/bin/python task-reminder.py",
        ]
    else:
        lines += [
            "Access has not been requested yet in this app.",
            "Run without --diagnose to trigger the permission prompt.",
        ]
    if error:
        lines += ["", f"  error: {error}"]
    return "\n".join(lines)


def open_store() -> EKEventStore:
    """Return an EventKit store, prompting for Calendar access if needed."""
    store = EKEventStore.alloc().init()
    if auth_status() == AUTHORIZED:
        return store

    granted, error, timed_out = request_access(store)
    if granted and auth_status() == AUTHORIZED:
        return store

    sys.exit(access_help(timed_out, error, requested=True))


def diagnose() -> None:
    status = auth_status()
    print(f"responsible app : {host_app()}")
    print(f"calendar access : {status} - {STATUS_NAMES.get(status, 'unknown')}")
    if status != AUTHORIZED:
        print()
        print(access_help())
        return
    store = EKEventStore.alloc().init()
    cals = store.calendarsForEntityType_(EKEntityTypeEvent) or []
    print(f"calendars       : {len(cals)}")
    for c in cals:
        print(f"                  - {c.title()}")


def upcoming_events(store: EKEventStore, hours: int = LOOKAHEAD_HOURS) -> list[dict]:
    """Events starting between now and `hours` from now, soonest first."""
    now = datetime.now()
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        NSDate.dateWithTimeIntervalSince1970_(now.timestamp()),
        NSDate.dateWithTimeIntervalSince1970_((now + timedelta(hours=hours)).timestamp()),
        None,  # None = every calendar
    )

    events = []
    for ev in store.eventsMatchingPredicate_(predicate) or []:
        start_date = ev.startDate()
        if start_date is None:
            continue
        start = datetime.fromtimestamp(start_date.timeIntervalSince1970())
        if start < now:
            continue  # already running
        events.append({
            # eventIdentifier repeats across occurrences of a recurring event,
            # so the start time is part of what makes an occurrence unique.
            "uid": f"{ev.eventIdentifier()}@{int(start.timestamp())}",
            "title": ev.title() or "(untitled)",
            "start": start,
            "all_day": bool(ev.isAllDay()),
            "location": ev.location() or "",
            "calendar": ev.calendar().title() if ev.calendar() else "",
        })
    events.sort(key=lambda e: e["start"])
    return events


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------

def _applescript_str(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, subtitle: str = "", message: str = "", sound: str = "Ping") -> None:
    script = (
        f'display notification "{_applescript_str(message)}" '
        f'with title "{_applescript_str(title)}"'
    )
    if subtitle:
        script += f' subtitle "{_applescript_str(subtitle)}"'
    if sound:
        script += f' sound name "{_applescript_str(sound)}"'
    subprocess.run(["osascript", "-e", script], check=False)


def notify_event(event: dict, minutes_out: int) -> None:
    when = "now" if minutes_out <= 0 else f"in {minutes_out} min"
    detail = event["start"].strftime("%-I:%M %p")
    if event["location"]:
        detail += f" · {event['location']}"
    notify(title=event["title"], subtitle=f"Starts {when}", message=detail)


# --------------------------------------------------------------------------
# State -- so the same reminder never fires twice
# --------------------------------------------------------------------------

def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    # Forget anything we notified about more than a day ago.
    cutoff = time.time() - 86400
    state = {k: v for k, v in state.items() if v > cutoff}
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------

def check(store: EKEventStore, leads: list[int], state: dict, verbose: bool = False) -> None:
    now = datetime.now()
    events = upcoming_events(store)
    pinged = 0

    for event in events:
        if event["all_day"]:
            continue  # all-day events have no meaningful "10 minutes before"
        minutes_out = (event["start"] - now).total_seconds() / 60
        for lead in leads:
            key = f"{event['uid']}#{lead}"
            if minutes_out <= lead and key not in state:
                notify_event(event, round(minutes_out))
                state[key] = time.time()
                pinged += 1
                if verbose:
                    print(f"[{now:%Y-%m-%d %H:%M:%S}] PING {event['title']} (T-{lead}m)")

    if verbose:
        # A heartbeat every run: a log that only speaks up when it pings gives
        # no way to tell "working, nothing due" from "silently broken".
        nxt = next((e for e in events if not e["all_day"]), None)
        upcoming = f"next: {nxt['title']} at {nxt['start']:%H:%M}" if nxt else "next: none"
        print(f"[{now:%Y-%m-%d %H:%M:%S}] ok - {len(events)} event(s), "
              f"{pinged} pinged, {upcoming}")

    save_state(state)


def print_events(store: EKEventStore) -> None:
    events = upcoming_events(store)
    if not events:
        print(f"Nothing scheduled in the next {LOOKAHEAD_HOURS} hours.")
        return
    print(f"Next {len(events)} event(s):\n")
    for e in events:
        when = "all day" if e["all_day"] else e["start"].strftime("%a %-I:%M %p")
        away = int((e["start"] - datetime.now()).total_seconds() / 60)
        print(f"  {when:>16}  (in {away:>4}m)  {e['title']}  [{e['calendar']}]")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lead", default=",".join(map(str, DEFAULT_LEADS)),
                        help="minutes before an event to ping, comma separated "
                             f"(default: {','.join(map(str, DEFAULT_LEADS))})")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"seconds between checks (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--once", action="store_true", help="check once, then exit")
    parser.add_argument("--list", action="store_true", help="list upcoming events and exit")
    parser.add_argument("--test-notify", action="store_true",
                        help="send a sample notification and exit")
    parser.add_argument("--diagnose", action="store_true",
                        help="report permission state and visible calendars")
    args = parser.parse_args()

    if args.test_notify:
        notify("task-reminder", "Notifications are working", "You'll get pings like this.")
        return

    if args.diagnose:
        diagnose()
        return

    store = open_store()

    if args.list:
        print_events(store)
        return

    leads = sorted({int(x) for x in args.lead.split(",") if x.strip()}, reverse=True)
    state = load_state()

    if args.once:
        check(store, leads, state, verbose=True)
        return

    print(f"Watching calendar. Pinging {leads} min before each event. Ctrl-C to stop.")
    try:
        while True:
            check(store, leads, state, verbose=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
