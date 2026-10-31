// Import/Library panel: browse, search and act on everything in local storage.
// Opening goes through the shared workspace command; rename and delete are manual only.
const CATEGORIES = [
  ['all', 'All assets'],
  ['capture', 'Captures'],
  ['recording', 'Recordings'],
  ['animation', 'Animations'],
  ['project', 'Projects'],
  ['scene', 'Scenes'],
  ['character', 'Characters'],
];
const KIND_LABEL = {
  capture: 'Capture',
  recording: 'Recording',
  animation: 'Animation',
  project: 'Project',
  scene: 'Scene',
  character: 'Character',
};
const ICONS = {
  capture: 'M12 3a2 2 0 110 4 2 2 0 010-4zM6 10l6-1 6 1M12 9v6M12 15l-4 6M12 15l4 6',
  recording: 'M3 8a2 2 0 012-2h9a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2zM16 10l5-3v10l-5-3',
  animation: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5',
  project: 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z',
  scene: 'M3 18l6-8 4 5 3-3 5 6zM16 8a2 2 0 100-4 2 2 0 000 4z',
  character: 'M12 3a4 4 0 110 8 4 4 0 010-8zM4 21c0-4.4 3.6-7 8-7s8 2.6 8 7',
  open: 'M8 5l11 7-11 7z',
  rename: 'M4 20h4L19 9l-4-4L4 16v4zM13 7l4 4',
  export: 'M12 4v11M7 10l5 5 5-5M4 20h16',
  delete: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5',
};
const SORTS = {
  modified: (a, b) => (b.modified ?? 0) - (a.modified ?? 0),
  created: (a, b) => (b.created ?? 0) - (a.created ?? 0),
  name: (a, b) => a.title.localeCompare(b.title),
  size: (a, b) => b.size - a.size,
};
const WEEK_SECONDS = 7 * 24 * 3600;
const FILTERS = {
  any: () => true,
  'full-body': item => item.meta.body === 'full body',
  'arm-only': item => item.meta.body === 'arm only',
  'has-source': item => !!item.video_id,
  unconverted: item => item.kind === 'recording' && !item.capture_id,
  recent: item => (item.modified ?? 0) > Date.now() / 1000 - WEEK_SECONDS,
};

const SVG = 'http://www.w3.org/2000/svg';
function icon(name) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(SVG, 'path');
  path.setAttribute('d', ICONS[name]);
  svg.append(path);
  return svg;
}
function poseThumb(lines) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 1 1');
  svg.setAttribute('aria-hidden', 'true');
  svg.classList.add('asset-pose');
  for (const line of lines) {
    const part = document.createElementNS(SVG, 'polyline');
    part.setAttribute('points', line.map(p => p.join(',')).join(' '));
    svg.append(part);
  }
  return svg;
}
const fileUrl = (id, download) =>
  '/library/file?id=' + encodeURIComponent(id) + (download ? '&download=1' : '');
