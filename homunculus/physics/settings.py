"""Authoring settings shared by every simulation: duration, reach pose, gains, obstacle."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Edit:
    duration: float = 4.0
    shoulder_deg: float = 65.0
    elbow_deg: float = -35.0
    strength: float = 1.0
    damping: float = 1.0
    obstacle: bool = True

    @classmethod
    def parse(cls, values):
        if not isinstance(values, dict) or set(values) - set(cls.__dataclass_fields__):
            raise ValueError('Unknown authoring fields')
        result = cls(**values)
        for key, lo, hi in [
            ('duration', 2, 30),
            ('shoulder_deg', 5, 100),
            ('elbow_deg', -100, 30),
            ('strength', 0.1, 2),
            ('damping', 0.2, 3),
        ]:
            val = getattr(result, key)
            if (
                isinstance(val, bool)
                or not isinstance(val, (float, int))
                or not math.isfinite(val)
                or not lo <= val <= hi
            ):
                raise ValueError(f'{key} must be finite and within [{lo}, {hi}]')
        if type(result.obstacle) is not bool:
            raise ValueError('obstacle must be boolean')
        return result
