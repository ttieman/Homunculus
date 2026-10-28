"""Offline, reproducible spatial synthesis and independently checked glTF export."""
import argparse
import json
from pathlib import Path
import numpy as np
from spatial import prepare_spatial, synthesize
from puppet import Edit
from exporter import export_gltf, replay_gltf


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture',type=Path); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--duration',type=float); p.add_argument('--obstacle',action='store_true')
    args=p.parse_args()
    if args.output.exists(): p.error('Choose a new output directory')
    bundle=json.loads(args.capture.read_text(encoding='utf-8')); bundle['retargeting']='spatial_arm_v1'
    motion=prepare_spatial(bundle)
    edit=Edit.parse({'duration':args.duration or float(motion.times[-1]),'obstacle':args.obstacle})
    result,report=synthesize(motion,edit); gltf=export_gltf(result)
    error=float(np.max(np.abs(np.asarray(replay_gltf(gltf))-np.array([f['hand'] for f in result['frames']]))))
    if error>1e-6: raise RuntimeError('Export transform verification failed')
    report.update(export_max_component_error_m=error,capture=motion.metadata)
    args.output.mkdir(parents=True)
    for name,value in [('capture.json',bundle),('animation.gltf',gltf),('simulation.json',result),('synthesis-report.json',report),
                       ('reference-animation.json',motion.timeline.document),('motion-profile.json',{'schema':'homunculus.motion-profile.v1','skeletonId':'homunculus.supported-arm.v1','reference':'reference-animation.json','trajectory':'simulation.json','export':'animation.gltf','controller':{'type':'PD+bias','version':1,'parameters':result['edit'],'torque_limits_Nm':[35,35,35,20]},'physics':{'root':'fixed','lengths_m':[.34,.29],'masses_kg':[1.4,.9],'timestep_s':.002,'gravity':[0,-9.81,0],'engine':'MuJoCo '+result['metrics']['mujoco']},'validation':{'export_verified':True,'full_body':False,'generalization':'not tested'},'optimization':report})]:
        (args.output/name).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'output':str(args.output),'selected':report['selected'],'metrics':result['metrics'],'export_error_m':error},indent=2))


if __name__=='__main__': main()
