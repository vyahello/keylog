# Keystroke logger

A precise keystroke logger.

**Local use only.** It captures keys on the machine it runs on, keeps everything in memory.

> [!NOTE]
> Before using a tool please launch a [Web Server](./ws) first.

## Requirements

- Python 3.10+
- Linux (X11) or Windows

## Usage

1. Install the dependency:
   ```bash
   pip install -r requirements.txt
   ```
2. Run it:
   ```bash
   python3 keylog.py
   ```
3. Type as usual. Stop with **Ctrl+C** or the stop hotkey **Ctrl+Alt+Q**.

### Options

| Flag | Default | Meaning |
|------|---------|---------|
| `--echo` | off | print each event to the terminal as it is captured |
| `--autosave SECONDS` | `5` | how often the transcript snapshot is rebuilt |
| `--stop-hotkey CHORD` | `ctrl+alt+q` | chord that stops capture |

## Where the data goes

Everything stays in memory on the `KeyLogger` object as two strings:

- `raw_log` — every event, one line each (`[HH:MM:SS.mmm] <token>`), with a header.
- `transcript` — the reconstructed typed text (Backspace/Enter/Tab applied).

To inspect them, drive the class yourself:

```python
import keylog

log = keylog.KeyLogger(autosave_seconds=1)
log.start()               # type in your focused window; Ctrl+C / Ctrl+Alt+Q to end
print(log.raw_log)
print(log.transcript)
```

## Notes

- On Linux, run under X11 (global capture is limited on Wayland).
- Data lives only while the process runs; nothing is persisted.
