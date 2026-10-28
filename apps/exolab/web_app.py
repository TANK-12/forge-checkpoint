"""Exo Lab backend: the page, the shared Forge kit and the physics API.

All physics lives in the engine-free ``exolab`` package; this file routes
HTTP to it and caches what is slow (bench runs and derived game stats). A
``profile`` in a request is either a saved profile's name or an inline
profile object, so the editor can re-run a test on edits it has not saved.

Run alone:
    FORGE_SHARED_DIR=~/Forge/shared .venv/bin/python -m uvicorn \
        web_app:app --host 127.0.0.1 --port 8466
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from exolab import arm, benches, derive, human, registry, report
from exolab.arm import kinematics, loads

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
SUIT_DIR = STATIC_DIR / "assets" / "suits"
REST_POSE = {"plane": 90.0, "elev": 8.0, "axial": 0.0, "elbow": 12.0}

if str(registry.SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(registry.SHARED_DIR))
import forge_revalidate  # noqa: E402  (lives in the shared folder)

app = FastAPI(title="Exo Lab")
forge_revalidate.revalidate(app)


@app.exception_handler(RequestValidationError)
async def _bad_body(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """A 422 with the reasons only: echoing the input back fails on NaN."""
    reasons = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": reasons})


REG = registry.Registry()


class _Lru:
    """A small thread-safe least-recently-used cache."""

    def __init__(self, size: int):
        self.size = size
        self.data: OrderedDict[str, Any] = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key: str, make: Callable[[], Any]) -> Any:
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                return self.data[key]
        value = make()
        with self.lock:
            self.data[key] = value
            while len(self.data) > self.size:
                self.data.popitem(last=False)
        return value

    def clear(self) -> None:
        with self.lock:
            self.data.clear()


RUNS = _Lru(24)
DERIVED = _Lru(32)


def _key(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()


def _profile(spec: str | dict | None) -> tuple[dict, list[str]]:
    """A saved profile by name (404 when there is none), or an inline one;
    both cleaned like a saved one. An inline profile that differs from the
    saved one of its name says so in its name, so a report cannot pass
    unsaved edits off as the saved profile."""
    return _call(lambda: _clean_spec(spec))


def _clean_spec(spec: str | dict | None) -> tuple[dict, list[str]]:
    if isinstance(spec, dict):
        name = str(spec.get("name") or "unsaved")
        prof, warnings = registry.clean_profile(name, spec, REG)
        # Compare clean with clean: a hand-edited file holding a value the
        # checks drop is still "unchanged" when the page sends it back.
        saved, _ = registry.clean_profile(name, _saved(name), REG)
        if registry.edits_of(prof) != registry.edits_of(saved):
            prof["name"] = f"{name} (unsaved edits)"
        return prof, warnings
    prof = registry.load_profile(spec)
    return registry.clean_profile(prof["name"], prof, REG)


def _saved(name: str) -> dict:
    try:
        return registry.load_profile(name)
    except (KeyError, ValueError, OSError):
        return registry.empty_profile(name)


def _call(fn: Callable[[], Any]) -> Any:
    """Turn core errors into HTTP ones: unknown ids, profiles and motions
    404; bad input, and a lookup the physics could not make, 400."""
    try:
        return fn()
    except registry.NotFound as e:
        raise HTTPException(404, str(e.args[0]) if e.args else "not found") from None
    except KeyError as e:
        missing = e.args[0] if e.args else "?"
        raise HTTPException(
            400, f"these settings leave out a value the physics needs: {missing!r}"
        ) from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except OSError as e:  # a profile file that is a folder, unreadable, ...
        raise HTTPException(
            400, f"a file could not be read or written: {e.strerror or e}"
        ) from None
    except ArithmeticError as e:
        raise HTTPException(
            400, f"these numbers break the physics ({type(e).__name__}: {e})"
        ) from None


def _joint_json(j) -> dict:
    return {
        "key": j.key,
        "name": j.name,
        "actuator": j.actuator_id,
        "kind": j.kind,
        "powered": j.powered,
        "mass_kg": round(j.mass + j.remote_mass, 3),
        "torque_cont_nm": round(j.torque_cont, 2),
        "torque_peak_nm": round(j.torque_peak, 2),
        "speed_max_rad_s": round(j.speed_max, 2),
        "power_cont_w": round(j.power_cont, 1),
        "stiffness_nm_rad": round(j.stiffness, 1),
        "efficiency": j.efficiency,
        "backdrivable": j.backdrivable,
    }


def _suit_json(rig: arm.Rig) -> dict:
    s = rig.suit
    links = [
        {
            "id": ln.id,
            "name": ln.name,
            "role": ln.role,
            "material": ln.material.id,
            "material_name": ln.material.name,
            "colour": ln.material.colour,
            "shape": ln.section.shape,
            "outer_mm": round(ln.section.outer * 1000, 1),
            "length_m": round(ln.length, 3),
            "mass_kg": round(ln.mass, 3),
            "stiffness_nm2": round(ln.stiffness, 1),
            "yield_mpa": round(ln.yield_strength / 1e6, 1),
        }
        for ln in s.links.values()
    ]
    cuffs = [
        {
            "id": c["id"],
            "name": c["name"],
            "segment": c.get("segment", "upper_arm"),
            "material_name": c["material_name"],
            "width_mm": round(c["width"] * 1000, 1),
            "radius_mm": round(c["radius"] * 1000, 1),
            "area_cm2": round(c["area"] * 1e4, 1),
            "mass_kg": round(c["mass"], 3),
        }
        for c in s.cuffs
    ]
    shells = [
        {
            "id": sh["id"],
            "name": sh["name"],
            "bone": sh.get("bone", ""),
            "material": sh["material"],
            "material_name": sh["material_name"],
            "thickness_mm": sh.get("thickness_mm", 2.5),
            "fit_gap_mm": sh.get("fit_gap_mm", 6),
            "copies": sh["copies"],
            "area_m2": round(sh["area"], 4),
            "area_measured": sh["area_measured"],
            "mass_kg": round(sh["mass"], 3),
        }
        for sh in s.shells
    ]
    joints = [_joint_json(j) for j in [*s.joints, s.elbow, *s.legs.values()]]
    return {
        "joints": joints,
        "links": links,
        "cuffs": cuffs,
        "shells": shells,
        "battery_wh": round(s.battery_wh, 1),
        "assist_share": s.assist_share,
        "masses": {k: round(v, 3) for k, v in s.masses.items()},
        "total_kg": round(s.mass, 2),
    }


def _suit_asset(asset: str | None) -> dict:
    out: dict[str, Any] = {"glb": None, "sidecar": None}
    if asset and (SUIT_DIR / f"{asset}.glb").is_file():
        out["glb"] = f"/assets/suits/{asset}.glb"
    if asset and (SUIT_DIR / f"{asset}.json").is_file():
        out["sidecar"] = f"/assets/suits/{asset}.json"
    return out


def _pose_frame(rig: arm.Rig, pose: dict, payload: float) -> dict:
    fr = kinematics(
        rig,
        float(pose["plane"]),
        float(pose["elev"]),
        float(pose.get("axial", 0.0)),
        float(pose.get("elbow", 0.0)),
        payload,
    )
    ld = loads(rig, fr)
    rules = benches.rules_for(rig, {})
    issues = benches.check(rig, fr, ld, rules)
    out = benches.frame_json(rig, fr, ld, issues, rules=rules)
    out["in_rom"] = human.in_rom(
        fr.pose.plane, fr.pose.elev, fr.pose.axial, fr.pose.elbow, rig.rom
    )
    return out


# ----- API -----


@app.get("/api/status")
def status() -> dict:
    return {"ok": True, "app": "exolab", "kinds": REG.kinds()}


@app.get("/api/registry")
def get_registry() -> dict:
    """Every data item in full (the editor edits them), plus the knob map,
    the bench and mechanism kinds the core knows, and the saved profiles."""
    return {
        "items": REG.items,
        "knobs": REG.knobs,
        "limits": REG.limits,
        "bench_kinds": sorted(benches.KINDS),
        "profiles": registry.list_profiles(),
        "characters": registry.characters(),
    }


@app.post("/api/reload")
def reload_data() -> dict:
    """Re-read data/ after a hand edit of the JSON files."""
    REG.reload()
    RUNS.clear()
    DERIVED.clear()
    return {"ok": True, "kinds": REG.kinds()}


def _model_json(model_id: str, prof: dict) -> dict:
    """The effective model: specs, masses, mechanism, suit asset, the rest frame."""
    model = _call(lambda: REG.effective("models", model_id, prof))
    out: dict[str, Any] = {
        "id": model_id,
        "name": model.get("name", model_id),
        "kind": model.get("kind", ""),
        "status": model.get("status", "planned"),
        "about": model.get("about", ""),
        "model": model,
        "suit_asset": _suit_asset(model.get("suit_asset")),
        # The knobs each part reads now (a drive swapped for a passive one
        # loses its power knob), so the editor can drop the stale ones; of
        # every model too, as models share a mechanism (both suits use the
        # girdle tracker, so a swap made on one changes the other's drives).
        "part_knobs": _call(lambda: REG.knobs_of_parts(model_id, prof)),
        "part_knobs_of": _call(
            lambda: {m: REG.knobs_of_parts(m, prof) for m in REG.ids("models")}
        ),
    }
    if out["status"] != "ready":
        return out
    rig = _call(lambda: arm.build(REG, model_id, prof))
    char_file = arm.character_path(rig.character).name
    out.update(
        {
            "character": {
                "id": rig.character,
                "url": f"/characters/{rig.character}/{char_file}",
                "vrm_version": rig.skel["vrm_version"],
                "height_m": rig.skel["height_estimate_m"],
            },
            "mechanism": rig.suit.mech,
            "suit": _suit_json(rig),
            "body": {
                "mass_kg": round(rig.body.mass, 1),
                "upper_arm_m": round(rig.body.l_upper, 3),
                "forearm_m": round(rig.body.l_fore, 3),
            },
            "rest": _call(lambda: _pose_frame(rig, REST_POSE, 0.0)),
        }
    )
    return out


@app.get("/api/model/{model_id}")
def get_model(model_id: str, profile: str | None = None) -> dict:
    return _model_json(model_id, _profile(profile)[0])


class ModelIn(BaseModel):
    model: str
    profile: str | dict | None = None


@app.post("/api/model")
def post_model(body: ModelIn) -> dict:
    """The same with an inline (unsaved) profile, so the editor's part table
    and 3D view follow edits before they are saved."""
    prof, warnings = _profile(body.profile)
    return dict(_model_json(body.model, prof), warnings=warnings)


def _deg(default: float, lo: float, hi: float) -> Any:
    return Field(default, ge=lo, le=hi, allow_inf_nan=False)


class PoseIn(BaseModel):
    """One arm pose; out-of-range or non-finite numbers get a 422."""

    model: str
    profile: str | dict | None = None
    plane: float = _deg(90.0, -180, 180)
    elev: float = _deg(0.0, 0, 180)
    axial: float = _deg(0.0, -180, 180)
    elbow: float = _deg(0.0, -30, 180)
    payload_kg: float = _deg(0.0, 0, 100)


@app.post("/api/pose")
def post_pose(body: PoseIn) -> dict:
    """Instant loads for one pose (the drag-the-arm mode)."""
    prof, warnings = _profile(body.profile)
    rig = _call(lambda: arm.build(REG, body.model, prof))
    pose = {
        "plane": body.plane,
        "elev": body.elev,
        "axial": body.axial,
        "elbow": body.elbow,
    }
    frame = _call(lambda: _pose_frame(rig, pose, max(0.0, body.payload_kg)))
    frame["warnings"] = warnings
    return frame


class RunIn(BaseModel):
    model: str
    test: str
    profile: str | dict | None = None
    only: str | None = None


def _run(model_id: str, test_id: str, prof: dict, only: str | None) -> dict:
    test = REG.effective("tests", test_id, prof)
    if only:
        test.setdefault("params", {})["only"] = only
    rig = arm.build(REG, model_id, prof)
    t0 = time.perf_counter()
    res = benches.run(rig, test, REG)
    res["ms"] = round((time.perf_counter() - t0) * 1000)
    res["test_name"] = test.get("name", test_id)
    res["model_name"] = rig.suit.model.get("name", model_id)
    res["profile"] = prof.get("name", "baseline")
    return res


@app.post("/api/run")
def post_run(body: RunIn) -> dict:
    """Run a bench test; the same inputs give the cached result."""
    prof, warnings = _profile(body.profile)
    key = _key("run", body.model, body.test, body.only, prof)
    res = _call(
        lambda: RUNS.get(key, lambda: _run(body.model, body.test, prof, body.only))
    )
    return dict(res, warnings=warnings)


@app.get("/api/derive/{model_id}")
def get_derive(model_id: str, profile: str | None = None) -> dict:
    """Game stats for the game half (and any other engine)."""
    prof, _ = _profile(profile)
    return _call(
        lambda: DERIVED.get(
            _key("derive", model_id, prof), lambda: derive.derive(REG, model_id, prof)
        )
    )


class DeriveIn(BaseModel):
    model: str
    profile: str | dict | None = None


@app.post("/api/derive")
def post_derive(body: DeriveIn) -> dict:
    """The same with an inline (unsaved) profile, for the editor."""
    prof, warnings = _profile(body.profile)
    res = _call(
        lambda: DERIVED.get(
            _key("derive", body.model, prof),
            lambda: derive.derive(REG, body.model, prof),
        )
    )
    return dict(res, warnings=warnings)


@app.get("/api/profiles")
def get_profiles() -> dict:
    return {"profiles": registry.list_profiles()}


@app.get("/api/profiles/{name}")
def get_profile(name: str) -> dict:
    return _profile(name)[0]


def _save(name: str, prof: dict) -> dict:
    """Save once each field passes (registry) and the rules between them
    (benches.cross_errors), so a profile that saves also runs."""
    return registry.save_profile(
        name, prof, REG, rules=lambda p: benches.cross_errors(REG, p)
    )


@app.put("/api/profiles/{name}")
def put_profile(name: str, body: dict) -> dict:
    saved = _call(lambda: _save(name, body))
    return {"ok": True, "profile": saved, "profiles": registry.list_profiles()}


class CopyIn(BaseModel):
    to: str


@app.post("/api/profiles/{name}/copy")
def copy_profile(name: str, body: CopyIn) -> dict:
    src, _ = _profile(name)
    if _call(lambda: registry.profile_path(body.to)).exists():
        raise HTTPException(409, f"a profile named {body.to!r} already exists")
    saved = _call(lambda: _save(body.to, src))
    return {"ok": True, "profile": saved, "profiles": registry.list_profiles()}


class ReportIn(BaseModel):
    model: str
    test: str
    profile: str | dict | None = None
    only: str | None = None


@app.post("/api/report")
def post_report(body: ReportIn) -> dict:
    """Save a dated markdown report of a run into the docs library."""
    prof, _ = _profile(body.profile)
    key = _key("run", body.model, body.test, body.only, prof)
    res = _call(
        lambda: RUNS.get(key, lambda: _run(body.model, body.test, prof, body.only))
    )
    path = report.save(res, res["model_name"], res["test_name"], prof)
    return {"ok": True, "path": str(path)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# The shared Forge kit (three.js, three-vrm, the theme) and the characters,
# mounted before the catch-all static mount, which would otherwise swallow
# the paths.
_SHARED = os.environ.get("FORGE_SHARED_DIR") or str(registry.SHARED_DIR)
if os.path.isdir(_SHARED):
    app.mount("/shared", StaticFiles(directory=_SHARED), name="shared")
if registry.CHAR_DIR.is_dir():
    app.mount(
        "/characters", StaticFiles(directory=str(registry.CHAR_DIR)), name="characters"
    )

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
