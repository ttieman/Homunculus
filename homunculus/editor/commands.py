"""Public workspace commands: shared schemas for manual controls and Muse tools."""

import math
import re
from homunculus.retarget.body import BODY_BONES


def obj(properties=None, required=()):
    return {
        'type': 'object',
        'properties': properties or {},
        'required': list(required),
        'additionalProperties': False,
    }


def num(lo, hi):
    return {'type': 'number', 'minimum': lo, 'maximum': hi}


def enum(*values):
    return {'type': 'string', 'enum': list(values)}


BOOL = {'type': 'boolean'}
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 80}
COLOR = {'type': 'string', 'pattern': '^#[0-9a-fA-F]{6}$'}
VEC = {'type': 'array', 'items': num(-10, 10), 'minItems': 3, 'maxItems': 3}
EDIT = obj(
    {
        'duration': num(2, 30),
        'shoulder_deg': num(5, 100),
        'elbow_deg': num(-100, 30),
        'strength': num(0.1, 2),
        'damping': num(0.2, 3),
        'obstacle': BOOL,
    }
)
PROP = obj(
    {
        'id': TEXT,
        'shape': enum('box', 'sphere'),
        'position': VEC,
        'scale': {'type': 'array', 'items': num(0.01, 5), 'minItems': 3, 'maxItems': 3},
        'color': COLOR,
    },
    ('id', 'shape', 'position', 'scale', 'color'),
)
SCENE = obj(
    {
        'background': COLOR,
        'grid': BOOL,
        'light': num(0, 5),
        'camera': enum('home', 'front', 'side', 'top'),
        'props': {'type': 'array', 'items': PROP, 'maxItems': 20},
    }
)
CURVE = enum(
    'step',
    'linear',
    'smoothstep',
    'smootherstep',
    'ease_in',
    'ease_out',
    'ease_in_out',
    'expo_in',
    'expo_out',
)  # segments.CURVES
SPECS = {
    'navigate_stage': (
        'Open the Capture, Import, Review, Edit or Export workspace. Muse remains available in every stage.',
        obj({'stage': enum('capture', 'import', 'review', 'edit', 'export')}, ('stage',)),
    ),
    'list_library': (
        'List saved assets in the local library (captures, recordings, animations, projects, scenes, character) with id, title, kind and dates.',
        obj(),
    ),
    'open_library_asset': (
        'Open a library asset by id from list_library: a capture or project replaces the current animation, a scene replaces the stage, an animation GLB previews in the viewport, an unconverted recording is made ready to convert. Undo restores the previous animation. Muse cannot rename or delete assets.',
        obj({'id': {'type': 'string', 'minLength': 1, 'maxLength': 400}}, ('id',)),
    ),
    'save_to_library': (
        'Save the current character GLB, animation project or preview scene into the local library. Refused while edits are unapplied.',
        obj({'format': enum('character', 'project', 'scene')}, ('format',)),
    ),
    'compose_motion': (
        'Mask exports only selected local joint tracks. Layer replaces selected joints from an attached full-body capture, fitted to base duration, preserving other base tracks. Sequence joins the selected joints with a transition; other joints hold the end of the base after it ends. rootMotion selects pelvis translation separately. Parent movement still carries child joints. Undo restores the previous composition. No world-space pinning.',
        obj(
            {
                'mode': enum('mask', 'layer', 'sequence'),
                'bones': {'type': 'array', 'items': enum(*BODY_BONES), 'maxItems': 19},
                'rootMotion': BOOL,
                'blend': num(0, 5),
                'sourceId': TEXT,
            },
            ('mode', 'bones', 'rootMotion'),
        ),
    ),
    'clear_composition': ('Restore the complete base animation without a mask or second clip.', obj()),
    'adjust_pose': (
        'Rotate one spatial reference keyframe in joint-local space, then re-simulate. Shoulder supports x/y/z; elbow supports z only. Speed and joint constraints may reject the edit.',
        obj(
            {
                'keyId': TEXT,
                'joint': enum('shoulder', 'elbow'),
                'axis': enum('x', 'y', 'z'),
                'degrees': num(-45, 45),
            },
            ('keyId', 'joint', 'axis', 'degrees'),
        ),
    ),
    'inspect_workspace': (
        'Read settings, scene, timeline keys, available attachments and result metrics.',
        obj(),
    ),
    'set_settings': (
        'Change only specified motion controls, recording view or physics overlay. Simulates changed motion. Captured angles cannot be replaced.',
        obj(
            {
                'edit': EDIT,
                'view': enum('auto', 'front', 'side'),
                'showPhysics': BOOL,
                'rotation': obj(
                    {'pitch': num(-180, 180), 'yaw': num(-180, 180), 'roll': num(-180, 180)},
                    ('pitch', 'yaw', 'roll'),
                ),
            }
        ),
    ),
    'set_animation_rotation': (
        'Set absolute whole-character rotation in degrees: pitch around X, yaw around Y, roll around Z, in that order. Unspecified axes keep their values. Pivot at starting hips; applies after composition, is undoable, saved with the project/reference and baked into character GLB. Does not change source video or physics overlay. Set all axes to zero to reset.',
        obj({'pitch': num(-180, 180), 'yaw': num(-180, 180), 'roll': num(-180, 180)}),
    ),
    'set_scene': (
        'Set visual stage background, grid, light, camera or replace visual props. Props do NOT collide; use edit.obstacle for the simulated obstacle.',
        SCENE,
    ),
    'playback': (
        'Play/pause, seek in seconds, or switch between simulation and exported-clip replay.',
        obj({'playing': BOOL, 'time': num(0, 60), 'replay': BOOL}),
    ),
    'simulate': ('Re-run the current physical motion.', obj()),
    'optimize': ('Run the bounded controller search for the current spatial capture.', obj()),
    'use_demo': ('Replace captured motion with the procedural reach, preserving control settings.', obj()),
    'edit_timeline': (
        'Edit a spatial capture timeline using existing key IDs. Only timing operations are supported.',
        obj(
            {
                'commands': {
                    'type': 'array',
                    'minItems': 1,
                    'maxItems': 50,
                    'items': obj(
                        {
                            'operation': enum('move_keyframe', 'set_duration', 'set_interpolation'),
                            'targetId': TEXT,
                            'parameters': obj(
                                {
                                    'time': num(0, 30),
                                    'seconds': num(2, 30),
                                    'interpolation': enum('linear', 'smoothstep', 'hold'),
                                }
                            ),
                        },
                        ('operation', 'parameters'),
                    ),
                }
            },
            ('commands',),
        ),
    ),
    'set_segment': (
        'Create or replace (by id) a range of the spatial capture, in source-clip seconds (the "Matched source" time), that overrides physics strength (.1-2) and/or damping (.2-3), easing in and out over blend seconds along curve. Re-simulates. Physics drives the supported arm; it shows on the character only with physics arm driving enabled.',
        obj(
            {
                'id': TEXT,
                'start': num(0, 30),
                'end': num(0, 30),
                'strength': num(0.1, 2),
                'damping': num(0.2, 3),
                'blend': num(0, 15),
                'curve': CURVE,
            },
            ('id', 'start', 'end'),
        ),
    ),
    'clear_segments': (
        'Remove the listed segment ids, or every segment when ids is omitted. Re-simulates.',
        obj({'ids': {'type': 'array', 'items': TEXT, 'minItems': 1, 'maxItems': 64}}),
    ),
    'assemble_three_poses': (
        'Reduce the spatial capture reference to its first, middle and last keys.',
        obj(),
    ),
    'undo': ('Undo the previous motion, view or scene change.', obj()),
    'redo': ('Redo the last undone change.', obj()),
    'use_attachment': (
        'Use an already attached video as local source preview, a validated capture JSON as motion, or a saved scene JSON. Images are visual references only. Cannot select arbitrary files or run SAM inference.',
        obj({'id': TEXT}, ('id',)),
    ),
    'export_asset': (
        'Download the current arm glTF, character GLB, reference, session or reusable scene JSON to the user browser.',
        obj({'format': enum('arm', 'character', 'reference', 'session', 'scene', 'project')}, ('format',)),
    ),
}


