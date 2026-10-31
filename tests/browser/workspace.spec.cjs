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

async function command(page, name, args) {
  await reveal(page, page.getByLabel('Command', { exact: true }));
  await page.getByLabel('Command', { exact: true }).selectOption(name);
  await reveal(page, page.getByLabel('JSON arguments'));
  await page.getByLabel('JSON arguments').fill(JSON.stringify(args));
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Run command', exact: true }));
  await page.getByRole('button', { includeHidden: true, name: 'Run command', exact: true }).click();
  await expect(page.locator('#command-result')).toContainText('"command": "' + name + '"');
}

test('shared tools configure scenes, undo, reject invalid settings and attach captures', async ({ page }) => {
  await page.goto('/');
  await expect(
    page.getByRole('button', { includeHidden: true, name: 'Apply changes', exact: true }),
  ).toBeEnabled();
  await reveal(page, page.getByText('Command inspector - same tools as Muse', { exact: true }));
  await page.getByText('Command inspector - same tools as Muse', { exact: true }).click();
  await command(page, 'set_scene', {
    background: '#112233',
    camera: 'front',
    props: [
      { id: 'marker', shape: 'box', position: [0.7, 0.15, 0], scale: [0.3, 0.3, 0.3], color: '#4488cc' },
    ],
  });
  await expect(page.locator('#scene-background')).toHaveValue('#112233');
  await command(page, 'undo', {});
  await expect(page.locator('#scene-background')).toHaveValue('#142024');
  await reveal(page, page.getByLabel('Command', { exact: true }));
  await page.getByLabel('Command', { exact: true }).selectOption('set_settings');
  await reveal(page, page.getByLabel('JSON arguments'));
  await page.getByLabel('JSON arguments').fill('{"edit":{"strength":99}}');
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Run command', exact: true }));
  await page.getByRole('button', { includeHidden: true, name: 'Run command', exact: true }).click();
  await expect(page.locator('#command-result')).toContainText('outside supported range');
  await reveal(page, page.getByLabel('Attach images, video, capture or scene JSON'));
  await page
    .getByLabel('Attach images, video, capture or scene JSON')
    .setInputFiles(path.resolve('outputs/browser-fixture.json'));
  await expect(page.locator('#chat-attachments')).toContainText('capture');
  await reveal(
    page,
    page.locator('#chat-attachments').getByRole('button', { includeHidden: true, name: 'Use', exact: true }),
  );
  await page
    .locator('#chat-attachments')
    .getByRole('button', { includeHidden: true, name: 'Use', exact: true })
    .click();
  await expect(
    page.getByRole('button', { includeHidden: true, name: 'Optimize captured motion', exact: true }),
  ).toBeEnabled();
  await command(page, 'adjust_pose', { keyId: 'key-20', joint: 'shoulder', axis: 'y', degrees: 5 });
  await expect(page.locator('#command-result')).toContainText('Pose adjusted');
});

test('fixture Muse tool loop executes and sends receipts, without claiming live inference', async ({
  page,
}) => {
  let calls = 0;
  await page.route('**/api/chat', async route => {
    const body = route.request().postDataJSON();
    calls++;
    if (calls === 1)
      await route.fulfill({
        json: {
          model: 'test-fixture',
          message: {
            role: 'assistant',
            content: '',
            tool_calls: [
              {
                id: 'fixture-1',
                type: 'function',
                function: { includeHidden: true, name: 'set_scene', arguments: '{"camera":"side"}' },
              },
            ],
          },
        },
      });
    else {
      expect(body.messages.at(-1).tool_call_id).toBe('fixture-1');
      expect(JSON.parse(body.messages.at(-1).content).ok).toBe(true);
      await route.fulfill({
        json: {
          model: 'test-fixture',
          message: { role: 'assistant', content: 'Fixture scene action completed.' },
        },
      });
    }
  });
  await page.goto('/');
  await expect(
    page.getByRole('button', { includeHidden: true, name: 'Apply changes', exact: true }),
  ).toBeEnabled();
  await reveal(page, page.getByLabel('Message Muse'));
  await page.getByLabel('Message Muse').fill('Show the side camera');
  await reveal(page, page.getByRole('button', { includeHidden: true, name: 'Send to Muse', exact: true }));
  await page.getByRole('button', { includeHidden: true, name: 'Send to Muse', exact: true }).click();
  await expect(page.locator('#chat-log')).toContainText('Fixture scene action completed.');
  await expect(page.locator('#scene-camera')).toHaveValue('side');
  expect(calls).toBe(2);
});
