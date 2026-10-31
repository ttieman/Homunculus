const { test, expect } = require('@playwright/test');
const path = require('node:path');
const fs = require('node:fs');
const CAPTURE = path.resolve('outputs/test-body-capture.json');
const VIDEO = path.resolve('outputs/browser-fixture.webm');
const STORAGE = path.resolve('outputs/browser-test-storage');

async function openLibrary(page) {
  await page.goto('/');
  await expect(page.locator('#message')).toContainText('ready');
  await page.locator('[data-step="0"]').click();
  await expect(page.locator('#library-grid')).toBeVisible();
}
async function addFiles(page, files) {
  await page.locator('#library-show-import').click();
  await page.locator('#library-files').setInputFiles(files);
  await expect(page.locator('#library-grid')).toBeVisible();
}
const card = (page, text) => page.locator('.asset', { hasText: text });
const SAVED = '.asset:not([data-kind=character])';
test.beforeEach(() => fs.rmSync(STORAGE, { recursive: true, force: true }));

test('a large panel holds categories, import and export left and a searchable grid right', async ({
  page,
}) => {
  await openLibrary(page);
  await expect(page.locator('#library-empty')).toContainText('empty');
  await expect(page.getByRole('button', { name: 'Import', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Export', exact: true })).toBeVisible();
  for (const name of [
    'All assets',
    'Captures',
    'Recordings',
    'Animations',
    'Projects',
    'Scenes',
    'Characters',
  ])
    await expect(page.locator('#library-categories').getByRole('button', { name })).toBeVisible();
  await expect(page.getByLabel('Search the library')).toBeVisible();
  await expect(page.getByLabel('Sort')).toBeVisible();
  await expect(page.getByLabel('Filter')).toBeVisible();
  const panel = await page.locator('.layout').boundingBox();
  expect(panel.width).toBeGreaterThan(800);
  expect(panel.height).toBeGreaterThan(500);
});

test('imports sort into categories, and search, filter and sort narrow the grid', async ({ page }, info) => {
  await openLibrary(page);
  const scene = info.outputPath('stage.json');
  fs.writeFileSync(
    scene,
    JSON.stringify({ schema: 'homunculus.scene.v1', scene: { background: '#334455' }, settings: {} }),
  );
  await addFiles(page, [CAPTURE, VIDEO, scene]);
  await expect(page.locator('#library-status')).toContainText('Added 3 files');
  await expect(page.locator(SAVED)).toHaveCount(3);
  await expect(card(page, 'test-body-capture')).toContainText('full body');
  await expect(card(page, 'test-body-capture')).toContainText('Modified');
  await expect(card(page, 'test-body-capture')).toContainText('Created');
  await expect(card(page, 'test-body-capture').locator('svg.asset-pose')).toBeVisible();
  await page.locator('#library-categories').getByRole('button', { name: 'Recordings' }).click();
  await expect(page.locator('.asset')).toHaveCount(1);
  await expect(page.locator('.asset')).toContainText('not converted');
  await page.locator('#library-categories').getByRole('button', { name: 'All assets' }).click();
  await page.getByLabel('Search the library').fill('stage');
  await expect(page.locator('.asset')).toHaveCount(1);
  await page.getByLabel('Search the library').fill('');
  await page.getByLabel('Filter').selectOption('full-body');
  await expect(page.locator('.asset')).toHaveCount(1);
  await page.getByLabel('Filter').selectOption('any');
  await page.getByLabel('Sort').selectOption('name');
  const titles = await page.locator('.asset-main strong').allTextContents();
  expect(titles).toEqual([...titles].sort((a, b) => a.localeCompare(b)));
});

test('a rejected import explains itself and stores nothing', async ({ page }) => {
  await openLibrary(page);
  await addFiles(page, [{ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('hello') }]);
  await expect(page.locator('#library-status')).toContainText('notes.txt');
  await expect(page.locator(SAVED)).toHaveCount(0);
});

test('one click reveals open, rename, export and delete; delete needs confirmation', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await openLibrary(page);
  await addFiles(page, [CAPTURE]);
  const asset = page.locator(SAVED);
  await expect(asset.locator('.asset-action')).toHaveCount(0);
  await asset.locator('.asset-main').click();
  await expect(asset.locator('.asset-action')).toHaveCount(4);
  for (const name of ['Open', 'Rename', 'Export', 'Delete'])
    await expect(asset.getByRole('button', { name: new RegExp('^' + name + ' ') })).toBeEnabled();

  await asset.getByRole('button', { name: /^Rename / }).click();
  await asset.getByRole('textbox').fill('Sword draw');
  await asset.getByRole('textbox').press('Enter');
  await expect(asset.locator('strong')).toHaveText('Sword draw');

  const downloading = page.waitForEvent('download');
  await asset.getByRole('button', { name: /^Export / }).click();
  expect((await downloading).suggestedFilename()).toBe('capture.json');

  await asset.getByRole('button', { name: /^Delete / }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Are you sure');
  await expect(dialog).toContainText('Sword draw');
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(asset).toHaveCount(1);
  await asset.getByRole('button', { name: /^Delete / }).click();
  await page.keyboard.press('Escape');
  await expect(asset).toHaveCount(1);
  const folders = fs.readdirSync(path.join(STORAGE, 'clips'));
  expect(folders).toHaveLength(1);
  await asset.getByRole('button', { name: /^Delete / }).click();
  await dialog.getByRole('button', { name: 'Delete' }).click();
  await expect(asset).toHaveCount(0);
  expect(fs.readdirSync(path.join(STORAGE, 'clips'))).toHaveLength(0);
  expect(errors).toEqual([]);
});

test('opening a capture switches the scene and survives a reload as the last opened asset', async ({
  page,
}) => {
  await openLibrary(page);
  await addFiles(page, [CAPTURE]);
  await page.locator(SAVED + ' .asset-main').click();
  await page.getByRole('button', { name: /^Open / }).click();
  await expect(page.locator('#stage')).toHaveAttribute('data-driven-bones', '19');
  await expect(page.getByRole('tab', { name: '02 Review' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#chat-attachments .attachment')).toHaveCount(0);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.locator('#view-label')).toHaveText('Sample arm reach');
  await page.reload();
  await expect(page.locator('#apply')).toBeEnabled();
  await page.locator('[data-step="0"]').click();
  await expect(page.locator(SAVED)).toContainText('Last opened');
});

test('save a GLB and project to the library, preview the GLB, then reopen the project', async ({ page }) => {
  await openLibrary(page);
  await addFiles(page, [CAPTURE]);
  await page.locator(SAVED + ' .asset-main').click();
  await page.getByRole('button', { name: /^Open / }).click();
  await expect(page.locator('#stage')).toHaveAttribute('data-driven-bones', '19');
  await page.locator('[data-step="3"]').click();
  await page.getByRole('button', { name: 'Save GLB to library' }).click();
  await expect(page.locator('#message')).toContainText('to the library');
  await page.getByRole('button', { name: 'Save project to library' }).click();
  await expect
    .poll(
      () =>
        fs.existsSync(path.join(STORAGE, 'projects')) &&
        fs.readdirSync(path.join(STORAGE, 'projects')).length,
    )
    .toBe(1);
  expect(fs.readdirSync(path.join(STORAGE, 'exports'))).toHaveLength(1);

  await page.locator('[data-step="0"]').click();
  await page.locator('#library-categories').getByRole('button', { name: 'Animations' }).click();
  await page.locator('.asset-main').click();
  await page.getByRole('button', { name: /^Open / }).click();
  await expect(page.locator('#glb-close')).toBeVisible();
  await expect(page.locator('#view-label')).toContainText('Saved GLB');
  await expect(page.locator('#step-0')).toBeHidden();
  await page.locator('[data-step="3"]').click();
  await expect(page.locator('#export-character')).toBeDisabled();
  await expect(page.locator('#export-status')).toContainText('previewing');
  await page.locator('#glb-close').click();
  await expect(page.locator('#export-character')).toBeEnabled();

  await page.locator('[data-step="0"]').click();
  await page.locator('#library-categories').getByRole('button', { name: 'Projects' }).click();
  await page.locator('.asset-main').click();
  await page.getByRole('button', { name: /^Open / }).click();
  await expect(page.getByRole('tab', { name: '03 Edit' })).toHaveAttribute('aria-selected', 'true');
});

test('an unconverted recording opens ready to convert, and the character is export only', async ({
  page,
}) => {
  await openLibrary(page);
  await addFiles(page, [VIDEO]);
  await page.locator('#library-categories').getByRole('button', { name: 'Characters' }).click();
  await page.locator('.asset-main').click();
  await expect(page.getByRole('button', { name: /^Open / })).toBeDisabled();
  await expect(page.getByRole('button', { name: /^Rename / })).toBeDisabled();
  await expect(page.getByRole('button', { name: /^Delete / })).toBeDisabled();
  await expect(page.getByRole('button', { name: /^Export / })).toBeEnabled();
  await page.locator('#library-categories').getByRole('button', { name: 'Recordings' }).click();
  await page.locator('.asset-main').click();
  await page.getByRole('button', { name: /^Open / }).click();
  await expect(page.locator('#process-submit')).toBeEnabled();
  await expect(page.locator('#job-status')).toContainText('Video selected');
});

test('the large panel stays usable at every width and closes the chat when there is no room', async ({
  page,
}) => {
  await openLibrary(page);
  await addFiles(page, [CAPTURE]);
  await page.setViewportSize({ width: 1500, height: 850 });
  await page.locator('[data-step="0"]').click();
  await page.locator('[data-step="0"]').click();
  await expect(page.locator('#chat-panel')).toBeVisible();
  const open = await page.locator('.layout').boundingBox();
  const chat = await page.locator('#muse-dock').boundingBox();
  expect(open.x + open.width).toBeLessThanOrEqual(chat.x);
  for (const width of [1000, 768, 320]) {
    await page.setViewportSize({ width, height: 800 });
    await expect(page.locator('#chat-panel')).toBeHidden();
    await page.locator(SAVED + ' .asset-main').click();
    await expect(page.locator('.asset-action')).toHaveCount(4);
    for (const action of await page.locator('.asset-action').all()) await expect(action).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.locator(SAVED + ' .asset-main').click();
  }
});

test('Muse commands list and open assets but offer no rename or delete', async ({ page }) => {
  await openLibrary(page);
  await addFiles(page, [CAPTURE]);
  const tools = (await (await page.request.get('/api/commands')).json()).tools.map(t => t.function.name);
  expect(tools).toEqual(expect.arrayContaining(['list_library', 'open_library_asset', 'save_to_library']));
  expect(tools.filter(t => /delete|rename/.test(t))).toEqual([]);
});
