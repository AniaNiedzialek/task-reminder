## What is this?
This is a event reminder app that sends notifications about the events and tasks from the calendar.
##  How do I run it?
In the Terminal.app not VS Code:
```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

```bash
./.venv/bin/python task-reminder.py --test-notify   # check notifications arrive
./.venv/bin/python task-reminder.py --list          # what's coming up
./.venv/bin/python task-reminder.py                 # watch and ping (Ctrl-C to stop)
./.venv/bin/python task-reminder.py --once          # single pass, for launchd/cron
./.venv/bin/python task-reminder.py --diagnose
# inspect when permissions misbehave
./install.sh install | uninstall | status | logs
```

## Gotchas:
- There are no tests yet 
- state.json lives in ~/Library/Application Support/task-reminder/, not in the repo.
- VS Code's terminal can never get Calendar access. Nothing in the code can fix this. 
- the Calendar permission is granted to the app that runs the script, not to the script itself. Is the permissions misbehave run --diagnose.

## Architecture: 
parts that are pure logic:
- _applescript_str,"--lead parsing in main()", open_store, notify
parts that touch macOS:
- open_store(), notify, load_state, save_state, check() is pure with side effects; upcoming_events, notify_event

## Convention:
- Keep it a single file. No new dependencies without asking. No classes where a function works.
- for commits write only ~10 words 
- No em dashes in commit messages or docs.
- do not delete state.json
