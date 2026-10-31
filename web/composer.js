// Body selections are a draft until the shared compose_motion command succeeds.
export function createComposer(workspace, read) {
  const $ = id => document.getElementById(id);
  const groups = {
    Torso: ['pelvis', 'spine', 'chest'],
    Head: ['neck', 'head'],
    'Left arm': ['shoulder.L', 'upper_arm.L', 'forearm.L', 'hand.L'],
    'Right arm': ['shoulder.R', 'upper_arm.R', 'forearm.R', 'hand.R'],
    'Left leg': ['thigh.L', 'shin.L', 'foot.L'],
    'Right leg': ['thigh.R', 'shin.R', 'foot.R'],
  };
  let draft = false;
  for (const [group, bones] of Object.entries(groups)) {
    const fieldset = document.createElement('fieldset');
    const legend = document.createElement('legend');
    legend.textContent = group;
    fieldset.append(legend);
    for (const bone of bones) {
      const label = document.createElement('label'),
        input = document.createElement('input');
      input.type = 'checkbox';
      input.value = bone;
      input.checked = true;
      input.dataset.bone = bone;
      label.append(input, bone.replace('.L', ' left').replace('.R', ' right').replace('_', ' '));
      fieldset.append(label);
    }
    $('bone-targets').append(fieldset);
  }
  function changed() {
    draft = true;
    $('composition-status').textContent = 'Selection changed. Apply targets to update the animation.';
    read().refresh();
  }
  $('bone-targets').onchange = changed;
  for (const id of ['composition-mode', 'composition-source', 'composition-blend', 'composition-root'])
    $(id).onchange = changed;
  $('target-preset').onchange = () => {
    const value = $('target-preset').value;
    document
      .querySelectorAll('[data-bone]')
      .forEach(el => (el.checked = value === 'All joints' || (groups[value] || []).includes(el.value)));
    $('composition-root').checked = value === 'All joints';
    changed();
  };
  $('composition-file').onchange = async () => {
    const file = $('composition-file').files[0];
    if (!file) return;
    try {
      const item = await workspace.attach(file);
      if (item.kind !== 'capture')
        throw Error('Choose a capture or saved reference JSON for the second motion.');
      refreshSources();
      $('composition-source').value = item.id;
      changed();
      $('composition-status').textContent =
        'Second clip attached: ' + file.name + '. Choose joints and apply.';
    } catch (e) {
      $('composition-status').textContent = e.message;
    } finally {
      $('composition-file').value = '';
    }
  };
  function refreshSources() {
    const old = $('composition-source').value;
    $('composition-source').replaceChildren(new Option('Choose an attached capture', ''));
    for (const a of workspace.state().attachments.filter(a => a.kind === 'capture'))
      $('composition-source').append(new Option(a.name, a.id));
    $('composition-source').value = old;
  }
  $('apply-composition').onclick = async () => {
    const mode = $('composition-mode').value;
    try {
      await workspace.manual('compose_motion', {
        mode,
        bones: [...document.querySelectorAll('[data-bone]:checked')].map(el => el.value),
        rootMotion: $('composition-root').checked,
        blend: Number($('composition-blend').value),
        ...(mode === 'mask' ? {} : { sourceId: $('composition-source').value }),
      });
    } catch (e) {
      $('composition-status').textContent = e.message;
    }
  };
  $('clear-composition').onclick = () =>
    workspace.manual('clear_composition').catch(e => ($('composition-status').textContent = e.message));
  function applied(composition) {
    draft = false;
    $('target-preset').selectedIndex = 0;
    $('composition-mode').value = composition?.mode || 'mask';
    $('composition-root').checked = composition?.rootMotion ?? true;
    $('composition-blend').value = composition?.blend ?? 0.25;
    document
      .querySelectorAll('[data-bone]')
      .forEach(el => (el.checked = !composition || composition.bones.includes(el.value)));
    $('composition-status').textContent = composition
      ? `${composition.mode}: ${composition.bones.length} joint tracks${composition.rootMotion ? ' + pelvis translation' : ''}. Preview and GLB use this result.`
      : 'Full base animation. Choose a limb or individual joints to target.';
  }
  applied(null);
  refreshSources();
  return {
    applied,
    refreshSources,
    get dirty() {
      return draft;
    },
  };
}
