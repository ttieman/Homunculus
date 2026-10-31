const { test, expect } = require('@playwright/test');
const path = require('node:path');
const fs = require('node:fs/promises');
async function loadBody(page) {
  await page.goto('/');
  await expect(page.locator('#apply')).toBeEnabled();
  await page.locator('[data-step="0"]').click();
  await page.locator('#library-show-import').click();
  await page.getByText('Open an existing capture', { exact: true }).click();
  await page.locator('#capture-file').setInputFiles(path.resolve('outputs/test-body-capture.json'));
  await page.locator('#review-capture').check();
  await page.locator('#use-capture').click();
  await expect(page.locator('#stage')).toHaveAttribute('data-driven-bones', '19');
  await page.getByRole('tab', { name: '03 Edit' }).click();
}
function glbJson(buffer) {
  return JSON.parse(buffer.subarray(20, 20 + buffer.readUInt32LE(12)).toString());
}
test('isolate a limb, export only its tracks, undo and reload the saved recipe', async ({ page }, info) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await loadBody(page);
  await page.locator('#target-preset').selectOption('Left arm');
  await page.getByRole('button', { name: 'Apply targets', exact: true }).click();
  await expect(page.locator('#stage')).toHaveAttribute('data-driven-bones', '4');
  await page.getByRole('tab', { name: '04 Export' }).click();
  let downloading = page.waitForEvent('download');
  await page.locator('#export-character').click();
  const glb = info.outputPath('arm-only.glb');
  await (await downloading).saveAs(glb);
  const doc = glbJson(await fs.readFile(glb));
  expect(doc.animations[0].channels.map(c => doc.nodes[c.target.node].name)).toEqual([
    'shoulder.L',
    'upper_arm.L',
    'forearm.L',
    'hand.L',
  ]);
  downloading = page.waitForEvent('download');
  await page.locator('#save-project').click();
  const project = info.outputPath('project.json');
  await (await downloading).saveAs(project);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.locator('#stage')).toHaveAttribute('data-driven-bones', '19');
  await page.getByRole('tab', { name: '01 Import' }).click();
  await page.locator('#project-file').setInputFiles(project);
  await expect(page.locator('#stage')).toHaveAttribute('data-driven-bones', '4');
  await expect(page.getByRole('tab', { name: '03 Edit' })).toHaveAttribute('aria-selected', 'true');
  expect(errors).toEqual([]);
});
test('layer and join a second clip through the UI with exact output duration', async ({ page }) => {
  await loadBody(page);
  const baseDuration = await page.locator('#duration').inputValue();
  await page.locator('#composition-file').setInputFiles(path.resolve('outputs/test-body-capture.json'));
  await expect(page.locator('#composition-status')).toContainText('Second clip attached');
  await page.locator('#target-preset').selectOption('Right leg');
  await page.locator('#composition-mode').selectOption('layer');
  await page.locator('#apply-composition').click();
  await expect(page.locator('#composition-status')).toContainText('layer: 3 joint tracks');
  await expect(page.locator('#time')).toContainText('/ ' + Number(baseDuration).toFixed(2) + ' s');
  await page.locator('#composition-mode').selectOption('sequence');
  await page.locator('#composition-blend').fill('0.5');
  await page.locator('#apply-composition').click();
  await expect(page.locator('#composition-status')).toContainText('sequence: 3 joint tracks');
  await expect(page.locator('#time')).toContainText(
    '/ ' + (2 * Number(baseDuration) - 0.5).toFixed(2) + ' s',
  );
});
test('Muse navigates and targets a limb through shared commands with receipts', async ({ page }) => {
  await loadBody(page);
  let calls = 0;
  await page.route('**/api/chat', async route => {
    const body = route.request().postDataJSON();
    calls++;
    if (calls === 1)
      await route.fulfill({
        json: {
          message: {
            role: 'assistant',
            content: null,
            tool_calls: [
              {
                id: 'nav',
                type: 'function',
                function: { name: 'navigate_stage', arguments: JSON.stringify({ stage: 'edit' }) },
              },
              {
                id: 'mask',
                type: 'function',
                function: {
                  name: 'compose_motion',
                  arguments: JSON.stringify({ mode: 'mask', bones: ['forearm.L'], rootMotion: false }),
                },
              },
              {
                id: 'export-view',
                type: 'function',
                function: { name: 'navigate_stage', arguments: JSON.stringify({ stage: 'export' }) },
              },
            ],
          },
        },
      });
    else {
      expect(body.state.stage).toBe('export');
      expect(body.state.composition.bones).toEqual(['forearm.L']);
      expect(body.messages.filter(m => m.role === 'tool').every(m => JSON.parse(m.content).ok)).toBe(true);
      await route.fulfill({
        json: {
          message: { role: 'assistant', content: 'The left forearm is isolated. Preview it in Export.' },
        },
      });
    }
  });
  await page.locator('#chat-prompt').fill('Isolate the left forearm and open Export.');
  await page.locator('#chat-send').click();
  await expect(page.locator('#chat-log')).toContainText('The left forearm is isolated.');
  await expect(page.getByRole('tab', { name: '04 Export' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#stage')).toHaveAttribute('data-driven-bones', '1');
  await expect(page.locator('#chat-prompt')).toBeVisible();
});
