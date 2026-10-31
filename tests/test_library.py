import json

import pytest

from homunculus.editor.library import Library, pose_lines


@pytest.fixture
def capture():
    with open('outputs/test-body-capture.json', encoding='utf-8') as handle:
        return json.load(handle)


@pytest.fixture
def library(tmp_path):
    return Library(tmp_path / 'store')


def scene(color='#112233'):
    return json.dumps(
        {'schema': 'homunculus.scene.v1', 'scene': {'background': color}, 'settings': {}}
    ).encode()


def test_empty_library_lists_nothing(library):
    assert library.list() == {'items': [], 'last_opened': None}


def test_import_files_by_type_into_categories(library, capture):
    blob = json.dumps(capture).encode()
    project = json.dumps(
        {'schema': 'homunculus.project.v1', 'edit': {'duration': 5}, 'capture': capture}
    ).encode()
    added = [('a.json', blob), ('b.mkv', b'video'), ('c.json', project), ('d.json', scene())]
    assert {library.add(n, b)['kind'] for n, b in added} == {'capture', 'recording', 'project', 'scene'}


def test_capture_row_has_duration_pose_and_dates(library, capture):
    item = library.add('take one.json', json.dumps(capture).encode())
    assert item['title'].endswith('take_one') and item['meta']['body'] == 'full body'
    assert item['meta']['duration'] > 0 and item['created'] <= item['modified']
    assert all(0 <= v <= 1 for line in item['meta']['pose'] for point in line for v in point)


def test_pose_thumbnail_keeps_the_head_above_the_feet(capture):
    lines = pose_lines(capture)
    assert lines[0][0][1] < lines[2][-1][1]


def test_rejects_invalid_imports_and_stores_nothing(library):
    for name, blob in [
        ('x.exe', b'1'),
        ('x.glb', b'nope'),
        ('x.json', b'{"frames": []}'),
        ('x.json', b'[1]'),
    ]:
        with pytest.raises((ValueError, KeyError, TypeError)):
            library.add(name, blob)
    assert library.list()['items'] == []


def test_same_name_never_overwrites(library):
    first, second = library.add('s.json', scene('#111111')), library.add('s.json', scene('#222222'))
    assert first['id'] != second['id']
    assert library.path(first['id']).read_bytes() == scene('#111111')


def test_rename_changes_title_and_modified_but_not_the_file(library):
    item = library.add('s.json', scene())
    renamed = library.rename(item['id'], '  Night stage ')
    assert renamed['title'] == 'Night stage' and renamed['file'] == item['file']
    assert renamed['modified'] >= item['modified'] and renamed['created'] == item['created']
    assert library.path(item['id']).is_file()
    with pytest.raises(ValueError):
        library.rename(item['id'], ' ')


def test_paired_clip_links_and_delete_leaves_the_other_file(library, capture):
    first = library.add('a.json', json.dumps(capture).encode())
    folder = library.path(first['id']).parent
    (folder / 'a.mp4').write_bytes(b'video')
    row = library.item(first['id'])
    assert row['video_id'].endswith('a.mp4')
    assert library.item(row['video_id'])['capture_id'] == row['id']
    library.delete(row['id'])
    assert (folder / 'a.mp4').is_file()
    library.delete(row['video_id'])
    assert not folder.exists() and library.clips.is_dir()


@pytest.mark.parametrize(
    'bad',
    [
        '../secret.json',
        'clips/../../secret.json',
        'projects/../../secret.json',
        'clips/a/notes.txt',
        'library.json',
        None,
        7,
    ],
)
def test_ids_cannot_escape_or_reach_other_files(library, bad):
    library.root.mkdir()
    (library.root.parent / 'secret.json').write_text('{}')
    (library.root / 'library.json').write_text('{}')
    with pytest.raises(ValueError):
        library.path(bad)
    with pytest.raises(ValueError):
        library.delete(bad)
    assert (library.root.parent / 'secret.json').exists()


def test_last_opened_survives_until_the_asset_is_deleted(library, capture):
    item = library.add('a.json', json.dumps(capture).encode())
    library.mark_opened(item['id'])
    assert library.list()['last_opened'] == item['id']
    assert library.last_opened_clip() == library.path(item['id']).parent
    library.delete(item['id'])
    assert library.list()['last_opened'] is None and library.last_opened_clip() is None


def test_corrupt_file_is_listed_as_broken_not_fatal(library):
    item = library.add('s.json', scene())
    library.path(item['id']).write_text('not json')
    assert library.list()['items'][0]['broken']
