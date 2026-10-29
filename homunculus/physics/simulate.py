"""Pick the simulation that matches the prepared capture."""

from homunculus.capture.spatial import SpatialMotion
from homunculus.physics.planar import run_planar
from homunculus.physics.spatial import run_spatial


def run(edit, motion=None):
    if isinstance(motion, SpatialMotion):
        return run_spatial(edit, motion)
    return run_planar(edit, motion)
