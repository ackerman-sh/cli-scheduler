#!/usr/bin/env python3
"""Cross-platform Textual resume scheduler with optional target window/position lock.

Target locking stores a window ID and relative click position, not a UI element.
Use only after testing in a harmless editor; automation cannot verify app acceptance.
"""
import asyncio
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Log, Static

PROBE = "locktest"
PICK_SECONDS = 5


def session_type():
    s = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if s in ("x11", "wayland"):
        return s
    return "wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11" if os.environ.get("DISPLAY") else "unknown"


def run(*args, input_text=None, timeout=15):
    p = subprocess.run(args, input=input_text, text=True, capture_output=True, check=True, timeout=timeout)
    return p.stdout.strip()


def window_tool(session):
    return "xdotool" if session == "x11" else "kdotool"


def active_window(session):
    out = run(window_tool(session), "getactivewindow")
    wid = out.splitlines()[-1].strip() if out else ""
    if not wid or wid == "0":
        raise RuntimeError("Could not identify active window")
    return wid


def mouse_position(session):
    if session == "x11":
        out = run("xdotool", "getmouselocation", "--shell")
        x, y = re.search(r"(?m)^X=(-?\d+)$", out), re.search(r"(?m)^Y=(-?\d+)$", out)
    else:
        out = run("kdotool", "getmouselocation")
        x, y = re.search(r"\bx:\s*(-?\d+)", out), re.search(r"\by:\s*(-?\d+)", out)
    if not x or not y:
        raise RuntimeError(f"Could not read pointer position: {out[:160]}")
    return int(x.group(1)), int(y.group(1))


def window_geometry(session, wid):
    if session == "x11":
        out = run("xdotool", "getwindowgeometry", "--shell", wid)
        vals = {}
        for k in ("X", "Y", "WIDTH", "HEIGHT"):
            m = re.search(rf"(?m)^{k}=(-?\d+)$", out)
            if not m:
                raise RuntimeError("Could not read X11 window geometry")
            vals[k] = int(m.group(1))
        return vals["X"], vals["Y"], vals["WIDTH"], vals["HEIGHT"]
    out = run("kdotool", "getwindowgeometry", wid)
    p = re.search(r"Position:\s*(-?[0-9.]+)\s*,\s*(-?[0-9.]+)", out)
    g = re.search(r"Geometry:\s*(\d+)\s*x\s*(\d+)", out)
    if not p or not g:
        raise RuntimeError(f"Could not parse KWin geometry: {out[:180]}")
    return round(float(p.group(1))), round(float(p.group(2))), int(g.group(1)), int(g.group(2))


@dataclass(frozen=True)
class Target:
    window_id: str
    title: str
    dx: int
    dy: int
    width: int
    height: int


def capture_target(session):
    wid = active_window(session)
    x, y = mouse_position(session)
    ox, oy, w, h = window_geometry(session, wid)
    dx, dy = x - ox, y - oy
    if not (0 <= dx < w and 0 <= dy < h):
        raise RuntimeError("Pointer is outside selected window; click the intended input field")
    try:
        title = run(window_tool(session), "getwindowname", wid)[:100]
    except Exception:
        title = "(untitled)"
    return Target(wid, title, dx, dy, w, h)


def inject(session, payload):
    if session == "x11":
        import pyautogui
        pyautogui.FAILSAFE = True
        if payload:
            pyautogui.write(payload, interval=0.04)
        pyautogui.press("enter")
    elif session == "wayland":
        if payload:
            run("ydotool", "type", "--file", "-", input_text=payload, timeout=120)
        run("ydotool", "key", "28:1", "28:0")
    else:
        raise RuntimeError("No supported X11/Wayland session detected")


def probe_and_erase(session):
    if session == "x11":
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.write(PROBE, interval=0.05)
        time.sleep(0.4)
        pyautogui.press("backspace", presses=len(PROBE), interval=0.05)
    else:
        run("ydotool", "type", "--file", "-", input_text=PROBE)
        time.sleep(0.4)
        run("ydotool", "key", *(v for _ in PROBE for v in ("14:1", "14:0")))


