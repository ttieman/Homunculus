// Navigate the guided UI using its visible step and disclosure controls.
async function reveal(page, control) {
  const location = await control.evaluate(el => {
    const step = el.closest('section[id^="step-"]');
    const summaries = [];
    for (let p = el.parentElement; p; p = p.parentElement)
      if (p.tagName === 'DETAILS' && !p.open) summaries.unshift(p.querySelector('summary').textContent);
    return { step: step?.id.split('-')[1], open: !!step?.checkVisibility(), summaries };
  });
  if (location.step !== undefined && !location.open)
    await page.locator(`[data-step="${location.step}"]`).click();
  if (
    (await control.evaluate(el => !!el.closest('#library-import'))) &&
    (await page.locator('#library-import').isHidden())
  )
    await page.locator('#library-show-import').click();
  for (const title of location.summaries) await page.getByText(title, { exact: true }).click();
}
const { test, expect } = require('@playwright/test');
const path = require('node:path');
const fs = require('node:fs/promises');

async function importCapture(page, source = false) {
  await page.goto('/');
  await page.locator('[data-step="1"]').click();
  await expect(
    page.getByRole('button', { includeHidden: true, name: 'Apply changes', exact: true }),
  ).toBeEnabled();
  if (source) await reveal(page, page.getByLabel('Preview your video locally'));
  await page
    .getByLabel('Preview your video locally')
    .setInputFiles(path.resolve('outputs/browser-fixture.webm'));
  await reveal(page, page.getByLabel('Import worker capture.json'));
  await page
    .getByLabel('Import worker capture.json')
    .setInputFiles(path.resolve('outputs/browser-fixture.json'));
  await expect(
    page.getByRole('button', { includeHidden: true, name: 'Use captured motion', exact: true }),
  ).toBeDisabled();
  await reveal(page, page.getByLabel('I checked the overlay, person and axis mapping'));
  await page.getByLabel('I checked the overlay, person and axis mapping').check();
  await reveal(
    page,
    page.getByRole('button', { includeHidden: true, name: 'Use captured motion', exact: true }),
  );
  await page.getByRole('button', { includeHidden: true, name: 'Use captured motion', exact: true }).click();
  await expect(
    page.getByRole('button', { includeHidden: true, name: 'Optimize captured motion', exact: true }),
  ).toBeEnabled();
}

test('reviewed import, source comparison, replay and timeline undo/redo', async ({ page }) => {
  await importCapture(page, true);
  if ((await page.locator('#compare-source').getAttribute('aria-pressed')) === 'false')
    await page.locator('#compare-source').click();
  await expect(page.locator('#sync-status')).toContainText('Matched source');
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Replay export', exact: true }));
  await page.getByRole('button', { includeHidden: true, name: 'Replay export', exact: true }).click();
  await expect(page.locator('#view-label')).toContainText('decoded animation buffers');
  await reveal(
    page,
    page.getByRole('button', { includeHidden: true, name: 'Assemble three poses', exact: true }),
  );
  await page.getByRole('button', { includeHidden: true, name: 'Assemble three poses', exact: true }).click();
  await expect(page.locator('#capture-status')).toContainText('3 editable keyframes');
  await reveal(page, page.getByLabel('New keyframe time (seconds)'));
  await page.getByLabel('New keyframe time (seconds)').fill('1.8');
  await reveal(
    page,
    page.getByRole('button', { includeHidden: true, name: 'Apply keyframe edit', exact: true }),
  );
  await page.getByRole('button', { includeHidden: true, name: 'Apply keyframe edit', exact: true }).click();
  await expect(page.getByRole('button', { includeHidden: true, name: 'Undo', exact: true })).toBeEnabled();
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Undo', exact: true }));
  await page.getByRole('button', { includeHidden: true, name: 'Undo', exact: true }).click();
  await expect(page.getByRole('button', { includeHidden: true, name: 'Redo', exact: true })).toBeEnabled();
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Redo', exact: true }));
  await page.getByRole('button', { includeHidden: true, name: 'Redo', exact: true }).click();
  await expect(
    page.getByRole('button', { includeHidden: true, name: 'Apply changes', exact: true }),
  ).toBeEnabled();
  if ((await page.locator('#compare-source').getAttribute('aria-pressed')) === 'false')
    await page.locator('#compare-source').click();
  await expect(page.locator('#sync-status')).toContainText('Matched source');
});

