const { test, expect } = require('@playwright/test');
const path = require('node:path');
const fs = require('node:fs/promises');

test('rotation preview, export, undo/redo, reset and saved project agree', async ({ page }, info) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await expect(page.locator('#apply')).toBeEnabled();
  await page.locator('[data-step="0"]').click();
  await page.locator('#library-show-import').click();
  await page.getByText('Open an existing capture', { exact: true }).click();
  const capture = JSON.parse(await fs.readFile(path.resolve('outputs/test-body-capture.json'), 'utf8'));
  for (const frame of capture.frames) frame.t *= 1.0005; // fractional duration must not appear unapplied after import
  await page
    .locator('#capture-file')
    .setInputFiles({
      name: 'fractional-capture.json',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify(capture)),
    });
  await page.locator('#review-capture').check();
  await page.locator('#use-capture').click();
  await expect(page.locator('#stage')).toHaveAttribute('data-driven-bones', '19');
  await page.locator('[data-step="2"]').click();
  await expect(page.locator('#rotation-pitch')).toBeEnabled();
  await expect(page.locator('#edit-status')).toContainText('up to date');
  await page.locator('#rotation-pitch').fill('-29.7');
  await page.locator('#rotation-yaw').fill('45');
  await expect(page.locator('#edit-status')).toContainText('unapplied');
  const pending = page.waitForResponse(
    r => r.url().endsWith('/api/simulate') && r.request().method() === 'POST',
  );
  await page.locator('#apply').click();
  const response = await (await pending).json();
  expect(response.result.retarget.animation_rotation).toEqual({ pitch: -29.7, yaw: 45, roll: 0 });
  await expect(page.locator('#rotation-status')).toContainText('pitch -29.7°');
  await expect(page.locator('#edit-status')).toContainText('up to date');
  await page.screenshot({ path: info.outputPath('rotation-desktop.png') });
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.locator('#rotation-pitch')).toHaveValue('0');
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await expect(page.locator('#rotation-pitch')).toHaveValue('-29.7');
  await page.locator('[data-step="3"]').click();
  let download = page.waitForEvent('download');
  await page.locator('#export-character').click();
  const glbPath = info.outputPath('rotated.glb');
  await (await download).saveAs(glbPath);
  const glb = await fs.readFile(glbPath);
  const doc = JSON.parse(glb.subarray(20, 20 + glb.readUInt32LE(12)).toString());
  expect(doc.extras.homunculus.animation_rotation).toEqual({ pitch: -29.7, yaw: 45, roll: 0 });
  download = page.waitForEvent('download');
  await page.locator('#save-project').click();
  const projectPath = info.outputPath('rotated-project.json');
  await (await download).saveAs(projectPath);
  expect(JSON.parse(await fs.readFile(projectPath, 'utf8')).capture.animation_rotation).toEqual({
    pitch: -29.7,
    yaw: 45,
    roll: 0,
  });
  await page.locator('[data-step="2"]').click();
  await page.locator('#reset-rotation').click();
  await expect(page.locator('#rotation-pitch')).toHaveValue('0');
  await expect(page.locator('#rotation-status')).toContainText('yaw 0°');
  await page.locator('[data-step="0"]').click();
  await page.locator('#library-show-import').click();
  await page.locator('#project-file').setInputFiles(projectPath);
  await expect(page.locator('#rotation-pitch')).toHaveValue('-29.7');
  await expect(page.locator('#rotation-yaw')).toHaveValue('45');
  await page.locator('#rotation-pitch').fill('181');
  await page.locator('#apply-rotation').click();
  await expect(page.locator('#rotation-status')).toContainText('Enter an angle');
  await page.locator('[data-step="3"]').click();
  await expect(page.locator('#export-character')).toBeDisabled();
  expect(errors).toEqual([]);
});
