"""Forge pad: a PS5 DualSense drives the whole desktop as mouse and keys.

Left stick moves the pointer, right stick scrolls, buttons follow
forge_pad.json. Stdlib only (raw evdev reads, legacy uinput writes). The
mapper goes quiet while a window listed in native_gamepad_windows has focus,
so games that read the pad themselves do not get doubled input.
"""

import fcntl
import json
import os
import select
import struct
import subprocess
import time
from pathlib import Path

CONFIG = Path(__file__).with_name("forge_pad.json")
EVENT = struct.Struct("llHHi")
EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
REL_X, REL_Y, REL_HWHEEL, REL_WHEEL = 0, 1, 6, 8
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT = 0x40045564, 0x40045565, 0x40045566
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502

KEYS = {
    "KEY_ESC": 1,
    "KEY_TAB": 15,
    "KEY_ENTER": 28,
    "KEY_LEFTCTRL": 29,
    "KEY_LEFTSHIFT": 42,
    "KEY_LEFTALT": 56,
    "KEY_SPACE": 57,
    "KEY_M": 50,
    "KEY_0": 11,
    "KEY_F11": 87,
    "KEY_UP": 103,
    "KEY_LEFT": 105,
    "KEY_RIGHT": 106,
    "KEY_DOWN": 108,
    "KEY_LEFTMETA": 125,
    "KEY_BACK": 158,
    "KEY_FORWARD": 159,
    "BTN_LEFT": 272,
    "BTN_RIGHT": 273,
    "BTN_MIDDLE": 274,
}
PAD_BUTTONS = {
    304: "cross",
    305: "circle",
    307: "triangle",
    308: "square",
    310: "l1",
    311: "r1",
    312: "l2",
    313: "r2",
    314: "create",
    315: "options",
    316: "ps",
    317: "l3",
    318: "r3",
}
HAT_X, HAT_Y = 16, 17


def parse_action(action):
    """'key:A+B' or 'click:BTN_LEFT' -> list of key codes pressed in order."""
    _, _, names = action.partition(":")
    return [KEYS[n] for n in names.split("+") if n]


def stick(raw, deadzone):
    """Map a 0..255 axis to -1..1 with a deadzone and a curve for fine aim."""
    v = (raw - 128) / 127.0
    if abs(v) < deadzone:
        return 0.0
    v = (abs(v) - deadzone) / (1 - deadzone) * (1 if v > 0 else -1)
    return max(-1.0, min(1.0, v * abs(v)))


def find_pad(name):
    for dev in sorted(Path("/sys/class/input").glob("event*")):
        try:
            dev_name = (dev / "device/name").read_text().strip()
        except OSError:
            continue
        if dev_name.endswith(name):
            return f"/dev/input/{dev.name}"
    return None


def make_uinput():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    for ev in (EV_KEY, EV_REL, EV_SYN):
        fcntl.ioctl(fd, UI_SET_EVBIT, ev)
    for code in KEYS.values():
        fcntl.ioctl(fd, UI_SET_KEYBIT, code)
    for code in (REL_X, REL_Y, REL_WHEEL, REL_HWHEEL):
        fcntl.ioctl(fd, UI_SET_RELBIT, code)
    name = b"Forge pad".ljust(80, b"\0")
    os.write(fd, name + struct.pack("HHHHi", 3, 0x1, 0x1, 1, 0) + bytes(4 * 64 * 4))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    return fd


class Out:
    def __init__(self, fd):
        self.fd = fd

    def emit(self, etype, code, value):
        os.write(self.fd, EVENT.pack(0, 0, etype, code, value))

    def sync(self):
        self.emit(EV_SYN, 0, 0)

    def press(self, codes, down):
        for code in codes if down else reversed(codes):
            self.emit(EV_KEY, code, 1 if down else 0)
        self.sync()


