"""Shared bounded capture/reference and transport contracts."""
import math

MAX_FRAMES = 901
MAX_DURATION_S = 30
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024


def number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{field} must be a finite number')
    return value


def object_value(value, field):
    if not isinstance(value, dict):
        raise ValueError(f'{field} must be an object')
    return value


class SampleGrid:
    """Select the nearest available frame at/after each fixed sampling instant.

    Half-millisecond tolerance accommodates millisecond-rounded decoder clocks.
    Late frames skip missed grid instants rather than accumulating drift.
    """
    def __init__(self, start, hz):
        self.start, self.hz, self.index = start, hz, 0

    def take(self, t):
        if t + .000501 < self.start + self.index / self.hz:
            return False
        self.index = max(self.index + 1, math.floor((t-self.start+.000501)*self.hz)+1)
        return True
