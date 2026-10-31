export function createWorkflow(read, navigate, onPanel) {
  const $ = id => document.getElementById(id);
  let step = 0;
  let panelOpen = false;
  const narrow = matchMedia('(max-width: 800px)');
  const tight = matchMedia('(max-width: 1100px)'); // the large library panel has no room beside chat here
  const crowded = () => narrow.matches || (tight.matches && panelOpen && names[step] === 'import');
  const layout = document.querySelector('.layout');
  const viewer = document.querySelector('main');
  const names = ['import', 'review', 'edit', 'export', 'capture'];
  const tabOrder = [4, 0, 1, 2, 3]; // Capture comes first on screen; step numbers stay stable
  const nav = document.querySelector('nav');
  nav.setAttribute('role', 'tablist');
  const views = names.map((name, i) => {
    const view = document.createElement('div');
    view.id = 'workspace-' + name;
    view.className = 'stage-workspace';
    view.setAttribute('role', 'tabpanel');
    view.setAttribute('aria-labelledby', 'tab-' + name);
    view.append($('step-' + i));
    layout.append(view);
    const tab = document.querySelector(`[data-step="${i}"]`);
    tab.id = 'tab-' + name;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', view.id);
    tab.onkeydown = e => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
      e.preventDefault();
      const at = tabOrder.indexOf(step);
      const next =
        tabOrder[e.key === 'Home' ? 0 : e.key === 'End' ? 4 : (at + (e.key === 'ArrowRight' ? 1 : 4)) % 5];
      document.querySelector(`[data-step="${next}"]`).click();
      document.querySelector(`[data-step="${next}"]`).focus();
    };
    return view;
  });
  document.querySelectorAll('.layout > aside > section').forEach(el => layout.append(el));
  document.querySelector('.layout > aside').remove();
  // The 3D viewport is the page's base layer; every menu floats above it.
  document.body.prepend(viewer);

  for (const id of ['undo', 'redo']) $('history-controls').append($(id));
  for (const id of ['export-character', 'replay']) $('primary-export').append($(id));
  $('export-character').classList.add('primary');
  $('reference-export').append($('save-reference'));
  $('physics-home').append($('physics-toggle'));
  const setChat = open => {
    document.body.dataset.chat = open ? 'open' : 'closed';
    $('chat-panel').hidden = !open;
    $('chat-launcher').hidden = open;
    if (open && crowded()) setPanel(false);
  };
  const setPanel = open => {
    panelOpen = open;
    layout.hidden = !open;
    for (const b of document.querySelectorAll('[data-step]'))
      b.setAttribute('aria-expanded', String(open && Number(b.dataset.step) === step));
    if (open && crowded()) setChat(false);
    onPanel?.(open, names[step]);
  };
  const go = (n, reveal = true) => {
    if (!reveal && panelOpen) return; // never switch a menu the user is working in
    step = Number(n);
    document.body.dataset.stage = names[step];
    views.forEach((v, i) => (v.hidden = i !== step));
    for (let i = 0; i < names.length; i++) {
      $('step-' + i).hidden = i !== step;
      const b = document.querySelector(`[data-step="${i}"]`);
      b.setAttribute('aria-selected', String(i === step));
      b.tabIndex = i === step ? 0 : -1;
      if (i === step) b.setAttribute('aria-current', 'step');
      else b.removeAttribute('aria-current');
    }
    setPanel(reveal || panelOpen);
  };
  document.querySelectorAll('[data-step], [data-go]').forEach(b => {
    b.addEventListener('click', () => {
      if (panelOpen && Number(b.dataset.step) === step) return setPanel(false);
      navigate(names[Number(b.dataset.step ?? b.dataset.go)]);
    });
  });
  for (const query of [narrow, tight])
    query.addEventListener('change', () => {
      if (panelOpen && crowded()) setChat(false);
    });
  $('panel-close').onclick = () => setPanel(false);
  $('chat-collapse').onclick = () => setChat(false);
  $('chat-launcher').onclick = () => {
    setChat(true);
    $('chat-prompt').focus();
  };
  $('compare-source').onclick = () => {
    const show = $('comparison').classList.toggle('show-source');
    $('compare-source').setAttribute('aria-pressed', String(show));
  };
  function sync() {
    const s = read();
    $('clip-title').textContent = s.capture ? 'Captured performance' : 'Sample reach';
    $('review-summary').textContent = s.capture
      ? `${s.duration.toFixed(2)} seconds of captured motion. Watch the preview before continuing.`
      : 'You are viewing the sample arm reach. Import a performance when you are ready.';
    $('compare-source').disabled = $('source-pane').hidden;
    $('edit-status').textContent = s.dirty
      ? 'You have unapplied changes. Apply them to update the preview and export.'
      : 'Preview is up to date.';
    $('export-status').textContent = s.processing
      ? 'Converting your video\u2026'
      : s.busy
        ? 'Updating animation\u2026'
        : s.dirty
          ? 'Apply your changes in Edit before exporting.'
          : !s.character
            ? 'Character GLB is unavailable. Start the editor with a character rig to export a character.'
            : 'Ready to preview and download the character animation.';
    for (const id of [
      'export-character',
      'export',
      'replay',
      'save-reference',
      'save-project',
      'library-save-character',
      'library-save-project',
    ]) {
      $(id).disabled =
        s.busy ||
        s.processing ||
        s.dirty ||
        !s.ready ||
        (['export-character', 'library-save-character'].includes(id) && !s.character) ||
        (['save-reference', 'save-project', 'library-save-project'].includes(id) && !s.capture);
    }
    if (s.preview)
      $('export-status').textContent =
        'A saved GLB is previewing. Close the preview to export the current animation.';
    $('library-show-import').textContent = s.processing ? 'Import · converting…' : 'Import';
    $('process-submit').disabled = s.busy || s.processing || !$('process-file').files.length;
    $('process-start').disabled = s.processing;
    $('step-2').inert = s.processing;
    if (s.processing) {
      $('undo').disabled = true;
      $('redo').disabled = true;
      $('use-capture').disabled = true;
    }
    document
      .querySelectorAll('.composition-panel button, .composition-panel input, .composition-panel select')
      .forEach(el => (el.disabled = s.busy || s.processing));
    $('process-progress').hidden = !s.processing;
    for (const id of ['process-file', 'capture-file', 'video-file', 'use-fixture', 'apply'])
      if (s.processing) $(id).disabled = true;
  }
  for (const id of [
    'duration',
    'shoulder_deg',
    'elbow_deg',
    'strength',
    'damping',
    'obstacle',
    'process-file',
  ])
    $(id).addEventListener('input', sync);
  go(0, false);
  setChat(!narrow.matches);
  sync();
  return {
    sync,
    go,
    close: () => setPanel(false),
    get stage() {
      return names[step];
    },
  };
}
