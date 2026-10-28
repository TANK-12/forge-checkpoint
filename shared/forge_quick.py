"""The hub's quick settings: brightness, volume, Wi-Fi, Bluetooth and the rest.

The tiles are declared in shared/quick_settings.json (one entry each); this
module only knows how to run an entry's commands and read their output, plus
the few list providers in ITEMS that need real parsing (Wi-Fi networks,
Bluetooth devices, an app's modes over its own HTTP API). forge.py hands it
the hub's {quick: {...}} messages on a worker thread:

    {"op": "read"}                              every tile's state
    {"op": "set", "id": "brightness", "value": 40}
    {"op": "set", "id": "wifi", "value": false}
    {"op": "items", "id": "wifi"}               the tile plus its list
    {"op": "pick", "id": "wifi", "item": "home", "secret": "..."}

and sends the answer back to window.forgeQuick. Every command is an argv list
run without a shell, so nothing the page sends is ever parsed by one.
Standard library only, so the GTK launcher can import it with system Python.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "quick_settings.json")
APPS_DIR = os.path.join(os.path.dirname(HERE), "apps")
KINDS = ("slider", "toggle", "choice")
MAC = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")

# run(argv, timeout) -> (exit code, stdout and stderr together)
Runner = Callable[[list[str], float], tuple[int, str]]
# fetch(method, url) -> parsed JSON, raising OSError when the app is not up
Fetcher = Callable[[str, str], object]


def run_command(argv: list[str], timeout: float = 8.0) -> tuple[int, str]:
    if not shutil.which(argv[0]):
        return 127, f"{argv[0]} is not installed"
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return 124, f"{argv[0]} took longer than {timeout:g} s"
    except OSError as e:
        return 126, str(e)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def fetch_json(method: str, url: str) -> object:
    req = urllib.request.Request(
        url, method=method, data=b"" if method == "POST" else None
    )
    try:
        # a mode change runs Power's root helper; a reading should be quick
        with urllib.request.urlopen(req, timeout=20 if method == "POST" else 6) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}").get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise QuickError(str(detail or f"the app answered {e.code}")) from e


class QuickError(Exception):
    """A change that did not happen, with a sentence for the panel."""


class NeedSecret(QuickError):
    """A network that wants a password the panel has not sent yet."""


def _argvs(spec: object) -> list[list[str]]:
    """turn_on/turn_off/set: one argv, or a list of them run in order."""
    if isinstance(spec, list) and spec and all(isinstance(a, str) for a in spec):
        return [list(spec)]
    if isinstance(spec, list) and all(
        isinstance(a, list) and a and all(isinstance(s, str) for s in a) for a in spec
    ):
        return [list(a) for a in spec]
    return []


def load_tiles(path: str = REGISTRY) -> list[dict]:
    """The registry's tiles, each checked; a broken entry is a ValueError
    naming it, so a typo is caught by the tests rather than in the panel."""
    with open(path, encoding="utf-8") as f:
        tiles = json.load(f).get("tiles")
    if not isinstance(tiles, list):
        raise ValueError(f"{path}: no tiles list")
    seen = set()
    for t in tiles:
        tid = t.get("id") if isinstance(t, dict) else None
        if not isinstance(tid, str) or not tid or tid in seen:
            raise ValueError(f"{path}: tile without a unique id: {t!r}")
        seen.add(tid)
        if t.get("kind") not in KINDS:
            raise ValueError(f"{tid}: kind must be one of {KINDS}")
        if not isinstance(t.get("label"), str):
            raise ValueError(f"{tid}: no label")
        if "items" in t and t["items"] not in ITEMS:
            raise ValueError(f"{tid}: no items provider called {t['items']!r}")
        for key in ("read", "set", "turn_on", "turn_off"):
            if key in t and not _argvs(t[key]):
                raise ValueError(
                    f"{tid}: {key} must be an argv list (or a list of them)"
                )
        if t["kind"] == "slider" and not ("read" in t and "value" in t and "set" in t):
            raise ValueError(f"{tid}: a slider needs read, value and set")
        if t["kind"] == "toggle" and not (
            "read" in t and "on" in t and "turn_on" in t and "turn_off" in t
        ):
            raise ValueError(f"{tid}: a toggle needs read, on, turn_on and turn_off")
        if t["kind"] == "choice" and "items" not in t:
            raise ValueError(f"{tid}: a choice needs an items provider")
        for key in ("value", "on"):
            if key in t:
                re.compile(t[key].get("match", ""))
        if "detail" in t:
            if not _argvs(t["detail"].get("read")):
                raise ValueError(f"{tid}: detail needs a read argv")
            re.compile(t["detail"].get("match", ""))
    return tiles


def _matches(spec: dict, out: str) -> bool:
    hit = re.search(spec.get("match", ""), out) is not None
    if spec.get("invert"):
        # nothing at all is not "nothing unblocked": no reading, no state
        return bool(out.strip()) and not hit
    return hit


def _value(spec: dict, out: str) -> int | None:
    m = re.search(spec.get("match", ""), out)
    if not m:
        return None
    try:
        return round(float(m.group(1)) * float(spec.get("scale", 1)))
    except (IndexError, ValueError):
        return None


def _fields(line: str) -> list[str]:
    """One line of nmcli -t: fields split on ':' that is not escaped as '\\:'."""
    out, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


# --- list providers ----------------------------------------------------------
# items(quick, tile) -> {"items": [...], ...tile fields to merge}
# pick(quick, tile, item, secret) -> None, or raises QuickError


def _wifi_items(q: "Quick", tile: dict, fresh: bool = False) -> dict:
    code, out = q.run(
        [
            "nmcli",
            "-t",
            "-f",
            "IN-USE,SSID,SIGNAL,SECURITY",
            "dev",
            "wifi",
            "list",
            "--rescan",
            # "Look again" scans now; auto reuses a scan under 30 s old
            "yes" if fresh else "auto",
        ],
        15,
    )
    if code != 0:
        raise QuickError(out.strip() or "nmcli could not list networks")
    known = q.saved_wifi()
    nets: dict[str, dict] = {}
    for line in out.splitlines():
        f = _fields(line)
        if len(f) < 4 or not f[1]:
            continue  # a hidden network has no name to pick
        ssid, active = f[1], f[0].strip() == "*"
        signal = int(f[2]) if f[2].isdigit() else 0
        secure = f[3].strip() not in ("", "--")
        n = nets.get(ssid)
        if n is None:
            nets[ssid] = n = {
                "id": ssid,
                "label": ssid,
                "signal": signal,
                "active": active,
            }
        n["signal"] = max(n["signal"], signal)
        n["active"] = n["active"] or active
        n["secure"] = n.get("secure", False) or secure
        n["known"] = ssid in known
    items = sorted(
        nets.values(), key=lambda n: (not n["active"], not n["known"], -n["signal"])
    )
    for n in items:
        bits = [f"{n['signal']}%"]
        if n["active"]:
            bits.insert(0, "connected")
        elif n["known"]:
            bits.append("saved")
        if n["secure"] and not n["known"]:
            bits.append("password")
        n["detail"] = " · ".join(bits)
    return {"items": items}


def _wifi_pick(q: "Quick", tile: dict, item: str, secret: str | None) -> None:
    if not item or len(item) > 32:
        raise QuickError("that is not a network name")
    if item.startswith("-"):
        # nmcli would read it as one of its own options
        raise QuickError("a name starting with - cannot be joined from here")
    # The password goes to nmcli as an argument (briefly visible in ps on
    # this single-user laptop); a saved network gets it written into its
    # profile first, so a changed password can be put right from the panel.
    cmds: list[list[str]] = []
    if item in q.saved_wifi():
        if secret:
            cmds.append(
                ["nmcli", "connection", "modify", "id", item, "wifi-sec.psk", secret]
            )
        cmds.append(["nmcli", "connection", "up", "id", item])
    else:
        cmds.append(["nmcli", "dev", "wifi", "connect", item])
        if secret:
            cmds[0] += ["password", secret]
    for argv in cmds:
        code, out = q.run(argv, 45)
        if code != 0:
            text = out.strip().splitlines()[-1] if out.strip() else "could not connect"
            if not secret and re.search(r"[Ss]ecret|password", out):
                raise NeedSecret("needs a password")
            raise QuickError(text.replace("Error: ", ""))


def _bt_items(q: "Quick", tile: dict, fresh: bool = False) -> dict:
    code, paired = q.run(["bluetoothctl", "devices", "Paired"], 8)
    if code != 0:
        raise QuickError(paired.strip() or "bluetoothctl could not list devices")
    _, connected = q.run(["bluetoothctl", "devices", "Connected"], 8)
    on = {m.group(1) for m in re.finditer(r"(?m)^Device (\S+) ", connected)}
    items = [
        {
            "id": m.group(1),
            "label": m.group(2),
            "active": m.group(1) in on,
            "detail": "connected" if m.group(1) in on else "paired",
            "toggles": True,
        }
        for m in re.finditer(r"(?m)^Device (\S+) (.+)$", paired)
    ]
    items.sort(key=lambda d: (not d["active"], d["label"].lower()))
    return {"items": items}


def _bt_pick(q: "Quick", tile: dict, item: str, secret: str | None) -> None:
    if not MAC.match(item or ""):
        raise QuickError("that is not a Bluetooth address")
    _, connected = q.run(["bluetoothctl", "devices", "Connected"], 8)
    verb = "disconnect" if f"Device {item} " in connected else "connect"
    code, out = q.run(["bluetoothctl", verb, item], 25)
    if code != 0 or re.search(r"Failed|not available", out):
        lines = [ln for ln in out.strip().splitlines() if ln.strip()]
        raise QuickError(lines[-1] if lines else f"could not {verb}")


def _app_port(q: "Quick", role: str) -> tuple[str, int] | None:
    for path in sorted(glob.glob(os.path.join(q.apps_dir, "*", "forge_app.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if m.get("role") == role and isinstance(m.get("port"), int):
            return (
                str(m.get("name") or os.path.basename(os.path.dirname(path))),
                m["port"],
            )
    return None


def _modes_items(q: "Quick", tile: dict, fresh: bool = False) -> dict:
    found = _app_port(q, str(tile.get("app_role") or ""))
    if found is None:
        return {"available": False, "detail": "no app for it", "items": []}
    name, port = found
    try:
        data = q.fetch("GET", f"http://127.0.0.1:{port}/api/modes")
    except (OSError, QuickError):
        # Not running: the hub offers to start it (its own start message).
        return {
            "available": False,
            "start_app": name,
            "detail": "tap to start",
            "items": [],
        }
    data = data if isinstance(data, dict) else {}
    current = data.get("current")
    modes = sorted(
        (m for m in data.get("modes") or [] if isinstance(m, dict) and m.get("name")),
        key=lambda m: m.get("order") or 0,
    )
    items = [
        {
            "id": m["name"],
            "label": str(m.get("label") or m["name"]),
            "detail": str(m.get("description") or ""),
            "active": m["name"] == current,
        }
        for m in modes
    ]
    label = next((i["label"] for i in items if i["active"]), "")
    out: dict = {"items": items, "detail": label, "app": name}
    if data.get("helper_installed") is False:
        out["detail"] = "helper not installed"
    return out


def _modes_pick(q: "Quick", tile: dict, item: str, secret: str | None) -> None:
    found = _app_port(q, str(tile.get("app_role") or ""))
    if found is None:
        raise QuickError("no app for it")
    if not re.match(r"^[\w-]{1,40}$", item or ""):
        raise QuickError("that is not a mode name")
    try:
        q.fetch(
            "POST", f"http://127.0.0.1:{found[1]}/api/modes/{urllib.parse.quote(item)}"
        )
    except TimeoutError as e:
        # the mode may still be applying: Power's helper is slow, not gone
        raise QuickError(f"{found[0]} did not answer in time") from e
    except OSError as e:
        if isinstance(getattr(e, "reason", None), TimeoutError):
            raise QuickError(f"{found[0]} did not answer in time") from e
        raise QuickError(f"{found[0]} is not running") from e


ITEMS: dict[str, tuple[Callable[..., dict], Callable[..., None]]] = {
    "wifi_networks": (_wifi_items, _wifi_pick),
    "bt_devices": (_bt_items, _bt_pick),
    "app_modes": (_modes_items, _modes_pick),
}


class Quick:
    """Reads and changes the registry's tiles. One lock per tile, so a slider
    dragged faster than its command runs never queues a pile of commands: a
    set that finds the tile busy leaves its value for the running one to
    pick up last."""

    def __init__(
        self,
        tiles: list[dict] | None = None,
        run: Runner = run_command,
        fetch: Fetcher = fetch_json,
        apps_dir: str = APPS_DIR,
        settle: float = 0.8,
    ):
        self.tiles = load_tiles() if tiles is None else tiles
        self.by_id = {t["id"]: t for t in self.tiles}
        self.run = run
        self.fetch = fetch
        self.apps_dir = apps_dir
        self.settle = settle
        self._locks = {t["id"]: threading.Lock() for t in self.tiles}
        self._pending: dict[str, int] = {}

    def saved_wifi(self) -> set[str]:
        code, out = self.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], 8
        )
        if code != 0:
            return set()
        return {
            f[0]
            for f in map(_fields, out.splitlines())
            if len(f) >= 2 and f[1] == "802-11-wireless"
        }

    def _public(self, t: dict) -> dict:
        return {
            "id": t["id"],
            "label": t["label"],
            "icon": t.get("icon", ""),
            "kind": t["kind"],
            "min": int(t.get("min", 0)),
            "max": int(t.get("max", 100)),
            "has_items": "items" in t,
            "can_mute": t["kind"] == "slider" and "on" in t,
            "bar": t.get("bar") is True,
            "list_label": str(t.get("list_label") or ""),
            "available": True,
        }

    def read(self, tid: str) -> dict:
        t = self.by_id[tid]
        s = self._public(t)
        if "read" in t:
            code, out = self.run(_argvs(t["read"])[0], 5)
            if code != 0:
                s["available"] = False
                s["detail"] = "not available" if code != 127 else out.strip()
                return s
            if "value" in t:
                s["value"] = _value(t["value"], out)
                if s["value"] is None:
                    s["available"] = False
                    s["detail"] = "no reading"
                    return s
            if "on" in t:
                s["on"] = _matches(t["on"], out)
        if "detail" in t and s.get("on", True):
            code, out = self.run(_argvs(t["detail"]["read"])[0], 5)
            if code == 0:
                found = [
                    m if isinstance(m, str) else m[0]
                    for m in re.findall(t["detail"].get("match", ""), out)
                ]
                # nmcli -t writes a ':' inside a name as '\\:'
                found = [x.replace("\\:", ":").strip() for x in found]
                if found:
                    s["detail"] = ", ".join(x for x in found if x)
        if t["kind"] == "choice":
            try:
                s.update(ITEMS[t["items"]][0](self, t))
            except QuickError as e:
                s.update(available=False, detail=str(e), items=[])
        return s

    def read_all(self) -> list[dict]:
        with ThreadPoolExecutor(max_workers=max(1, len(self.tiles))) as pool:
            return list(pool.map(self._read_safe, [t["id"] for t in self.tiles]))

    def _read_safe(self, tid: str) -> dict:
        try:
            return self.read(tid)
        except Exception as e:  # one broken tile never blanks the panel
            s = self._public(self.by_id[tid])
            s.update(available=False, detail=f"error: {e}")
            return s

    def _run_all(self, cmds: list[list[str]]) -> None:
        for argv in cmds:
            code, out = self.run(argv, 10)
            if code != 0:
                # a radio just unblocked takes a moment to show up: once more
                time.sleep(self.settle)
                code, out = self.run(argv, 10)
            if code != 0:
                lines = [ln for ln in out.strip().splitlines() if ln.strip()]
                raise QuickError(lines[-1] if lines else f"{argv[0]} failed")

    def set(self, tid: str, value: object) -> dict:
        t = self.by_id[tid]
        if isinstance(value, bool):
            if "turn_on" not in t:
                raise QuickError(f"{t['label']} has no on/off")
            self._run_all(_argvs(t["turn_on" if value else "turn_off"]))
            return self.read(tid)
        if t["kind"] != "slider" or not isinstance(value, (int, float)):
            raise QuickError(f"{t['label']} takes no number")
        lo, hi = int(t.get("min", 0)), int(t.get("max", 100))
        self._pending[tid] = max(lo, min(hi, int(round(value))))
        lock = self._locks[tid]
        while True:
            if not lock.acquire(blocking=False):
                return self._public(t) | {"value": self._pending[tid], "busy": True}
            try:
                while tid in self._pending:
                    v = self._pending.pop(tid)
                    cmds = [
                        [a.replace("{value}", str(v)) for a in argv]
                        for argv in _argvs(t["set"])
                    ]
                    if t.get("unmute_on_set") and "turn_on" in t:
                        cmds += _argvs(t["turn_on"])
                    self._run_all(cmds)
            finally:
                lock.release()
            # a value left between the last check and the release: once more
            if tid not in self._pending:
                break
        return self.read(tid)

    def items(self, tid: str, fresh: bool = False) -> dict:
        t = self.by_id[tid]
        if "items" not in t:
            raise QuickError(f"{t['label']} has no list")
        s = self.read(tid)
        if t["kind"] != "choice":
            s.update(ITEMS[t["items"]][0](self, t, fresh))
        return s

    def pick(self, tid: str, item: str, secret: str | None = None) -> dict:
        t = self.by_id[tid]
        if "items" not in t:
            raise QuickError(f"{t['label']} has no list")
        ITEMS[t["items"]][1](self, t, str(item or ""), secret or None)
        try:
            return self.items(tid)
        except QuickError:
            # the change happened; a list that will not refresh is no error
            return self.read(tid)

    def handle(self, req: dict) -> dict:
        """One hub message to one answer for window.forgeQuick. Never raises:
        a failure comes back as {"error": ...} beside the tile's fresh state."""
        op = str(req.get("op") or "read")
        tid = str(req.get("id") or "")
        if op == "read":
            return {"op": op, "tiles": self.read_all()}
        if tid not in self.by_id:
            return {"op": op, "id": tid, "error": "no such tile"}
        try:
            if op == "set":
                tile = self.set(tid, req.get("value"))
            elif op == "items":
                tile = self.items(tid, req.get("fresh") is True)
            elif op == "pick":
                secret = req.get("secret")
                tile = self.pick(
                    tid,
                    str(req.get("item") or ""),
                    secret if isinstance(secret, str) else None,
                )
            else:
                return {"op": op, "id": tid, "error": f"unknown op {op}"}
        except Exception as e:  # noqa: BLE001 -- the panel must hear back
            text = str(e) if isinstance(e, QuickError) else f"{type(e).__name__}: {e}"
            out = {"op": op, "id": tid, "error": text, "tile": self._read_safe(tid)}
            if op == "pick":
                out["item"] = req.get("item")
                out["need_secret"] = isinstance(e, NeedSecret)
            return out
        return {"op": op, "id": tid, "tile": tile}
