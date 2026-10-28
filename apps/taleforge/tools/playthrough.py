"""Play a few turns against a running Taleforge server and print what the
engine wrote next to what Jan made of it. Usage:

    .venv/bin/python tools/playthrough.py [--port 8502] [--campaign hollow-crown] "turn" "turn" ...

Each turn is free text, or `@{json action}` for a button press. It waits for
Jan after every turn (up to --wait seconds) so the output shows real retellings.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def call(base: str, path: str, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method or ("POST" if data else "GET")
    )
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": json.loads(e.read()).get("detail")}


def wait(base: str, sid: str, ids: list[str], limit: float) -> dict:
    end = time.time() + limit
    got: dict = {}
    while ids and time.time() < end:
        for e in call(base, f"/api/saves/{sid}/entries?ids={','.join(ids)}")["entries"]:
            if not e.get("pending"):
                got[e["id"]] = e
        ids = [i for i in ids if i not in got]
        time.sleep(1)
    return got


def show(entries: list[dict], done: dict) -> None:
    for e in entries:
        e = done.get(e["id"], e)
        who = e.get("name") or e.get("title") or ""
        head = f"[{e['kind']}{' ' + who if who else ''}]"
        if e.get("jan"):
            print(f"  {head} fallback: {e['text']!r}")
            print(
                f"      jan ({e['jan']['role']}, {e.get('jan_note', 'still pending')}): {e.get('jan_text')!r}"
            )
        elif e["kind"] == "topics":
            print(f"  {head} " + " | ".join(t["prompt"] for t in e["topics"]))
        elif e["text"]:
            print(f"  {head} {e['text']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8502)
    ap.add_argument("--campaign", default="hollow-crown")
    ap.add_argument("--wait", type=float, default=240)
    ap.add_argument("turns", nargs="*")
    a = ap.parse_args()
    base = f"http://127.0.0.1:{a.port}"
    cr = call(base, f"/api/campaigns/{a.campaign}/creation")
    cls = cr["classes"][0]
    bg = cr["backgrounds"][1]
    skills = [s for s in cls["skill_options"] if s not in bg["skills"]][
        : cls["skill_count"]
    ]
    arr = sorted(cr["ability_scores"]["standard_array"], reverse=True)
    scores = dict(zip([x["id"] for x in cr["abilities"]], arr))
    char = {
        "name": "Wren",
        "pronouns": "she/her",
        "class": cls["id"],
        "background": bg["id"],
        "method": "array",
        "scores": scores,
        "skills": skills,
    }
    v = call(base, "/api/saves", {"campaign": a.campaign, "character": char})
    sid = v["id"]
    print(f"save {sid}: {char['name']}, {cls['name']} / {bg['name']}")
    seen = {e["id"] for e in v["log"]}
    pend = [e["id"] for e in v["log"] if e.get("pending")]
    t0 = time.time()
    done = wait(base, sid, pend, a.wait)
    print(f"> (start)  [Jan took {time.time() - t0:.1f}s]")
    show(v["log"], done)
    for turn in a.turns:
        action = (
            json.loads(turn[1:])
            if turn.startswith("@")
            else {"do": "text", "text": turn}
        )
        v = call(base, f"/api/saves/{sid}/act", {"action": action})
        if "error" in v:
            print(f"> {turn}\n  refused: {v['error']}")
            continue
        new = [e for e in v["log"] if e["id"] not in seen]
        seen |= {e["id"] for e in new}
        t0 = time.time()
        done = wait(base, sid, [e["id"] for e in new if e.get("pending")], a.wait)
        print(f"> {turn}  [Jan took {time.time() - t0:.1f}s]")
        show(new, done)
    print(f"save id: {sid}")


if __name__ == "__main__":
    main()
