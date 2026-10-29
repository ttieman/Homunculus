"""Validate a capture bundle and turn it into the motion the physics step follows."""


def prepare(bundle):
    """capture.json (homunculus.observations.v1) -> SpatialMotion for spatial captures, else planar Motion."""
    if isinstance(bundle, dict) and bundle.get('retargeting') == 'spatial_arm_v1':
        from homunculus.capture.spatial import (
            prepare_spatial,
        )  # needs MuJoCo; the GPU worker only uses planar

        return prepare_spatial(bundle)
    from homunculus.capture.planar import prepare_planar

    return prepare_planar(bundle)