def validate(value, schema, path='arguments'):
    kind = schema['type']
    if kind == 'object':
        if not isinstance(value, dict):
            raise ValueError(f'{path} must be an object')
        if set(value) - set(schema['properties']):
            raise ValueError(f'{path}: unknown fields')
        if set(schema['required']) - set(value):
            raise ValueError(f'{path}: required fields missing')
        for k, v in value.items():
            validate(v, schema['properties'][k], f'{path}.{k}')
    elif kind == 'array':
        if not isinstance(value, list) or not schema.get('minItems', 0) <= len(value) <= schema.get(
            'maxItems', 100
        ):
            raise ValueError(f'{path}: invalid array length')
        for i, v in enumerate(value):
            validate(v, schema['items'], f'{path}[{i}]')
    elif kind == 'boolean':
        if type(value) is not bool:
            raise ValueError(f'{path} must be boolean')
    elif kind == 'number':
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not schema['minimum'] <= value <= schema['maximum']
        ):
            raise ValueError(f'{path}: number outside supported range')
    elif kind == 'string':
        if not isinstance(value, str) or not schema.get('minLength', 0) <= len(value) <= schema.get(
            'maxLength', 200
        ):
            raise ValueError(f'{path}: invalid text')
        if 'enum' in schema and value not in schema['enum']:
            raise ValueError(f'{path}: unsupported value')
        if 'pattern' in schema and not re.fullmatch(schema['pattern'], value):
            raise ValueError(f'{path}: invalid format')


def validate_command(name, arguments):
    if not isinstance(name, str) or name not in SPECS:
        raise ValueError('Unknown workspace command')
    validate(arguments, SPECS[name][1])
    if name == 'set_scene' and 'props' in arguments:
        ids = [p['id'] for p in arguments['props']]
        if len(ids) != len(set(ids)):
            raise ValueError('Scene prop IDs must be unique')
    return arguments


def tools():
    return [
        {'type': 'function', 'function': {'name': name, 'description': desc, 'parameters': schema}}
        for name, (desc, schema) in SPECS.items()
    ]
