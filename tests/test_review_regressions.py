import copy
import json
import threading
import urllib.request
import urllib.error
import numpy as np
import pytest
from http.server import ThreadingHTTPServer
from homunculus.contracts import SampleGrid, MAX_DOCUMENT_BYTES, MAX_FRAMES
from test_spatial import bundle
from homunculus.capture.spatial import prepare_spatial
from homunculus.physics.spatial import synthesize, run_spatial
from homunculus.physics.settings import Edit
from homunculus.editor.server import Handler
from homunculus.export.gltf import export_gltf, replay_gltf


def test_optimizer_includes_off_grid_current_configuration():
    result, report = synthesize(
        prepare_spatial(bundle()), Edit(duration=3, strength=2, damping=0.2, obstacle=False)
    )
    assert report['candidates'][0]['edit']['strength'] == 2
    assert report['selected_score'] <= report['current_score']


def test_edited_speed_and_hold_discontinuity_are_rejected():
    b = bundle()
    m = prepare_spatial(b)
    b['reference_animation'] = m.timeline.document
    b['reference_animation']['keyframes'][1]['time'] = 0.000001
    with pytest.raises(ValueError, match='Edited reference'):
        prepare_spatial(b)
    b['reference_animation'] = prepare_spatial(bundle()).timeline.document
    b['reference_animation']['keyframes'][0]['interpolation'] = 'hold'
    with pytest.raises(ValueError, match='Hold boundary'):
        prepare_spatial(b)


def test_duration_scaling_is_checked_before_simulation():
    m = prepare_spatial(bundle())
    with pytest.raises(ValueError, match='Edited reference'):
        m.timeline.validate_motion(0.001)


def test_hinge_quaternion_sign_does_not_change_target():
    b = bundle()
    original = prepare_spatial(b)
    b['reference_animation'] = copy.deepcopy(original.timeline.document)
    for pose in b['reference_animation']['poses'].values():
        pose['rotations_wxyz'][1] = (-np.array(pose['rotations_wxyz'][1])).tolist()
    changed = prepare_spatial(b)
    for t in np.linspace(0, 3, 51):
        assert np.allclose(original.target(t, 3), changed.target(t, 3))


@pytest.mark.parametrize('hz', [5, 15, 30])
def test_grid_does_not_accumulate_decoder_rounding(hz):
    grid = SampleGrid(0, hz)
    selected = [t for t in np.round(np.arange(1801) / 60, 3) if grid.take(t)]
    assert len(selected) == 30 * hz + 1
    assert len(selected) <= MAX_FRAMES
    assert np.max(np.abs(np.array(selected) - np.arange(len(selected)) / hz)) < 0.00051


def test_maximum_reference_fits_shared_transport_contract():
    b = bundle()
    pose = b['frames'][0]['arm']
    b['frames'] = [{'t': float(t), 'arm': pose} for t in np.linspace(0, 30, MAX_FRAMES)]
    b['reference_animation'] = prepare_spatial(b).timeline.document
    encoded = json.dumps(b, indent=2).encode()
    assert len(encoded) < MAX_DOCUMENT_BYTES
    assert len(prepare_spatial(json.loads(encoded)).timeline.times) == MAX_FRAMES


@pytest.fixture
def local_api():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def post(route, body):
        req = urllib.request.Request(
            f'http://127.0.0.1:{server.server_port}' + route,
            data=json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'},
        )
        return json.load(urllib.request.urlopen(req, timeout=10))

    yield post
    server.shutdown()
    server.server_close()
    worker.join()


def test_malformed_request_returns_400_and_server_recovers(local_api):
    for payload in (
        None,
        [],
        {'capture': dict(bundle(), provenance=None)},
        {'capture': dict(bundle(), frames=[None, None, None])},
    ):
        with pytest.raises(urllib.error.HTTPError) as exc:
            local_api('/api/capture/validate', payload)
        assert exc.value.code == 400
        assert 'error' in json.load(exc.value)
    assert local_api('/api/capture/validate', {'capture': bundle()})['metadata']


def test_saved_reference_preserves_authoring_duration(local_api):
    response = local_api('/api/reference', {'capture': bundle(), 'duration': 6})
    saved = json.loads(json.dumps(response['capture']))
    assert prepare_spatial(saved).times[-1] == 6
    assert np.allclose(prepare_spatial(saved).target(3, 6), prepare_spatial(bundle()).target(1.5, 3))


def test_export_detects_corrupt_times_channels_and_counts():
    r = run_spatial(Edit(duration=3, obstacle=False), prepare_spatial(bundle()))
    g = export_gltf(r)
    for fault in ('time', 'channel', 'length'):
        broken = copy.deepcopy(g)
        if fault == 'time':
            broken['accessors'][broken['animations'][0]['samplers'][0]['input']]['count'] = 0
        if fault == 'channel':
            broken['animations'][0]['channels'][0]['target']['node'] = 5
        if fault == 'length':
            broken['accessors'][broken['animations'][0]['samplers'][0]['output']]['count'] -= 1
        with pytest.raises(ValueError):
            replay_gltf(broken)
    # Non-grid times and endpoint clamping are evaluated from timestamps.
    positions = np.array(replay_gltf(g, [0, 0.011, 2.999, 3, 4]))
    assert np.allclose(positions[-1], positions[-2])
    assert np.isfinite(positions).all()
