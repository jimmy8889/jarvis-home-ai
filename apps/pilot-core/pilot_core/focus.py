from __future__ import annotations

from dataclasses import dataclass


SOURCE_PRIORITY = {
    "critical": 100,
    "assistant": 90,
    "bluetooth": 80,
    "airplay": 70,
    "music": 60,
}


@dataclass(frozen=True)
class FocusDecision:
    foreground: str | None
    gains: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        return {"foreground": self.foreground, "gains": self.gains}


def decide_focus(active: dict[str, bool], duck_gain: float = 0.2) -> FocusDecision:
    unknown = set(active) - set(SOURCE_PRIORITY)
    if unknown:
        raise ValueError(f"unknown audio source(s): {', '.join(sorted(unknown))}")
    if not 0 <= duck_gain <= 1:
        raise ValueError("duck_gain must be between 0 and 1")

    enabled = [source for source, is_active in active.items() if is_active]
    foreground = max(enabled, key=SOURCE_PRIORITY.__getitem__) if enabled else None
    gains: dict[str, float] = {}
    for source in SOURCE_PRIORITY:
        if not active.get(source, False):
            gains[source] = 0.0
        elif foreground is None or source == foreground:
            gains[source] = 1.0
        elif foreground in {"critical", "assistant"}:
            gains[source] = duck_gain
        else:
            gains[source] = 0.0
    return FocusDecision(foreground=foreground, gains=gains)