def hypr_env():
    """The service starts without Hyprland's socket name; find the live one."""
    env = dict(os.environ)
    if "HYPRLAND_INSTANCE_SIGNATURE" not in env:
        runs = sorted(
            Path(f"/run/user/{os.getuid()}/hypr").glob("*/.socket.sock"),
            key=lambda p: p.stat().st_mtime,
        )
        if runs:
            env["HYPRLAND_INSTANCE_SIGNATURE"] = runs[-1].parent.name
    return env


def pad_should_idle(cfg, cache={"t": 0.0, "v": True}):
    """True unless a Forge window has focus and it is not a native-pad game."""
    now = time.monotonic()
    flag = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "forge" / "pad-focus"
    if flag.exists():  # Forge writes this on any desktop (forge_popout.py)
        try:
            return flag.read_text().strip() != "1"
        except OSError:
            return True
    if now - cache["t"] > 0.5:
        cache["t"] = now
        try:
            win = json.loads(
                subprocess.run(
                    ["hyprctl", "activewindow", "-j"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                ).stdout
                or "{}"
            )
            text = f"{win.get('class', '')} {win.get('title', '')}".lower()
            ours = any(n in text for n in cfg["active_windows"])
            native = any(n in text for n in cfg["native_gamepad_windows"])
            cache["v"] = native or not ours
        except (OSError, ValueError, subprocess.SubprocessError):
            cache["v"] = True
    return cache["v"]


def run_pad(path, cfg, out):
    actions = {k: parse_action(v) for k, v in cfg["buttons"].items()}
    axes = {0: 128, 1: 128, 3: 128, 4: 128}
    held = {}
    frac = {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
    dz, speed, sspeed = cfg["deadzone"], cfg["mouse_speed"], cfg["scroll_speed"]
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 1 / 120)
            quiet = pad_should_idle(cfg)
            if ready:
                data = os.read(fd, EVENT.size * 64)
                for i in range(0, len(data), EVENT.size):
                    _, _, etype, code, value = EVENT.unpack_from(data, i)
                    if etype == EV_ABS and code in axes:
                        axes[code] = value
                    elif etype == EV_ABS and code in (HAT_X, HAT_Y):
                        neg, pos = (
                            ("dpad_left", "dpad_right")
                            if code == HAT_X
                            else ("dpad_up", "dpad_down")
                        )
                        for btn, on in ((neg, value < 0), (pos, value > 0)):
                            set_button(btn, on and not quiet, actions, held, out)
                    elif etype == EV_KEY and code in PAD_BUTTONS:
                        set_button(
                            PAD_BUTTONS[code], value and not quiet, actions, held, out
                        )
            if quiet:
                for btn in list(held):
                    set_button(btn, False, actions, held, out)
                continue
            moved = False
            for key, rel, val, k in (
                ("x", REL_X, stick(axes[0], dz), speed),
                ("y", REL_Y, stick(axes[1], dz), speed),
                ("w", REL_WHEEL, -stick(axes[4], dz), sspeed),
                ("h", REL_HWHEEL, stick(axes[3], dz), sspeed),
            ):
                frac[key] += val * k
                step = int(frac[key])
                if step:
                    frac[key] -= step
                    out.emit(EV_REL, rel, step)
                    moved = True
            if moved:
                out.sync()
    finally:
        for btn in list(held):
            set_button(btn, False, actions, held, out)
        os.close(fd)


def set_button(btn, down, actions, held, out):
    codes = actions.get(btn)
    if not codes or bool(down) == (btn in held):
        return
    if down:
        held[btn] = codes
    else:
        held.pop(btn)
    out.press(codes, bool(down))


def main():
    cfg = json.loads(CONFIG.read_text())
    out = Out(make_uinput())
    while True:
        path = find_pad(cfg["device_name"])
        if path:
            try:
                run_pad(path, cfg, out)
            except OSError:
                pass  # controller unplugged or slept; look for it again
        time.sleep(2)


if __name__ == "__main__":
    main()