def activate_and_click(session, target):
    tool = window_tool(session)
    ox, oy, w, h = window_geometry(session, target.window_id)
    if (w, h) != (target.width, target.height):
        raise RuntimeError("Locked window was resized; pick the field again")
    run(tool, "windowactivate", target.window_id)
    time.sleep(0.5)
    if active_window(session) != target.window_id:
        raise RuntimeError("Could not activate target window; no text sent")
    x, y = ox + target.dx, oy + target.dy
    if session == "x11":
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.click(x, y)
    else:
        # Relative movement plus feedback; abort if KWin reports a missed position.
        for _ in range(5):
            cx, cy = mouse_position(session)
            if abs(cx - x) <= 5 and abs(cy - y) <= 5:
                break
            run("ydotool", "mousemove", "-x", str(x - cx), "-y", str(y - cy))
            time.sleep(0.15)
        cx, cy = mouse_position(session)
        if abs(cx - x) > 5 or abs(cy - y) > 5:
            raise RuntimeError(f"Pointer missed target ({cx},{cy} vs {x},{y}); no click sent")
        run("ydotool", "click", "0xC0")
    time.sleep(0.3)
    if active_window(session) != target.window_id:
        raise RuntimeError("Focus changed after target click; payload not sent")


class SchedulerApp(App):
    TITLE = "Resume Scheduler"
    SUB_TITLE = "X11 / KDE Wayland · Target Lock"
    CSS = """
    Screen { align: center middle; background: #1a1b26; }
    #main { width: 78; max-width: 100%; height: auto; padding: 1 2; border: double #7aa2f7; background: #24283c; }
    Label { color: #c0caf5; margin-top: 1; text-style: bold; }
    Input { background: #1f2335; color: #9ece6a; border: tall #414868; margin-bottom: 1; }
    Input:focus { border: tall #7aa2f7; }
    #backend { color: #bb9af7; margin-top: 1; }
    #target_state { color: #9ece6a; margin-top: 1; }
    #status { color: #e0af68; margin-top: 1; text-style: bold; }
    #countdown { color: #7dcfff; text-style: bold; margin: 1 0; padding: 1; height: 3; content-align: center middle; background: #1f2335; border: solid #414868; }
    #controls { height: auto; margin-top: 1; }
    Button { width: 1fr; margin: 0 1; }
    #arm_btn, #pick_btn { background: #3d59a1; color: #fff; }
    #cancel_btn, #clear_btn { background: #f7768e; color: #16161e; }
    Checkbox { color: #c0caf5; margin-top: 1; }
    Log { height: 7; margin-top: 1; background: #16161e; color: #a9b1d6; border: solid #414868; }
    """

    def __init__(self):
        super().__init__()
        self.session = session_type()
        self.target = None
        self.armed = self.sending = self.picking = False
        self.target_at = None
        self.payload = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main"):
            yield Label("TARGET TIME (24-hour HH:MM)")
            yield Input(value="06:50", placeholder="e.g. 06:50", id="target_time")
            yield Label("COMMAND (blank = Enter only)")
            yield Input(value="resume", placeholder="Leave blank for Enter only", id="command")
            yield Static(f"BACKEND: {self.session.upper()}", id="backend")
            yield Static("TARGET: Focused window at execution", id="target_state")
            yield Checkbox("Type + erase a temporary test marker while picking", value=True, id="probe")
            with Horizontal():
                yield Button("PICK TARGET (5s)", id="pick_btn")
                yield Button("CLEAR LOCK", id="clear_btn")
            yield Static("STATUS: IDLE", id="status")
            yield Static("--:--:--", id="countdown")
            with Horizontal(id="controls"):
                yield Button("ARM SCHEDULER", id="arm_btn")
                yield Button("CANCEL", id="cancel_btn", disabled=True)
            yield Log(id="log")
        yield Footer()

    def on_mount(self):
        self.log = self.query_one("#log", Log)
        self.say(f"Detected {self.session.upper()} session.")
        self.say("PICK captures window + pointer position after 5 seconds.")
        self.set_interval(0.25, self.tick)

    def say(self, msg):
        self.log.write_line(f"[{datetime.now():%H:%M:%S}] {msg}")

    def controls(self):
        busy = self.armed or self.sending or self.picking
        for sel in ("#target_time", "#command", "#probe", "#pick_btn", "#clear_btn", "#arm_btn"):
            self.query_one(sel).disabled = busy
        self.query_one("#cancel_btn", Button).disabled = not self.armed or self.sending

    def requirements(self, picker=False):
        if self.session not in ("x11", "wayland"):
            raise RuntimeError("Run in an X11 or Wayland desktop session")
        if self.session == "wayland" and not shutil.which("ydotool"):
            raise RuntimeError("Wayland requires ydotool and a running ydotoold")
        if self.session == "x11":
            try:
                import pyautogui  # noqa: F401
            except ImportError as e:
                raise RuntimeError("Install pyautogui in this virtual environment") from e
        if picker:
            tool = window_tool(self.session)
            if not shutil.which(tool):
                raise RuntimeError(f"Target lock requires {tool}; install/configure it first")

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "arm_btn":
            self.arm()
        elif bid == "cancel_btn":
            self.cancel()
        elif bid == "pick_btn":
            self.pick()
        elif bid == "clear_btn" and not (self.armed or self.sending or self.picking):
            self.target = None
            self.query_one("#target_state", Static).update("TARGET: Focused window at execution")
            self.say("Target lock cleared; focused-window mode.")

    def pick(self):
        if self.armed or self.sending or self.picking:
            return
        try:
            self.requirements(picker=True)
        except Exception as e:
            self.say(f"PICK ERROR: {e}")
            return
        self.target = None
        self.picking = True
        self.controls()
        asyncio.create_task(self.pick_worker())

    async def pick_worker(self):
        try:
            for n in range(PICK_SECONDS, 0, -1):
                self.query_one("#status", Static).update(f"STATUS: CLICK FIELD IN {n}s")
                if n == PICK_SECONDS:
                    self.say("Switch to target app and click its input field now.")
                await asyncio.sleep(1)
            target = await asyncio.to_thread(capture_target, self.session)
            if self.query_one("#probe", Checkbox).value:
                await asyncio.to_thread(probe_and_erase, self.session)
            self.target = target
            self.query_one("#target_state", Static).update(f"LOCKED: {target.title[:38]} (+{target.dx}, +{target.dy})")
            self.query_one("#status", Static).update("STATUS: TARGET LOCKED")
            self.say(f"Captured window {target.title!r}; marker removal cannot be verified.")
        except Exception as e:
            self.target = None
            self.query_one("#target_state", Static).update("TARGET: No lock (focus mode)")
            self.query_one("#status", Static).update("STATUS: PICK FAILED")
            self.say(f"PICK ERROR: {type(e).__name__}: {e}")
        finally:
            self.picking = False
            self.controls()

    def arm(self):
        if self.armed or self.sending or self.picking:
            return
        try:
            self.requirements()
        except Exception as e:
            self.say(f"ERROR: {e}")
            return
        t = self.query_one("#target_time", Input).value.strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t):
            self.say("ERROR: Time must be HH:MM (00:00-23:59).")
            return
        hh, mm = map(int, t.split(":"))
        now = datetime.now()
        at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)
        self.target_at = at
        self.payload = self.query_one("#command", Input).value
        self.armed = True
        self.controls()
        self.query_one("#status", Static).update("STATUS: ARMED")
        self.say(f"Armed for {at:%Y-%m-%d %H:%M:%S}; {'locked target' if self.target else 'focused window'}.")
        self.say(f"Payload: {self.payload!r}" if self.payload else "Payload is blank: Enter only.")
        self.tick()

    def cancel(self):
        if not self.armed or self.sending:
            return
        self.armed = False
        self.target_at = None
        self.controls()
        self.query_one("#status", Static).update("STATUS: CANCELLED")
        self.query_one("#countdown", Static).update("--:--:--")
        self.say("Schedule cancelled.")

    def tick(self):
        if not self.armed or self.target_at is None:
            return
        seconds = (self.target_at - datetime.now()).total_seconds()
        if seconds <= 0:
            self.armed = False
            self.sending = True
            self.controls()
            self.query_one("#status", Static).update("STATUS: EXECUTING")
            self.query_one("#countdown", Static).update("EXECUTING NOW")
            asyncio.create_task(self.execute())
            return
        seconds = math.ceil(seconds)
        h, rest = divmod(seconds, 3600)
        m, s = divmod(rest, 60)
        self.query_one("#countdown", Static).update(f"TIME REMAINING: {h:02d}:{m:02d}:{s:02d}")

    async def execute(self):
        try:
            if self.target:
                await asyncio.to_thread(activate_and_click, self.session, self.target)
            await asyncio.to_thread(inject, self.session, self.payload)
        except Exception as e:
            self.say(f"EXECUTION FAILED: {type(e).__name__}: {e}")
            self.query_one("#status", Static).update("STATUS: FAILED")
            self.query_one("#countdown", Static).update("EXECUTION FAILED")
        else:
            self.say("Input events sent; target application response is not verified.")
            self.query_one("#status", Static).update("STATUS: COMPLETED")
            self.query_one("#countdown", Static).update("EXECUTION COMPLETED")
        finally:
            self.armed = self.sending = False
            self.target_at = None
            self.controls()


if __name__ == "__main__":
    SchedulerApp().run()