const formatDate = seconds =>
  new Date(seconds * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
const formatSize = bytes =>
  bytes < 1048576 ? Math.max(1, Math.round(bytes / 1024)) + ' KB' : (bytes / 1048576).toFixed(1) + ' MB';

export function createLibrary({ open, showExport }) {
  const $ = id => document.getElementById(id);
  let items = [],
    lastOpened = null,
    category = 'all',
    selected = null,
    renaming = null,
    pendingDelete = null;
  const say = text => ($('library-status').textContent = text);

  function button(label, name, action, disabledReason) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'asset-action' + (name === 'delete' ? ' danger' : '');
    b.title = disabledReason || label;
    b.setAttribute('aria-label', label);
    b.disabled = !!disabledReason;
    b.append(icon(name));
    b.onclick = action;
    return b;
  }

  function thumb(item) {
    const box = document.createElement('span');
    box.className = 'asset-thumb';
    if (item.meta.pose) box.append(poseThumb(item.meta.pose));
    else if (item.kind === 'recording') {
      const video = document.createElement('video');
      video.muted = true;
      video.preload = 'metadata';
      video.src = fileUrl(item.id);
      video.onerror = () => video.replaceWith(icon('recording')); // e.g. .mkv, which browsers cannot decode
      box.append(video);
    } else {
      if (item.kind === 'scene' && item.meta.background) box.style.background = item.meta.background;
      box.append(icon(item.kind));
    }
    return box;
  }

  function metaLine(item) {
    const parts = [KIND_LABEL[item.kind]];
    if (item.meta.duration) parts.push(item.meta.duration.toFixed(2) + ' s');
    if (item.meta.body) parts.push(item.meta.body);
    if (item.kind === 'recording') parts.push(item.capture_id ? 'converted' : 'not converted');
    parts.push(formatSize(item.size));
    return parts.join(' · ');
  }

  function renameForm(item) {
    const form = document.createElement('form');
    form.className = 'asset-rename';
    const input = document.createElement('input');
    input.value = item.title;
    input.maxLength = 80;
    input.setAttribute('aria-label', 'New name for ' + item.title);
    const save = document.createElement('button');
    save.textContent = 'Save';
    form.append(input, save);
    form.onsubmit = async e => {
      e.preventDefault();
      try {
        await post('/api/library/rename', { id: item.id, title: input.value });
        renaming = null;
        await refresh();
        say('Renamed to ' + input.value.trim() + '.');
      } catch (error) {
        say(error.message);
      }
    };
    input.onkeydown = e => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        renaming = null;
        render();
      }
    };
    queueMicrotask(() => input.select());
    return form;
  }

  function actions(item) {
    const row = document.createElement('div');
    row.className = 'asset-actions';
    const locked = item.read_only ? 'The active character is set when the editor starts' : '';
    row.append(
      button(
        'Open ' + item.title,
        'open',
        () => openItem(item),
        locked || (item.broken ? 'This file could not be read' : ''),
      ),
      button(
        'Rename ' + item.title,
        'rename',
        () => {
          renaming = item.id;
          render();
        },
        locked,
      ),
      button('Export ' + item.title, 'export', () => exportItem(item)),
      button('Delete ' + item.title, 'delete', () => askDelete(item), locked),
    );
    return row;
  }

  function card(item) {
    const article = document.createElement('article');
    article.className = 'asset' + (item.id === selected ? ' selected' : '');
    article.dataset.id = item.id;
    article.dataset.kind = item.kind;
    const main = document.createElement('button');
    main.type = 'button';
    main.className = 'asset-main';
    main.setAttribute('aria-pressed', String(item.id === selected));
    const title = document.createElement('strong');
    title.textContent = item.title;
    title.title = item.file;
    const meta = document.createElement('small');
    meta.textContent = item.broken ? 'Could not be read' : metaLine(item);
    main.append(thumb(item), title, meta);
    if (item.created) {
      const dates = document.createElement('small');
      dates.textContent = 'Modified ' + formatDate(item.modified) + ' · Created ' + formatDate(item.created);
      main.append(dates);
    }
    if (item.id === lastOpened) {
      const badge = document.createElement('span');
      badge.className = 'asset-badge';
      badge.textContent = 'Last opened';
      main.append(badge);
    }
    main.onclick = () => {
      selected = selected === item.id ? null : item.id;
      renaming = null;
      render();
      document.querySelector(`.asset[data-id="${CSS.escape(item.id)}"] .asset-main`)?.focus();
    };
    main.ondblclick = () => !item.read_only && !item.broken && openItem(item);
    article.append(main);
    if (item.id === selected) article.append(renaming === item.id ? renameForm(item) : actions(item));
    return article;
  }

  function visible() {
    const query = $('library-search').value.trim().toLowerCase();
    return items
      .filter(item => category === 'all' || item.kind === category)
      .filter(FILTERS[$('library-filter').value])
      .filter(item => !query || (item.title + ' ' + item.file).toLowerCase().includes(query))
      .sort(SORTS[$('library-sort').value]);
  }

  function renderCategories() {
    $('library-categories').replaceChildren(
      ...CATEGORIES.map(([key, label]) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.setAttribute('aria-pressed', String(key === category));
        const count = key === 'all' ? items.length : items.filter(item => item.kind === key).length;
        const name = document.createElement('span');
        name.textContent = label;
        const number = document.createElement('small');
        number.textContent = count;
        b.append(name, number);
        b.onclick = () => {
          category = key;
          showBrowse();
          render();
        };
        return b;
      }),
    );
  }

  function render() {
    renderCategories();
    const shown = visible();
    $('library-grid').replaceChildren(...shown.map(card));
    $('library-empty').hidden = shown.length > 0 && items.some(item => !item.read_only);
    $('library-empty').textContent = items.some(item => !item.read_only)
      ? 'Nothing matches this search and filter.'
      : 'Your library is empty. Import a video or file to get started.';
  }

  async function post(path, data) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const reply = await r.json();
    if (!r.ok) throw Error(reply.error || 'Request failed');
    return reply;
  }

  async function refresh() {
    try {
      const r = await fetch('/api/library');
      const listing = await r.json();
      if (!r.ok) throw Error(listing.error || 'Could not read the library');
      items = listing.items;
      lastOpened = listing.last_opened;
      if (!items.some(item => item.id === selected)) selected = null;
      render();
    } catch (e) {
      say(e.message);
    }
  }

  async function openItem(item) {
    say('Opening ' + item.title + '…');
    try {
      await open(item.id);
      say('');
      await refresh();
    } catch (e) {
      say(e.message);
    }
  }

  function exportItem(item) {
    const a = document.createElement('a');
    a.href = fileUrl(item.id, true);
    a.download = item.file;
    a.click();
    say('Exporting ' + item.title + '.');
  }

  function askDelete(item) {
    pendingDelete = item;
    $('library-delete-name').textContent = item.title;
    $('library-delete-file').textContent = item.file;
    $('library-delete-error').textContent = '';
    $('library-delete').showModal();
    $('library-delete-cancel').focus();
  }

  $('library-delete-cancel').onclick = () => $('library-delete').close();
  $('library-delete-confirm').onclick = async () => {
    try {
      await post('/api/library/delete', { id: pendingDelete.id });
      $('library-delete').close();
      say('Deleted ' + pendingDelete.title + '.');
      await refresh();
    } catch (e) {
      $('library-delete-error').textContent = e.message;
    }
  };
  $('library-delete').addEventListener('close', () => (pendingDelete = null));

  function showBrowse() {
    $('library-browse').hidden = false;
    $('library-import').hidden = true;
    $('library-show-import').setAttribute('aria-expanded', 'false');
  }
  function showImport() {
    $('library-browse').hidden = true;
    $('library-import').hidden = false;
    $('library-show-import').setAttribute('aria-expanded', 'true');
  }

  $('library-show-import').onclick = () => ($('library-import').hidden ? showImport() : showBrowse());
  $('library-import-back').onclick = showBrowse;
  $('library-export').onclick = showExport;
  for (const id of ['library-search', 'library-sort', 'library-filter'])
    $(id).addEventListener('input', render);
  $('library-files').onchange = async () => {
    const files = [...$('library-files').files];
    const failed = [];
    for (const file of files) {
      $('library-files-status').textContent = 'Adding ' + file.name + '…';
      try {
        await upload(file.name, file);
      } catch (e) {
        failed.push(e.message);
      }
    }
    $('library-files').value = '';
    $('library-files-status').textContent = '';
    await refresh();
    showBrowse();
    const added = files.length - failed.length;
    say((added ? `Added ${added} file${added === 1 ? '' : 's'}. ` : '') + failed.join(' '));
  };

  async function upload(name, body) {
    const r = await fetch('/api/library/upload?name=' + encodeURIComponent(name), {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body,
    });
    const reply = await r.json();
    if (!r.ok) throw Error(name + ': ' + (reply.error || 'upload failed'));
    return reply;
  }

  render();
  return { refresh, showImport, showBrowse, upload };
}
