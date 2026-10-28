"""Versioned, checksummed physical motion assets and deterministic replay."""
import hashlib
import json
from pathlib import Path
import numpy as np
from exporter import export_gltf, replay_gltf
from puppet import Edit
from spatial import prepare_spatial, run_spatial


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save_asset(directory, capture, motion, result, optimization):
    directory=Path(directory)
    if directory.exists(): raise ValueError('Choose a new output directory')
    gltf=export_gltf(result)
    error=float(np.max(np.abs(np.asarray(replay_gltf(gltf))-[f['hand'] for f in result['frames']])))
    if error>1e-6: raise ValueError('Export validation failed')
    files={'capture.json':capture,'reference-animation.json':motion.timeline.document,
           'simulation.json':result,'animation.gltf':gltf,'physics.json':result['physics_configuration'],
           'synthesis-report.json':dict(optimization,export_max_component_error_m=error)}
    encoded={name:json.dumps(value,indent=2,allow_nan=False).encode() for name,value in files.items()}
    profile={'schema':'homunculus.motion-profile.v2','skeletonId':'homunculus.supported-arm.v1',
             'files':{name:digest(data) for name,data in encoded.items()},
             'controller':{'type':'PD+bias','version':1,'parameters':result['edit']},
             'physics_sha256':result['physics_sha256'],
             'validation':{'export_max_component_error_m':error,'physical_feasibility':result['feasibility'],
                           'generalization':'not tested','capture_accuracy':'not measured'}}
    directory.mkdir(parents=True)
    for name,data in encoded.items(): (directory/name).write_bytes(data)
    (directory/'motion-profile.json').write_text(json.dumps(profile,indent=2),encoding='utf-8')
    return profile


def replay_asset(directory):
    directory=Path(directory)
    profile=json.loads((directory/'motion-profile.json').read_text(encoding='utf-8'))
    if profile.get('schema')!='homunculus.motion-profile.v2': raise ValueError('Unsupported motion profile')
    expected={'capture.json','reference-animation.json','simulation.json','animation.gltf','physics.json','synthesis-report.json'}
    if set(profile.get('files',{}))!=expected: raise ValueError('Invalid asset file manifest')
    data={}
    for name,sha in profile['files'].items():
        raw=(directory/name).read_bytes()
        if digest(raw)!=sha: raise ValueError(f'Asset hash mismatch: {name}')
        data[name]=json.loads(raw)
    capture=data['capture.json'];capture['reference_animation']=data['reference-animation.json']
    result=run_spatial(Edit.parse(profile['controller']['parameters']),prepare_spatial(capture),physics=data['physics.json'])
    if result['physics_sha256']!=profile['physics_sha256']: raise ValueError('Physics configuration mismatch')
    old=data['simulation.json']['frames'];new=result['frames']
    if len(old)!=len(new): raise ValueError('Replay frame count mismatch')
    position_error=float(np.max(np.abs(np.array([f['hand'] for f in old])-np.array([f['hand'] for f in new]))))
    torque_error=float(np.max(np.abs(np.array([f['torque_Nm'] for f in old])-np.array([f['torque_Nm'] for f in new]))))
    return {'position_error_m':position_error,'torque_error_Nm':torque_error,
            'passed':position_error<=1e-8 and torque_error<=1e-8,'frames':len(new)}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    args=parser.parse_args(); report=replay_asset(args.directory)
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['passed'] else 1)
