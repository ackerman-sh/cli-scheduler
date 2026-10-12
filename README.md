# CLI Resume Scheduler

A small Textual terminal dashboard for scheduling a command/payload to be typed into a focused desktop application. Includes optional target-window and click-position locking for X11 and KDE Plasma 6 Wayland.

> **Caution:** This is keyboard/mouse automation, not a verified application API. Test with a harmless editor before using it with a live CLI. A successful status only means input events were sent; it does not verify that the target application accepted the command.

## Features

- Tokyo Night-inspired Textual dashboard.
- 24-hour `HH:MM` scheduling, live countdown, and cancellation.
- Empty payload means **press Enter only**.
- Detects X11 vs Wayland from the desktop session.
- **Pick Target**: after a five-second countdown, switch to the target app and click the intended input field. The app stores the active window ID and the click position relative to that window.
- Optional `locktest` marker that is typed and then erased during target picking.
- **Clear Lock** returns to focused-window mode.
- Target-lock execution attempts to activate the saved window and click the saved position. It fails rather than typing if the window cannot be activated, its size changed, or the pointer misses the saved point.

## Requirements

- Python 3.10+
- Python packages from `requirements.txt`
- X11: `xdotool` and PyAutoGUI
- Wayland: KDE Plasma 6, `kdotool`, and `ydotool` / `ydotoold`

Target locking on Wayland uses KWin's scripting API via [kdotool](https://github.com/jinliu/kdotool). Not every xdotool command is supported by kdotool, and this feature has not been tested against every Plasma setup.

## Install

Create and activate a virtual environment:

```bash
python -m venv env
source env/bin/activate
python -m pip install -r requirements.txt
```

Install desktop tools using your distribution's package manager where available:

```bash
# X11
sudo apt install xdotool

# Wayland keyboard/mouse injection
sudo apt install ydotool
```

For KDE Plasma 6 Wayland target-window control, install `kdotool` from its upstream instructions: https://github.com/jinliu/kdotool

### Wayland ydotool setup

The `ydotoold` daemon needs access to `/dev/uinput`. Start the distro-provided service if available:

```bash
systemctl --user enable --now ydotool.service
systemctl --user status ydotool.service
```

If it reports a permission error opening `/dev/uinput`, follow your distribution's guidance for device permissions. Granting membership in the `input` group is security-sensitive because it can expose input devices. After changing group membership, a new login is normally required; `newgrp input` can be used for a temporary shell. Ensure the daemon and client use the same socket path.

Check injection in a harmless text editor before using the scheduler:

```bash
ydotool type 'WAYLAND_TEST'
```

## Run

```bash
source env/bin/activate
python scheduler.py
```

## Use

1. Set a time in 24-hour `HH:MM` format.
2. Enter a payload such as `resume`, or leave it blank to send Enter only.
3. Optional: click **PICK TARGET**, then within five seconds switch to the target app and click the intended input field. Do not click elsewhere until picking finishes.
4. If the marker option is enabled, the scheduler briefly types `locktest` and sends Backspace eight times. The app cannot verify that the text was removed, so disable this option if temporary input could trigger an action in the target app.
5. Click **ARM SCHEDULER**. The target window is activated and the saved position is clicked when the schedule fires.
6. Use **CLEAR LOCK** to return to focused-window mode.

## Target-lock limitations

This is a **window + coordinate lock**, not a lock on the actual text-field widget. It does not inspect an application's UI tree or verify the field identity. If the target app changes its layout while keeping the same window size, the saved point may no longer be the intended field. The implementation checks the window size and pointer position and aborts on detected mismatches, but it cannot eliminate every GUI automation risk.

Keep the desktop session running and unlocked. Do not rely on this for safety-critical tasks or unattended commands that could cause data loss.
