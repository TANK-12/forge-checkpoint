"""Buy and hold: always invested. The benchmark every other idea must beat."""

META = {
    "id": "buy_and_hold",
    "name": "Buy and hold",
    "summary": "Put every dollar in and never sell. Each deposit is invested "
    "once there is enough cash for a sensible order.",
    "long_only": True,
    "params": [],
}


def targets(series, params):
    return [1.0] * len(series)
