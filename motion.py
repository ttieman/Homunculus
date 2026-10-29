"""Validated observations -> planar targets. No inference is performed here."""
from dataclasses import dataclass
import hashlib
import json
import numpy as np


@dataclass
class Motion:
    times: np.ndarray
    angles: np.ndarray
    metadata: dict

    def target(self, t, duration):
        source_t = np.clip(t/duration, 0, 1)*self.times[-1]
        return np.array([np.interp(source_t,self.times,self.angles[:,j]) for j in range(2)])


def prepare(bundle):
    if isinstance(bundle,dict) and bundle.get('retargeting')=='spatial_arm_v1':
        from spatial import prepare_spatial
        return prepare_spatial(bundle)
    if not isinstance(bundle,dict) or bundle.get('schema') != 'homunculus.observations.v1':
        raise ValueError('Expected homunculus.observations.v1 capture bundle')
    if 'timing' in bundle: raise ValueError('Segments require a spatial capture')
    provenance = bundle.get('provenance',{})
    if not isinstance(provenance,dict) or provenance.get('kind') not in ('sam3d','synthetic_test'):
        raise ValueError('Capture provenance must identify sam3d or synthetic_test')
    for key in ('model','revision','video_sha256'):
        if not isinstance(provenance.get(key),str) or not 1 <= len(provenance[key]) <= 200:
            raise ValueError('Missing or invalid provenance: '+key)
    frames = bundle.get('frames')
    if not isinstance(frames,list) or not 3 <= len(frames) <= 601:
        raise ValueError('Capture requires 3–601 timestamped observations')
    # Explicit basis, never assume native SAM axes are already game axes.
    basis = np.asarray(bundle.get('basis'),dtype=float)
    if basis.shape != (3,3) or not np.all(np.isfinite(basis)) or not np.allclose(basis@basis.T,np.eye(3),atol=1e-5) or not np.isclose(np.linalg.det(basis),1,atol=1e-5):
        raise ValueError('basis must be a finite right-handed orthonormal 3x3 matrix')
    times = np.array([f['t'] for f in frames],dtype=float)
    if not np.all(np.isfinite(times)) or np.any(np.diff(times)<=0):
        raise ValueError('Frame timestamps must be finite and strictly increasing')
    times -= times[0]
    if not 2 <= times[-1] <= 10:
        raise ValueError('Trim capture to 2–10 seconds of observations')
    if np.max(np.diff(times)) > .251:
        raise ValueError('Observation gaps over 250 ms require a new capture or trim')
    angles,valid,planes = [],[],[]
    for i,f in enumerate(frames):
        if f.get('arm') is None:
            continue
        points = np.asarray(f['arm'],dtype=float)
        if points.shape != (3,3) or not np.all(np.isfinite(points)):
            raise ValueError('Each arm must contain finite shoulder/elbow/wrist 3D coordinates')
        vectors = np.diff(points,axis=0)@basis.T
        lengths = np.linalg.norm(vectors,axis=1)
        if np.any(lengths<1e-6):
            raise ValueError('Degenerate arm segment')
        planes.extend(np.degrees(np.arcsin(np.clip(np.abs(vectors[:,2])/lengths,0,1))).tolist())
        absolute = np.arctan2(vectors[:,1],vectors[:,0])
        elbow = np.arctan2(np.sin(absolute[1]-absolute[0]),np.cos(absolute[1]-absolute[0]))
        angles.append([absolute[0],elbow]);valid.append(i)
    if len(valid)<3 or valid[0]!=0 or valid[-1]!=len(frames)-1:
        raise ValueError('First/last observations and at least three poses must be valid; trim the clip')
    valid_times = times[valid]
    if np.max(np.diff(valid_times)) > .251:
        raise ValueError('Missing pose gap exceeds 250 ms; no silent long-gap interpolation')
    max_plane = max(planes)
    if max_plane>25:
        raise ValueError(f'Arm leaves selected plane by {max_plane:.1f}° (limit 25°); recapture side-on or supply a calibrated basis')
    q = np.unwrap(np.array(angles),axis=0)
    if np.max(np.abs(np.diff(q,axis=0)/np.diff(valid_times)[:,None])) > np.radians(720):
        raise ValueError('Pose jumps exceed 720 degrees/second; inspect source estimates')
    full = np.column_stack([np.interp(times,valid_times,q[:,j]) for j in range(2)])
    # Time-based local averaging; retain endpoints, expose the raw motion separately.
    smooth = full.copy()
    for i,t in enumerate(times[1:-1],1):
        smooth[i] = np.mean(full[np.abs(times-t)<=.065],axis=0)
    if np.any(np.abs(full)>2.7) or np.any(np.abs(smooth)>2.7):
        raise ValueError('Capture exceeds supported ±155° joint targets; choose another take/basis')
    digest = hashlib.sha256(json.dumps(bundle,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return Motion(times,smooth,{'provenance':provenance,'bundle_sha256':digest,
        'source_duration_s':float(times[-1]),'missing_frames':len(frames)-len(valid),
        'max_out_of_plane_deg':max_plane,'basis':basis.tolist(),
        'mapping':'shoulder/elbow/wrist directions -> planar hinges; source scale discarded',
        'smoothing':'65 ms half-window mean of unwrapped angles; endpoints preserved',
        'raw_angles_rad':full.tolist(),'times_s':times.tolist(),
        'inference':'IMPORTED_UNVERIFIED' if provenance['kind']=='sam3d' else 'NOT_RUN_SYNTHETIC_TEST'})