test('duration edits survive save and reimport', async ({ page }, testInfo) => {
  await importCapture(page);
  await page.locator('#duration').evaluate(el => {
    el.value = '6';
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Apply changes', exact: true }));
  await page.getByRole('button', { includeHidden: true, name: 'Apply changes', exact: true }).click();
  await expect(
    page.getByRole('button', { includeHidden: true, name: 'Save reference', exact: true }),
  ).toBeEnabled();
  const downloadPromise = page.waitForEvent('download');
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Save reference', exact: true }));
  await page.getByRole('button', { includeHidden: true, name: 'Save reference', exact: true }).click();
  const file = testInfo.outputPath('reference.json');
  await (await downloadPromise).saveAs(file);
  expect(JSON.parse(await fs.readFile(file, 'utf8')).reference_animation.keyframes.at(-1).time).toBe(6);
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Use demo reach', exact: true }));
  await page.getByRole('button', { includeHidden: true, name: 'Use demo reach', exact: true }).click();
  await expect(page.locator('#step-1')).toBeVisible();
  await expect(page.getByLabel('Import worker capture.json')).toBeEnabled();
  await reveal(page, page.getByLabel('Import worker capture.json'));
  await page.getByLabel('Import worker capture.json').setInputFiles(file);
  await reveal(page, page.getByLabel('I checked the overlay, person and axis mapping'));
  await page.getByLabel('I checked the overlay, person and axis mapping').check();
  await reveal(
    page,
    page.getByRole('button', { includeHidden: true, name: 'Use captured motion', exact: true }),
  );
  await page.getByRole('button', { includeHidden: true, name: 'Use captured motion', exact: true }).click();
  await expect(page.locator('#time')).toContainText('/ 6.00 s');
});

test('mismatched source cannot apply the capture', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-step="1"]').click();
  await expect(page.getByLabel('Import worker capture.json')).toBeEnabled();
  await reveal(page, page.getByLabel('Import worker capture.json'));
  await page
    .getByLabel('Import worker capture.json')
    .setInputFiles(path.resolve('outputs/browser-fixture.json'));
  await reveal(page, page.getByLabel('Preview your video locally'));
  await page
    .getByLabel('Preview your video locally')
    .setInputFiles({
      includeHidden: true,
      name: 'mismatch.webm',
      mimeType: 'video/webm',
      buffer: Buffer.from('not the source'),
    });
  await reveal(page, page.getByLabel('I checked the overlay, person and axis mapping'));
  await page.getByLabel('I checked the overlay, person and axis mapping').check();
  await reveal(
    page,
    page.getByRole('button', { includeHidden: true, name: 'Use captured motion', exact: true }),
  );
  await page.getByRole('button', { includeHidden: true, name: 'Use captured motion', exact: true }).click();
  await expect(page.locator('#capture-status')).toContainText('mismatch');
});

test('3D stage renders with WebGL and orbits', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await page.locator('[data-step="1"]').click();
  await expect(page.locator('#stage')).toHaveAttribute('data-renderer', 'webgl');
  await expect(page.locator('#time')).toContainText('/ 4.00 s');
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Pause playback' }));
  await page.getByRole('button', { includeHidden: true, name: 'Pause playback' }).click();
  const stage = page.locator('#stage');
  const before = await stage.screenshot();
  const box = await stage.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 160, box.y + box.height / 2 + 30, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(400);
  expect(Buffer.compare(before, await stage.screenshot())).not.toBe(0);
  expect(errors).toEqual([]);
});

test('configured character is posed, exported and replayed', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await page.locator('[data-step="1"]').click();
  await expect(page.locator('#stage')).toHaveAttribute('data-character', 'loaded');
  await expect(page.locator('#character-note')).toContainText('test-character.glb');
  await expect(
    page.getByRole('button', { includeHidden: true, name: 'Export character GLB', exact: true }),
  ).toBeEnabled();
  const downloadPromise = page.waitForEvent('download');
  await reveal(
    page,
    page.getByRole('button', { includeHidden: true, name: 'Export character GLB', exact: true }),
  );
  await page.getByRole('button', { includeHidden: true, name: 'Export character GLB', exact: true }).click();
  const file = await (await downloadPromise).path();
  expect((await fs.readFile(file)).subarray(0, 4).toString()).toBe('glTF');
  await reveal(page, page.getByLabel('Show physics arm'));
  await page.getByLabel('Show physics arm').check();
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Replay export', exact: true }));
  await page.getByRole('button', { includeHidden: true, name: 'Replay export', exact: true }).click();
  await expect(page.locator('#view-label')).toContainText('character clip');
  await page.waitForTimeout(300);
  expect(errors).toEqual([]);
});

test('full-body capture drives every character bone and exports the body clip', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await page.locator('[data-step="1"]').click();
  await expect(page.locator('#stage')).toHaveAttribute('data-character', 'loaded');
  await reveal(page, page.getByLabel('Import worker capture.json'));
  await page
    .getByLabel('Import worker capture.json')
    .setInputFiles(path.resolve('outputs/test-body-capture.json'));
  await expect(page.locator('#capture-status')).toContainText('full body (70 keypoints)');
  await reveal(page, page.getByLabel('I checked the overlay, person and axis mapping'));
  await page.getByLabel('I checked the overlay, person and axis mapping').check();
  await reveal(
    page,
    page.getByRole('button', { includeHidden: true, name: 'Use captured motion', exact: true }),
  );
  await page.getByRole('button', { includeHidden: true, name: 'Use captured motion', exact: true }).click();
  await expect(
    page.getByRole('button', { includeHidden: true, name: 'Optimize captured motion', exact: true }),
  ).toBeEnabled();
  await expect(page.locator('#stage')).toHaveAttribute('data-driven-bones', '19');
  const downloadPromise = page.waitForEvent('download');
  await reveal(
    page,
    page.getByRole('button', { includeHidden: true, name: 'Export character GLB', exact: true }),
  );
  await page.getByRole('button', { includeHidden: true, name: 'Export character GLB', exact: true }).click();
  const file = await (await downloadPromise).path();
  const glb = await fs.readFile(file);
  const json = JSON.parse(glb.subarray(20, 20 + glb.readUInt32LE(12)).toString());
  expect(json.animations[0].name).toBe('Homunculus_Body');
  expect(json.animations[0].channels.length).toBe(20); // 19 bone rotations + pelvis height
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Replay export', exact: true }));
  await page.getByRole('button', { includeHidden: true, name: 'Replay export', exact: true }).click();
  await expect(page.locator('#view-label')).toContainText('character clip');
  await page.waitForTimeout(300);
  expect(errors).toEqual([]);
});
