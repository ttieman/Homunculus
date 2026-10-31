const { test, expect } = require('@playwright/test');
test.use({
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
});
async function openCamera(page) {
  await page.goto('/');
  await expect(page.locator('#apply')).toBeEnabled();
  await page.getByRole('tab', { name: 'Capture' }).click();
  await expect(page.locator('#camera-status')).toContainText('Camera ready');
  await expect.poll(() => page.locator('#capture-live').evaluate(v => v.videoWidth)).toBeGreaterThan(0);
  await page.locator('#capture-countdown').selectOption('0');
}
const liveTracks = page =>
  page
    .locator('#capture-live')
    .evaluate(v => v.srcObject?.getTracks().filter(t => t.readyState === 'live').length ?? 0);

test('records a take, plays it back and converts it through the upload path', async ({ page }) => {
  const uploads = [];
  await page.route('**/api/jobs?*', route => {
    uploads.push(new URL(route.request().url()).searchParams.get('name'));
    return route.fulfill({ status: 503, json: { error: 'Worker unavailable. Try again.' } });
  });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await openCamera(page);
  expect(await page.locator('#capture-camera option').count()).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Record', exact: true }).click();
  await expect(page.locator('#camera-status')).toContainText('Recording');
  await page.waitForTimeout(2600);
  await page.getByRole('button', { name: 'Stop recording' }).click();
  await expect(page.locator('#camera-status')).toContainText('Recorded');
  await expect.poll(() => page.locator('#capture-playback').evaluate(v => v.readyState)).toBeGreaterThan(0);
  await expect(page.locator('#capture-use')).toBeInViewport();
  expect(uploads).toEqual([]);
  await page.getByRole('button', { name: 'Convert to animation' }).first().click();
  await expect(page.locator('#step-0')).toBeVisible();
  await expect(page.locator('#job-status')).toContainText('Worker unavailable');
  expect(uploads).toHaveLength(1);
  expect(uploads[0]).toMatch(/^capture-.*\.webm$/);
  await expect(page.locator('#process-submit')).toBeEnabled();
  expect(await liveTracks(page)).toBe(0);
  expect(errors).toEqual([]);
});

test('a take too short for the worker cannot be converted', async ({ page }) => {
  await openCamera(page);
  await page.getByRole('button', { name: 'Record', exact: true }).click();
  await page.waitForTimeout(500);
  await page.getByRole('button', { name: 'Stop recording' }).click();
  await expect(page.locator('#camera-status')).toContainText('at least 2.1 s');
  await expect(page.locator('#capture-use')).toBeDisabled();
  await page.getByRole('button', { name: 'Remove from session' }).click();
  await expect(page.locator('#capture-take')).toBeHidden();
});

test('collapsing the panel releases an idle camera but keeps a recording running', async ({ page }) => {
  await openCamera(page);
  await page.getByRole('tab', { name: 'Capture' }).click();
  await expect(page.locator('#capture-live')).toBeHidden();
  expect(await liveTracks(page)).toBe(0);
  await page.getByRole('tab', { name: 'Capture' }).click();
  await expect.poll(() => liveTracks(page)).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Record', exact: true }).click();
  await page.getByRole('tab', { name: 'Capture' }).click();
  expect(await liveTracks(page)).toBeGreaterThan(0);
  await expect(page.locator('body')).toHaveAttribute('data-recording', 'true');
  await page.waitForTimeout(2500);
  await page.getByRole('tab', { name: 'Capture' }).click();
  await page.getByRole('button', { name: 'Stop recording' }).click();
  await expect(page.locator('#camera-status')).toContainText('Recorded');
});

test('recording stops by itself at the 30 second limit', async ({ page }) => {
  await openCamera(page);
  await page.getByRole('button', { name: 'Record', exact: true }).click();
  await expect(page.locator('#camera-status')).toContainText('Recorded', { timeout: 35000 });
  await expect(page.locator('#capture-use')).toBeEnabled();
});

test('a session keeps several takes, saves them to the library and Space controls recording', async ({
  page,
}) => {
  await openCamera(page);
  await expect(page.locator('#capture-worker')).toContainText('GPU worker');
  await page.getByRole('tab', { name: 'Capture' }).focus();
  await page.keyboard.press('Space');
  await expect(page.locator('body')).toHaveAttribute('data-recording', 'true');
  await page.waitForTimeout(2600);
  await page.getByRole('button', { name: 'Stop recording' }).click();
  await expect(page.locator('.capture-take-row')).toContainText('in Library');
  await page.getByRole('button', { name: 'Record', exact: true }).click();
  await page.waitForTimeout(2600);
  await page.getByRole('button', { name: 'Stop recording' }).click();
  await expect(page.locator('.capture-take-row')).toHaveCount(2);
  await expect(page.locator('.capture-take-row').first()).toContainText('in Library');
  await expect(page.locator('.capture-take-row').first()).toContainText('Take 2');
  const listing = await (await page.request.get('/api/library')).json();
  expect(
    listing.items.filter(i => i.kind === 'recording' && /^capture-/.test(i.file)).length,
  ).toBeGreaterThanOrEqual(2);
  await page.getByRole('button', { name: 'Remove from session' }).click();
  await expect(page.locator('.capture-take-row')).toHaveCount(1);
});

test('a blocked camera explains how to fix it', async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw new DOMException('denied', 'NotAllowedError');
    };
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Capture' }).click();
  await page.getByRole('button', { name: 'Turn on camera' }).click();
  await expect(page.locator('#camera-status')).toContainText('Camera access was blocked');
  await expect(page.getByRole('button', { name: 'Turn on camera' })).toBeVisible();
});
