"""Fire detection rules (paper §IV-1 "fire alarm systems, leveraging pre-existing sensors").

A node is on fire when any of:
  * smoke reading >= smoke_threshold (e.g. MQ-2 ppm-equivalent),
  * temperature >= temp_threshold_c (57 C - typical fixed-temperature heat detector rating),
  * temperature rising >= rate_of_rise_c_per_min (rate-of-rise heat detector rule),
  * a flame sensor or an alarm-panel relay contact reports true.
"""

from __future__ import annotations

from datetime import datetime


def evaluate(reading: dict, previous: list[tuple[datetime, float]], settings: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    smoke = reading.get("smoke")
    temp = reading.get("temperature_c")
    if smoke is not None and smoke >= float(settings.get("smoke_threshold", 300.0)):
        reasons.append(f"smoke {smoke:g} >= {settings.get('smoke_threshold')}")
    if temp is not None and temp >= float(settings.get("temp_threshold_c", 57.0)):
        reasons.append(f"temperature {temp:g}C >= {settings.get('temp_threshold_c')}C")
    if reading.get("flame"):
        reasons.append("flame detected")
    if reading.get("alarm"):
        reasons.append("alarm panel contact closed")
    if temp is not None and previous:
        now = reading["ts"]
        # compare with the oldest reading within the last ~2 minutes
        window = [(ts, t) for ts, t in previous if 20 <= (now - ts).total_seconds() <= 120]
        if window:
            ts0, t0 = window[0]
            minutes = (now - ts0).total_seconds() / 60.0
            rise = (temp - t0) / minutes
            if rise >= float(settings.get("rate_of_rise_c_per_min", 8.0)):
                reasons.append(f"temperature rising {rise:.1f}C/min")
    return bool(reasons), reasons
