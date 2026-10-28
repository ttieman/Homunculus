"""Public workspace commands: shared schemas for manual controls and Muse tools."""
import math
import re


def obj(properties=None, required=()):
    return {'type':'object','properties':properties or {},'required':list(required),'additionalProperties':False}


def num(lo, hi): return {'type':'number','minimum':lo,'maximum':hi}
def enum(*values): return {'type':'string','enum':list(values)}
BOOL = {'type':'boolean'}
TEXT = {'type':'string','minLength':1,'maxLength':80}
COLOR = {'type':'string','pattern':'^#[0-9a-fA-F]{6}$'}
VEC = {'type':'array','items':num(-10,10),'minItems':3,'maxItems':3}
EDIT = obj({'duration':num(2,30),'shoulder_deg':num(5,100),'elbow_deg':num(-100,30),
            'strength':num(.1,2),'damping':num(.2,3),'obstacle':BOOL})
PROP = obj({'id':TEXT,'shape':enum('box','sphere'),'position':VEC,
            'scale':{'type':'array','items':num(.01,5),'minItems':3,'maxItems':3},'color':COLOR},
           ('id','shape','position','scale','color'))
SCENE = obj({'background':COLOR,'grid':BOOL,'light':num(0,5),'camera':enum('home','front','side','top'),
             'props':{'type':'array','items':PROP,'maxItems':20}})
SPECS = {
 'adjust_pose':('Rotate one spatial reference keyframe in joint-local space, then re-simulate. Shoulder supports x/y/z; elbow supports z only. Speed and joint constraints may reject the edit.',obj({'keyId':TEXT,'joint':enum('shoulder','elbow'),'axis':enum('x','y','z'),'degrees':num(-45,45)},('keyId','joint','axis','degrees'))),
 'inspect_workspace':('Read settings, scene, timeline keys, available attachments and result metrics.',obj()),
 'set_settings':('Change only specified motion controls, recording view or physics overlay. Simulates changed motion. Captured angles cannot be replaced.',obj({'edit':EDIT,'view':enum('auto','front','side'),'showPhysics':BOOL})),
 'set_scene':('Set visual stage background, grid, light, camera or replace visual props. Props do NOT collide; use edit.obstacle for the simulated obstacle.',SCENE),
 'playback':('Play/pause, seek in seconds, or switch between simulation and exported-clip replay.',obj({'playing':BOOL,'time':num(0,30),'replay':BOOL})),
 'simulate':('Re-run the current physical motion.',obj()),
 'optimize':('Run the bounded controller search for the current spatial capture.',obj()),
 'use_demo':('Replace captured motion with the procedural reach, preserving control settings.',obj()),
 'edit_timeline':('Edit a spatial capture timeline using existing key IDs. Only timing operations are supported.',obj({'commands':{'type':'array','minItems':1,'maxItems':50,'items':obj({'operation':enum('move_keyframe','set_duration','set_interpolation'),'targetId':TEXT,'parameters':obj({'time':num(0,30),'seconds':num(2,30),'interpolation':enum('linear','smoothstep','hold')})},('operation','parameters'))}},('commands',))),
 'assemble_three_poses':('Reduce the spatial capture reference to its first, middle and last keys.',obj()),
 'undo':('Undo the previous motion, view or scene change.',obj()),
 'redo':('Redo the last undone change.',obj()),
 'use_attachment':('Use an already attached video as local source preview, a validated capture JSON as motion, or a saved scene JSON. Images are visual references only. Cannot select arbitrary files or run SAM inference.',obj({'id':TEXT},('id',))),
 'export_asset':('Download the current arm glTF, character GLB, reference, session or reusable scene JSON to the user browser.',obj({'format':enum('arm','character','reference','session','scene')},('format',))),
}


def validate(value, schema, path='arguments'):
    kind=schema['type']
    if kind=='object':
        if not isinstance(value,dict): raise ValueError(f'{path} must be an object')
        if set(value)-set(schema['properties']): raise ValueError(f'{path}: unknown fields')
        if set(schema['required'])-set(value): raise ValueError(f'{path}: required fields missing')
        for k,v in value.items(): validate(v,schema['properties'][k],f'{path}.{k}')
    elif kind=='array':
        if not isinstance(value,list) or not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',100): raise ValueError(f'{path}: invalid array length')
        for i,v in enumerate(value): validate(v,schema['items'],f'{path}[{i}]')
    elif kind=='boolean':
        if type(value) is not bool: raise ValueError(f'{path} must be boolean')
    elif kind=='number':
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not schema['minimum']<=value<=schema['maximum']: raise ValueError(f'{path}: number outside supported range')
    elif kind=='string':
        if not isinstance(value,str) or not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',200): raise ValueError(f'{path}: invalid text')
        if 'enum' in schema and value not in schema['enum']: raise ValueError(f'{path}: unsupported value')
        if 'pattern' in schema and not re.fullmatch(schema['pattern'],value): raise ValueError(f'{path}: invalid format')


def validate_command(name, arguments):
    if not isinstance(name,str) or name not in SPECS: raise ValueError('Unknown workspace command')
    validate(arguments,SPECS[name][1])
    if name=='set_scene' and 'props' in arguments:
        ids=[p['id'] for p in arguments['props']]
        if len(ids)!=len(set(ids)): raise ValueError('Scene prop IDs must be unique')
    return arguments


def tools():
    return [{'type':'function','function':{'name':name,'description':desc,'parameters':schema}}
            for name,(desc,schema) in SPECS.items()]
