# task-reminder

Desktop pings for upcoming macOS Calendar events, so nothing gets missed.

Reads events through **EventKit** — the same framework Calendar.app uses — so it
sees every connected account (iCloud, Google, Exchange) and expands recurring
events correctly. Notifications go out through the native macOS notification
centre.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

The first run asks for Calendar access. macOS grants it to the *app running the
script*, never to the script itself — so switching terminals means approving
again under **System Settings → Privacy & Security → Calendars**.

**Run it from Terminal.app or iTerm, not VS Code's integrated terminal.** macOS
only shows the Calendar prompt for an app whose `Info.plist` declares
`NSCalendarsUsageDescription`; VS Code ships no calendar key, so the request is
refused with no dialog and the status stays `not determined` forever. Nothing
about the script can work around that.

`--diagnose` reports which app is being held responsible and what it is allowed
to do.

## Usage

```bash
./.venv/bin/python task-reminder.py --test-notify   # check notifications arrive
./.venv/bin/python task-reminder.py --list          # what's coming up
./.venv/bin/python task-reminder.py                 # watch and ping (Ctrl-C to stop)
./.venv/bin/python task-reminder.py --once          # single pass, for launchd/cron
```

Options:

| Flag | Default | Meaning |
|---|---|---|
| `--lead` | `10,1` | Minutes before an event to ping. One ping per value. |
| `--interval` | `60` | Seconds between checks in watch mode. |
| `--once` | — | Check once and exit. |
| `--list` | — | Print upcoming events, notify nothing. |

Already-sent reminders are recorded in
`~/Library/Application Support/task-reminder/state.json`, so restarting the
script never replays a ping. Entries older than a day are pruned automatically.

## Roadmap

- [ ] `launchd` plist so it runs at login without a terminal window
- [ ] Clickable notifications (via `terminal-notifier`) that open the event
- [ ] Reminders.app support alongside Calendar
- [ ] Snooze / per-calendar filtering
