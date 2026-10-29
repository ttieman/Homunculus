import base64
import json
import struct
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

from homunculus.retarget import character
from homunculus.retarget.character import (
    Rig,
    export_character_glb,
    mapping,
    puppet_arm,
    read_glb,
    replay_character,
    retarget,
    to_character,
)
from character_fixture import build
from homunculus.physics.settings import Edit
from homunculus.physics.simulate import run
from homunculus.capture.spatial import prepare_spatial
from homunculus.physics.spatial import run_spatial
from test_spatial import bundle


@pytest.fixture(scope='module')
def rig():
    return Rig(build(), 'test-character.glb')


@pytest.fixture(scope='module')
def results():
    return {
        'planar': run(Edit()),
        'planar_straight': run(Edit(elbow_deg=0, obstacle=False)),
        'spatial': run_spatial(Edit(duration=3, obstacle=False), prepare_spatial(bundle())),
    }


def angle(a, b):
    return np.degrees(np.arccos(np.clip(np.dot(a, b) / np.linalg.norm(a) / np.linalg.norm(b), -1, 1)))


@pytest.mark.parametrize('view', ['front', 'side'])
@pytest.mark.parametrize('name', ['planar', 'planar_straight', 'spatial'])
@pytest.mark.parametrize('side', ['L', 'R'])
def test_exported_character_reproduces_arm_directions(rig, results, name, side, view):
    result = results[name]
    glb = export_character_glb(rig, retarget(result, rig, side, view))
    times, decoded = replay_character(glb)
    assert np.allclose(times, [f['t'] - result['frames'][0]['t'] for f in result['frames']], atol=1e-5)
    worst = 0
    for frame, (upper, fore) in zip(result['frames'], decoded):
        elbow, hand = puppet_arm(frame)
        worst = max(
            worst,
            angle(upper, to_character(elbow - [0, 1.4, 0], side, view)),
            angle(fore, to_character(hand - elbow, side, view)),
        )
    assert worst < 0.01


def test_front_view_keeps_camera_axes_and_is_the_spatial_default(rig, results):
    # Facing the camera: an arm held out to image-right is the character's left side.
    assert np.allclose(to_character([1, 0, 0], 'L', 'front'), [1, 0, 0])
    assert np.allclose(to_character([0, 0, 1], 'R', 'front'), [0, 0, 1])  # toward camera is forward
    assert retarget(results['spatial'], rig)['view'] == 'front'
    assert retarget(results['planar'], rig)['view'] == 'side'
    for side in 'LR':
        for view in ('front', 'side'):
            m = mapping(side, view)
            assert np.allclose(m @ m.T, np.eye(3))
            assert np.allclose(
                np.array(retarget(results['planar'], rig, side, view)['character_to_puppet']), m.T
            )
    with pytest.raises(ValueError, match='Unknown recording view'):
        mapping('L', 'overhead')


def test_mapping_puts_reach_in_front_and_on_captured_side():
    # Puppet +X reach is character forward; puppet +Z points away from the body on that side.
    assert np.allclose(to_character([1, 0, 0], 'R'), [0, 0, 1])
    assert np.allclose(to_character([0, 0, 1], 'R'), [-1, 0, 0])  # right arm lives on -X
    assert np.allclose(to_character([0, 0, 1], 'L'), [1, 0, 0])


def test_retarget_is_continuous_and_uses_the_elbow_hinge(rig, results):
    frames = retarget(results['spatial'], rig)['frames']
    upper = np.array([f['rotations_xyzw'][0] for f in frames])
    fore = np.array([f['rotations_xyzw'][1] for f in frames])
    assert np.all(np.sum(upper[1:] * upper[:-1], axis=1) > 0)  # same hemisphere for LINEAR sampling
    assert np.allclose(fore[:, 1:3], 0)  # pure rotation about the bone's local X (the rig's hinge)


def test_export_keeps_mesh_and_skin_and_drops_source_clips(rig, results):
    glb = export_character_glb(rig, retarget(results['planar'], rig), {'note': 'x'})
    doc, binary = read_glb(glb)
    src, src_bin = rig.document, rig.binary
    assert [a['name'] for a in doc['animations']] == ['Homunculus_Reach']
    assert doc['nodes'] == src['nodes'] and doc['skins'][0]['joints'] == src['skins'][0]['joints']

    def floats(d, b, index):
        acc = d['accessors'][index]
        view = d['bufferViews'][acc['bufferView']]
        return b[view.get('byteOffset', 0) : view.get('byteOffset', 0) + view['byteLength']]

    prim, src_prim = doc['meshes'][0]['primitives'][0], src['meshes'][0]['primitives'][0]
    assert floats(doc, binary, prim['attributes']['POSITION']) == floats(
        src, src_bin, src_prim['attributes']['POSITION']
    )
    assert (
        len(doc['accessors']) == len(src['accessors']) - 2 + 3
    )  # source clip accessors gone, time + 2 tracks added
    assert doc['extras']['homunculus']['side'] == 'R'


def test_rejects_unsupported_characters():
    with pytest.raises(ValueError, match='glTF 2.0 binary'):
        Rig(b'{"asset":{}}')
    with pytest.raises(ValueError, match='missing bone forearm.L'):
        Rig(build(drop_bone='forearm.L'))
    glb = bytearray(build())
    glb[8:12] = struct.pack('<I', len(glb) + 4)
    with pytest.raises(ValueError, match='length header'):
        Rig(bytes(glb))


def test_configured_path_reads_env_local(tmp_path, monkeypatch):
    monkeypatch.delenv('HOMUNCULUS_CHARACTER', raising=False)
    assert character.configured_path(tmp_path) is None
    (tmp_path / '.env.local').write_text('MODEL_API_KEY=x\nHOMUNCULUS_CHARACTER="C:/game/stickman.glb"\n')
    assert character.configured_path(tmp_path) == 'C:/game/stickman.glb'
    monkeypatch.setenv('HOMUNCULUS_CHARACTER', '/env/wins.glb')
    assert character.configured_path(tmp_path) == '/env/wins.glb'


def test_server_serves_character_and_retargets_simulations(rig):
    from homunculus.editor.server import Handler

    Handler.rig = rig
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        status = json.load(urllib.request.urlopen(base + '/api/status'))
        assert status['character']['source'] == 'test-character.glb'
        assert urllib.request.urlopen(base + '/character.glb').read() == rig.blob
        request = urllib.request.Request(
            base + '/api/simulate',
            data=json.dumps({'edit': {'duration': 2, 'obstacle': False}}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        payload = json.load(urllib.request.urlopen(request))
        assert payload['result']['retarget']['bones'] == ['upper_arm.R', 'forearm.R']
        replay_character(base64.b64decode(payload['character_glb']))
        request = urllib.request.Request(
            base + '/api/simulate',
            data=json.dumps({'edit': {'duration': 2}, 'view': 'front'}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        assert json.load(urllib.request.urlopen(request))['result']['retarget']['view'] == 'front'
        request = urllib.request.Request(
            base + '/api/simulate',
            data=json.dumps({'edit': {'duration': 2}, 'view': 'top'}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 400
    finally:
        Handler.rig = None
        server.shutdown()
        server.server_close()
        worker.join()
