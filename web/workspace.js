// The application and Muse call the same validated command dispatcher.
const $ = id => document.getElementById(id);
export const defaultScene = { background: '#142024', grid: true, light: 2.1, camera: 'home', props: [] };
export function createWorkspace(app) {
  let scene = structuredClone(defaultScene),
    undo = [],
    redo = [],
    revision = 0,
    executing = false,
    chatting = false,
    stopped = false;
  const attachments = new Map();
  let messages = [];
  let nextId = 1;
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const scrollChat = () => {
    const box = $('chat-scroll');
    box.scrollTop = box.scrollHeight;
  };
  // Model text is escaped before the small Markdown subset is applied.
  const markdown = text => {
    const escaped = text.replace(
      /[&<>"]/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c],
    );
    const inline = s =>
      s.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    return escaped
      .split(/\n{2,}/)
      .map(block => {
        const lines = block.split('\n');
        if (lines.every(l => /^\s*([-*]|\d+\.)\s+/.test(l))) {
          const tag = /^\s*\d+\./.test(lines[0]) ? 'ol' : 'ul';
          return `<${tag}>${lines.map(l => `<li>${inline(l.replace(/^\s*([-*]|\d+\.)\s+/, ''))}</li>`).join('')}</${tag}>`;
        }
        return `<p>${inline(lines.join('<br>'))}</p>`;
      })
      .join('');
  };
  const post = node => {
    $('chat-empty').hidden = true;
    $('chat-log').append(node);
    scrollChat();
    return node;
  };
  const say = {
    user(text, images) {
      const row = element('div', 'chat-msg chat-user');
      const bubble = element('div', 'chat-bubble', text);
      if (images.length) {
        const strip = element('div', 'chat-images');
        for (const a of images) {
          const img = element('img');
          img.src = a.dataURL;
          img.alt = a.name;
          strip.append(img);
        }
        bubble.prepend(strip);
      }
      row.append(bubble);
      post(row);
    },
    muse(text) {
      const row = element('div', 'chat-msg chat-muse');
      const body = element('div', 'chat-text');
      body.innerHTML = markdown(text);
      row.append(body);
      post(row);
    },
    tool(name, args, receipt) {
      const card = element('details', 'chat-tool ' + (receipt.ok ? 'ok' : 'failed'));
      const summary = element('summary');
      summary.append(
        element('span', 'chat-tool-icon', receipt.ok ? '✓' : '✕'),
        element('span', 'chat-tool-name', name.replaceAll('_', ' ')),
        element('span', 'chat-tool-state', receipt.ok ? 'Tool completed' : 'Tool failed'),
      );
      const detail = element(
        'pre',
        '',
        JSON.stringify({ arguments: args, result: receipt.result ?? receipt.error }, null, 2),
      );
      card.append(summary, detail);
      post(card);
    },
    notice(text, error = false) {
      post(element('div', 'chat-notice' + (error ? ' error' : ''), text));
    },
  };
  const log = (role, text) => say.notice(`${role}: ${text}`, /error/i.test(role));
  function syncScene() {
    app.configureScene(scene);
    $('scene-background').value = scene.background;
    $('scene-grid').checked = scene.grid;
    $('scene-light').value = scene.light;
    $('scene-camera').value = scene.camera;
  }
  function snapshot() {
    return { app: app.snapshot(), scene: structuredClone(scene) };
  }
  async function restore(value) {
    await app.restore(value.app);
    scene = structuredClone(value.scene);
    syncScene();
  }
  function state() {
    return {
      ...app.inspect(),
      scene: structuredClone(scene),
      revision,
      undo: undo.length,
      redo: redo.length,
      attachments: [...attachments.values()].map(({ id, name, kind }) => ({ id, name, kind })),
    };
  }
  const handlers = {
    ...app.actions,
    inspect_workspace: async () => state(),
    compose_motion: async args => {
      const item = args.sourceId ? attachments.get(args.sourceId) : null;
      if (args.mode !== 'mask' && item?.kind !== 'capture')
        throw Error('Choose an attached capture for the second animation.');
      return app.actions.compose_motion(args, args.mode === 'mask' ? null : item.data);
    },
    set_scene: async args => {
      scene = { ...scene, ...structuredClone(args) };
      syncScene();
      return { scene, physics: 'Props are visual only; simulated collision uses the obstacle setting.' };
    },
    // Library files pass through the normal attachment path but do not stay attached.
    open_library_asset: async ({ id }) => {
      const opened = await app.openAsset(id);
      if (!opened.file) return opened.result;
      const item = await attach(opened.file);
      try {
        const value = await handlers.use_attachment({ id: item.id });
        opened.done?.();
        return value;
      } finally {
        detach(item.id);
      }
    },
    save_to_library: async ({ format }) => {
      if (format !== 'scene') return app.actions.save_to_library({ format });
      return app.saveAsset(
        'scene.json',
        JSON.stringify({ schema: 'homunculus.scene.v1', scene, settings: app.inspect().settings }),
      );
    },
    undo: async () => {
      if (!undo.length) throw Error('Nothing to undo');
      const before = snapshot();
      await restore(undo.at(-1));
      undo.pop();
      redo.push(before);
    },
    redo: async () => {
      if (!redo.length) throw Error('Nothing to redo');
      const before = snapshot();
      await restore(redo.at(-1));
      redo.pop();
      undo.push(before);
    },
    use_attachment: async ({ id }) => {
      const item = attachments.get(id);
      if (!item) throw Error('Unknown attachment ID');
      if (item.kind === 'video') {
        await app.useVideo(item.file);
        return { status: 'Local video preview selected; SAM inference has not run.' };
      }
      if (item.kind === 'capture') return app.useCapture(item.data);
      if (item.kind === 'project') return app.loadProject(item.data);
      if (item.kind === 'scene') {
        const d = item.data;
        if (d.schema !== 'homunculus.scene.v1') throw Error('Unsupported scene');
        await app.validate('set_scene', d.scene);
        await app.validate('set_settings', d.settings);
        await app.actions.set_settings(d.settings);
        scene = { ...structuredClone(defaultScene), ...d.scene };
        syncScene();
        return { status: 'Scene loaded' };
      }
      throw Error(
        'Images are chat references, not captured poses. Run SAM and attach its capture JSON to drive motion.',
      );
    },
    export_asset: async ({ format }) => {
      if (format === 'scene') {
        app.download('homunculus-scene.json', {
          schema: 'homunculus.scene.v1',
          scene,
          settings: app.inspect().settings,
        });
        return { status: 'Scene download requested' };
      }
      return app.actions.export_asset({ format });
    },
  };
  async function perform(name, args = {}, source = 'manual') {
    if (name === 'navigate_stage') {
      await app.validate(name, args);
      const value = await app.actions.navigate_stage(args);
      revision++;
      return { ok: true, command: name, source, result: value, revision };
    }
    if (executing || app.busy()) throw Error('Another operation is still running');
    executing = true;
    $('undo').disabled = true;
    $('redo').disabled = true;
    let before;
    try {
      await app.validate(name, args);
      if (!handlers[name]) throw Error('Command is not implemented');
      before = snapshot();
      const value = await handlers[name](args);
      if (
        ![
          'inspect_workspace',
          'navigate_stage',
          'playback',
          'export_asset',
          'list_library',
          'save_to_library',
          'undo',
          'redo',
        ].includes(name)
      ) {
        undo.push(before);
        if (undo.length > 30) undo.shift();
        redo = [];
      }
      if (name !== 'inspect_workspace') revision++;
      $('undo').disabled = !undo.length;
      $('redo').disabled = !redo.length;
      return { ok: true, command: name, source, result: value ?? { status: 'Applied' }, revision };
    } catch (error) {
      throw error;
    } finally {
      executing = false;
      $('undo').disabled = app.busy() || !undo.length;
      $('redo').disabled = app.busy() || !redo.length;
    }
  }
  function manual(name, args = {}) {
    return perform(name, args).catch(e => {
      $('message').textContent = e.message;
      throw e;
    });
  }
  function bind(id, name, args = () => ({})) {
    $(id).onclick = () => manual(name, args()).catch(() => {});
  }
  bind('apply', 'set_settings', () => {
    const rotation = app.pendingRotation();
    return { edit: app.fields(), ...(rotation ? { rotation } : {}) };
  });
  bind('optimize', 'optimize');
  bind('use-fixture', 'use_demo');
  bind('undo', 'undo');
  bind('redo', 'redo');
  bind('three-poses', 'assemble_three_poses');
  bind('play', 'playback', () => ({ playing: !app.inspect().playback.playing }));
  bind('replay', 'playback', () => ({ replay: !app.inspect().playback.replay }));
  for (const [id, format] of [
    ['export', 'arm'],
    ['export-character', 'character'],
    ['save', 'session'],
    ['save-reference', 'reference'],
    ['save-scene', 'scene'],
  ])
    bind(id, 'export_asset', () => ({ format }));
  for (const format of ['character', 'project', 'scene'])
    bind('library-save-' + format, 'save_to_library', () => ({ format }));
  bind('apply-scene', 'set_scene', () => ({
    background: $('scene-background').value,
    grid: $('scene-grid').checked,
    light: Number($('scene-light').value),
    camera: $('scene-camera').value,
  }));
  bind('add-prop', 'set_scene', () => ({
    props: [
      ...scene.props,
      {
        id: 'prop-' + nextId++,
        shape: $('prop-shape').value,
        position: [Number($('prop-x').value), Number($('prop-y').value), Number($('prop-z').value)],
        scale: [0.3, 0.3, 0.3],
        color: '#d7945b',
      },
    ],
  }));
  bind('clear-props', 'set_scene', () => ({ props: [] }));
  $('timeline').oninput = () =>
    manual('playback', { time: Number($('timeline').value) * app.inspect().playback.duration }).catch(
      () => {},
    );
  $('character-view').onchange = () =>
    manual('set_settings', { view: $('character-view').value }).catch(() => {});
  $('show-physics').onchange = () =>
    manual('set_settings', { showPhysics: $('show-physics').checked }).catch(() => {});
  // A control edited while a model request is in flight makes its proposed calls stale.
  for (const id of ['duration', 'shoulder_deg', 'elbow_deg', 'strength', 'damping', 'obstacle'])
    $(id).addEventListener('input', () => revision++);
  document.addEventListener('change', e => {
    if (e.target.closest('.composition-panel')) revision++;
  });
  async function attach(file) {
    if (attachments.size >= 12) throw Error('Remove an attachment before adding more (limit 12).');
    let kind =
      file.type.startsWith('video/') || /\.(mkv|mp4|webm)$/i.test(file.name)
        ? 'video'
        : file.type.startsWith('image/')
          ? 'image'
          : 'json';
    const limit = kind === 'video' ? 100 * 1024 * 1024 : kind === 'image' ? 1400000 : 8 * 1024 * 1024;
    if (file.size > limit)
      throw Error(`${file.name}: file exceeds ${Math.round((limit / 1024 / 1024) * 10) / 10} MB limit`);
    const item = { id: 'media-' + nextId++, name: file.name, kind, file };
    if (kind === 'json') {
      item.data = JSON.parse(await file.text());
      item.kind =
        item.data.schema === 'homunculus.project.v1'
          ? 'project'
          : item.data.schema === 'homunculus.scene.v1'
            ? 'scene'
            : 'capture';
      if (item.kind === 'capture') await app.validateCapture(item.data);
      else if (item.kind === 'project') {
        await app.validateCapture(item.data.capture);
      } else {
        await app.validate('set_scene', item.data.scene);
        await app.validate('set_settings', item.data.settings);
      }
    }
    if (kind === 'image')
      item.dataURL = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
    attachments.set(item.id, item);
    revision++;
    renderAttachments();
    return item;
  }
  function detach(id) {
    attachments.delete(id);
    renderAttachments();
  }
  function renderAttachments() {
    app.attachmentsChanged?.();
    $('chat-attachments').replaceChildren();
    for (const item of attachments.values()) {
      const row = element('div', 'attachment');
      row.title = `${item.id}: ${item.name}`;
      if (item.kind === 'image') {
        const img = element('img');
        img.src = item.dataURL;
        img.alt = item.name;
        row.append(img);
      } else row.append(element('span', 'attachment-kind', item.kind === 'video' ? '▶' : '{ }'));
      const label = element('span', 'attachment-name');
      label.append(element('span', '', item.name), element('small', '', item.kind));
      row.append(label);
      if (item.kind !== 'image') {
        const use = element('button', 'attachment-use', 'Use');
        use.type = 'button';
        use.onclick = () => manual('use_attachment', { id: item.id }).catch(() => {});
        row.append(use);
      }
      const remove = element('button', 'attachment-remove', '×');
      remove.type = 'button';
      remove.title = remove.ariaLabel = 'Remove ' + item.name;
      remove.onclick = () => {
        attachments.delete(item.id);
        revision++;
        renderAttachments();
      };
      row.append(remove);
      $('chat-attachments').append(row);
    }
  }
  $('chat-files').onchange = async () => {
    for (const file of $('chat-files').files) {
      try {
        await attach(file);
      } catch (e) {
        log('Attachment error', e.message);
      }
    }
    $('chat-files').value = '';
  };
  $('chat-prompt').addEventListener('paste', async event => {
    const files = [...event.clipboardData.files];
    if (files.length) {
      event.preventDefault();
      for (const file of files) {
        try {
          await attach(file);
        } catch (e) {
          log('Attachment error', e.message);
        }
      }
    }
  });
  let dragDepth = 0;
  $('chat-panel').ondragenter = e => {
    if (e.dataTransfer?.types.includes('Files') && ++dragDepth === 1) $('chat-drop').hidden = false;
  };
  $('chat-panel').ondragleave = () => {
    if (dragDepth && --dragDepth === 0) $('chat-drop').hidden = true;
  };
  $('chat-panel').ondragover = e => e.preventDefault();
  $('chat-panel').ondrop = async e => {
    e.preventDefault();
    dragDepth = 0;
    $('chat-drop').hidden = true;
    for (const file of e.dataTransfer.files) {
      try {
        await attach(file);
      } catch (error) {
        log('Attachment error', error.message);
      }
    }
  };
  $('chat-stop').onclick = () => {
    stopped = true;
    $('chat-stop').disabled = true;
    say.notice('Stopping after the current request or action completes.');
  };
  $('chat-clear').onclick = () => {
    if (chatting) return;
    messages = [];
    $('chat-log').replaceChildren();
    $('chat-empty').hidden = false;
    $('chat-prompt').focus();
  };
  const fitPrompt = () => {
    const box = $('chat-prompt');
    box.style.height = 'auto';
    box.style.height = Math.min(box.scrollHeight, 200) + 'px';
    $('chat-send').disabled = chatting || !box.value.trim();
  };
  $('chat-prompt').addEventListener('input', fitPrompt);
  $('chat-prompt').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (!$('chat-send').disabled) $('chat-send').click();
    }
  });
  for (const chip of document.querySelectorAll('.chat-suggestions button'))
    chip.onclick = () => {
      $('chat-prompt').value = chip.textContent;
      fitPrompt();
      $('chat-prompt').focus();
    };
  const setChatting = value => {
    chatting = value;
    $('chat-typing').hidden = !value;
    $('chat-stop').hidden = !value;
    $('chat-stop').disabled = !value;
    $('chat-send').hidden = value;
    fitPrompt();
    if (value) scrollChat();
  };
  fetch('/api/commands')
    .then(r => r.json())
    .then(({ tools }) => {
      for (const tool of tools) {
        const option = document.createElement('option');
        option.value = option.textContent = tool.function.name;
        $('command-name').append(option);
      }
    });
  fetch('/api/status')
    .then(r => r.json())
    .then(s => {
      const ready = s.meta.startsWith('configured');
      $('chat-status').lastChild.textContent = ready
        ? `${s.model} · key configured`
        : 'No API key: add MODEL_API_KEY to .env.local';
      $('chat-status').classList.toggle('ready', ready);
    })
    .catch(e => {
      $('chat-status').lastChild.textContent = e.message;
    });
  $('run-command').onclick = async () => {
    try {
      const receipt = await manual($('command-name').value, JSON.parse($('command-arguments').value));
      $('command-result').textContent = JSON.stringify(receipt, null, 2);
    } catch (e) {
      $('command-result').textContent = JSON.stringify({ ok: false, error: e.message }, null, 2);
    }
  };
  $('chat-send').onclick = async () => {
    if (chatting) return;
    if (executing || app.busy()) {
      say.notice('Muse can start once the current operation finishes. Your message is still in the box.');
      return;
    }
    const text = $('chat-prompt').value.trim();
    if (!text) return;
    const images = [...attachments.values()].filter(a => a.kind === 'image');
    if (images.length > 4) {
      log('Workspace', 'Use at most four image references per message.');
      return;
    }
    stopped = false;
    messages.push({
      role: 'user',
      content: [
        { type: 'text', text },
        ...images.map(a => ({ type: 'image_url', image_url: { url: a.dataURL } })),
      ],
    });
    $('chat-prompt').value = '';
    say.user(text, images);
    // Images now live in the conversation history; files Muse can act on stay attached.
    if (images.length) {
      for (const a of images) attachments.delete(a.id);
      renderAttachments();
    }
    setChatting(true);
    try {
      for (let step = 0; step < 8; step++) {
        if (stopped) break;
        const base = revision;
        const response = await app.chat({ messages, state: state() });
        const message = response.message;
        messages.push(message);
        if (message.content) say.muse(message.content);
        const calls = message.tool_calls || [];
        if (!calls.length) break;
        let blocked = stopped || base !== revision;
        for (const call of calls) {
          let receipt, args;
          try {
            if (blocked || stopped)
              throw Error(
                'Actions skipped because the workspace changed, a previous action failed, or Stop was pressed. Ask again.',
              );
            args = JSON.parse(call.function.arguments);
            receipt = await perform(call.function.name, args, 'Muse');
          } catch (e) {
            blocked = true;
            receipt = { ok: false, error: e.message };
          }
          messages.push({ role: 'tool', tool_call_id: call.id, content: JSON.stringify(receipt) });
          say.tool(call.function.name, args ?? call.function.arguments, receipt);
        }
        if (blocked) break;
        if (step === 7) say.notice('Reached the eight-step limit. Ask Muse to continue if needed.');
      }
    } catch (e) {
      say.notice('Muse error: ' + e.message, true);
    } finally {
      setChatting(false);
      $('chat-prompt').focus();
    }
  };
  syncScene();
  return { perform, manual, attach, detach, state };
}
