const { test, expect } = require('@playwright/test');
test('conversion is explicit and a failed worker request can be retried', async ({ page }) => {
  let requests = 0;
  await page.route('**/api/jobs?*', route => {
    requests++;
    return route.fulfill({ status: 503, json: { error: 'Worker unavailable. Try again.' } });
  });
  await page.goto('/');
  await expect(page.locator('#apply')).toBeEnabled();
  await page.locator('[data-step="0"]').click();
  await page.locator('#library-show-import').click();
  await page
    .locator('#process-file')
    .setInputFiles({ name: 'fixture.webm', mimeType: 'video/webm', buffer: Buffer.from('fixture') });
  expect(requests).toBe(0);
  await page.getByRole('button', { name: 'Convert to animation' }).click();
  await expect(page.locator('#job-status')).toContainText('Worker unavailable');
  await expect(page.locator('#process-submit')).toBeEnabled();
  await expect(page.locator('#process-file')).toBeEnabled();
  await page.locator('#process-submit').click();
  await expect.poll(() => requests).toBe(2);
});
test('the local GPU toggle explains a missing install and stays on the remote worker', async ({ page }) => {
  let mode = 'remote';
  await page.route('**/api/worker', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { mode, reachable: false } });
    const want = route.request().postDataJSON().mode;
    if (want === 'local' && mode === 'remote' && !page.allowLocal)
      return route.fulfill({
        status: 400,
        json: { error: 'Local SAM is not installed yet. Missing: the SAM 3D Body checkpoint.' },
      });
    mode = want;
    return route.fulfill({ json: { mode, reachable: true, gpu_free_mib: 5000, gpu_needed_mib: 5930 } });
  });
  await page.goto('/');
  await page.locator('[data-step="0"]').click();
  await page.locator('#library-show-import').click();
  await expect(page.locator('#sam-status')).toContainText('not reachable');
  await page.getByLabel("Use this PC's GPU").click();
  await expect(page.locator('#sam-status')).toContainText('Missing: the SAM 3D Body checkpoint');
  await expect(page.getByLabel("Use this PC's GPU")).not.toBeChecked();
  page.allowLocal = true;
  await page.getByLabel("Use this PC's GPU").click();
  await expect(page.locator('#sam-status')).toContainText('close other GPU programs');
  await expect(page.getByLabel("Use this PC's GPU")).toBeChecked();
});
test('unapplied duration blocks export until preview is updated', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#apply')).toBeEnabled();
  await page.locator('[data-step="2"]').click();
  await page.locator('#duration').fill('6');
  await expect(page.locator('#edit-status')).toContainText('unapplied');
  await page.getByRole('button', { name: 'Continue to export' }).click();
  await expect(page.locator('#export-character')).toBeDisabled();
  await expect(page.locator('#export-status')).toContainText('Apply your changes');
  await page.locator('[data-step="2"]').click();
  await page.getByRole('button', { name: 'Apply changes', exact: true }).click();
  await expect(page.locator('#time')).toContainText('/ 6.00 s');
  await page.locator('[data-step="3"]').click();
  await expect(page.locator('#export-character')).toBeEnabled();
});
test('guided steps remain usable without horizontal overflow', async ({ page }, info) => {
  await page.goto('/');
  await expect(page.locator('#apply')).toBeEnabled();
  for (const width of [320, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    for (let step = 0; step < 4; step++) {
      await page.locator(`[data-step="${step}"]`).click();
      await expect(page.locator(`#step-${step}`)).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  }
  await page.locator('[data-step="2"]').click();
  await page.screenshot({ path: info.outputPath('guided-editor-desktop.png'), fullPage: true });
});
test('the 3D viewport is the full-window base layer under collapsible menus and chat', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#stage')).toHaveAttribute('data-renderer', 'webgl');
  await expect(page.locator('canvas')).toHaveCount(1);
  for (const width of [320, 768, 1365]) {
    await page.setViewportSize({ width, height: 800 });
    expect(await page.locator('#stage').boundingBox()).toEqual({ x: 0, y: 0, width, height: 800 });
    for (let step = 0; step < 4; step++) {
      await page.locator(`[data-step="${step}"]`).click();
      await expect(page.locator(`#step-${step}`)).toBeVisible();
      expect(await page.locator('#stage').boundingBox()).toEqual({ x: 0, y: 0, width, height: 800 });
      await page.locator(`[data-step="${step}"]`).click();
      await expect(page.locator(`#step-${step}`)).toBeHidden();
    }
  }
  await page.setViewportSize({ width: 1365, height: 800 });
  await page.locator('[data-step="1"]').click();
  await page.getByRole('button', { name: 'Collapse menu' }).click();
  await expect(page.locator('#step-1')).toBeHidden();
  if (await page.locator('#chat-panel').isHidden())
    await page.getByRole('button', { name: 'Open Muse chat' }).click();
  await page.getByRole('button', { name: 'Collapse chat' }).click();
  await expect(page.locator('#chat-panel')).toBeHidden();
  await page.getByRole('button', { name: 'Open Muse chat' }).click();
  await expect(page.locator('#chat-prompt')).toBeFocused();
});
test('shrinking the window with a menu and chat open keeps the menu uncovered', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-step="0"]').click();
  await expect(page.locator('#chat-panel')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 800 });
  await expect(page.locator('#chat-panel')).toBeHidden();
  await expect(page.locator('#step-0')).toBeVisible();
});
