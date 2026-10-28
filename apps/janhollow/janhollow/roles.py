"""Which model each role wants, and why.

the owner chose the pairing: "0.8B chatter plus 4B narrator". Without this file
the app asked shared/forge_jan.py for a model, got no answer from its settings,
and fell back to whatever Jan happened to list first -- which on 2026-09-16 was
an unrelated 2B that leaked thinking into the crew's mouths.

So this is the app's *preference*, not a hardcoding: the order of precedence is

1. what the person chose in the Jan settings panel (~/.config/forge/jan/janhollow.json),
2. the preferred model here, if Jan has it,
3. whatever Jan lists first, which is forge_jan's own last resort.

Changing the pairing is an edit to this registry; adding a third role is one
more entry plus the calls that use it.
"""

ROLES = {
    "chatter": {
        "label": "Crew chatter",
        "prefer": "qwen35-0_8b-spectralquant-calib360-q4_k_m",
        "why": (
            "Every line a crew member says. It answers in about 0.8 s and runs on the "
            "CPU -- its model.yml sets no n_gpu_layers -- which is what keeps the iGPU "
            "free for the narrator."
        ),
        "size": "416 MB",
    },
    "narrator": {
        "label": "Narrator",
        "prefer": "Qwen3_5-4B-IQ4_XS",
        "why": (
            "The day's event and the time-skip summary. About 21 s a paragraph on the "
            "iGPU (n_gpu_layers: 40), so it runs once a station day and never where "
            "anyone is waiting."
        ),
        "size": "3.0 GB",
    },
}


def preferences():
    return {role: spec["prefer"] for role, spec in ROLES.items()}


def describe():
    """For the settings panel, so the page can say what each role is for
    without repeating any of it."""
    return {
        role: {
            "label": spec["label"],
            "why": spec["why"],
            "prefer": spec["prefer"],
            "size": spec["size"],
        }
        for role, spec in ROLES.items()
    }
