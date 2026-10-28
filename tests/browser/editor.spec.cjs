const {test,expect}=require('@playwright/test');
const path=require('node:path');
const fs=require('node:fs/promises');

async function importCapture(page, source=false){
  await page.goto('/');
  await expect(page.getByRole('button',{name:'Simulate edit',exact:true})).toBeEnabled();
  if(source)await page.getByLabel('Preview your video locally').setInputFiles(path.resolve('outputs/browser-fixture.webm'));
  await page.getByLabel('Import worker capture.json').setInputFiles(path.resolve('outputs/browser-fixture.json'));
  await expect(page.getByRole('button',{name:'Use captured motion',exact:true})).toBeDisabled();
  await page.getByLabel('I checked the overlay, person and axis mapping').check();
  await page.getByRole('button',{name:'Use captured motion',exact:true}).click();
  await expect(page.getByRole('button',{name:'Optimize captured motion',exact:true})).toBeEnabled();
}

test('reviewed import, source comparison, replay and timeline undo/redo',async({page})=>{
  await importCapture(page,true);
  await expect(page.locator('#sync-status')).toContainText('Matched source');
  await page.getByRole('button',{name:'Replay export',exact:true}).click();
  await expect(page.locator('#view-label')).toContainText('decoded animation buffers');
  await page.getByRole('button',{name:'Assemble three poses',exact:true}).click();
  await expect(page.locator('#capture-status')).toContainText('3 editable keyframes');
  await page.getByLabel('New keyframe time (seconds)').fill('1.8');
  await page.getByRole('button',{name:'Apply keyframe edit',exact:true}).click();
  await expect(page.getByRole('button',{name:'Undo',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'Undo',exact:true}).click();
  await expect(page.getByRole('button',{name:'Redo',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'Redo',exact:true}).click();
  await expect(page.getByRole('button',{name:'Simulate edit',exact:true})).toBeEnabled();
  await expect(page.locator('#sync-status')).toContainText('Matched source');
});

test('duration edits survive save and reimport',async({page},testInfo)=>{
  await importCapture(page);
  await page.locator('#duration').evaluate(el=>{el.value='6';el.dispatchEvent(new Event('input',{bubbles:true}));});
  await page.getByRole('button',{name:'Simulate edit',exact:true}).click();
  await expect(page.getByRole('button',{name:'Save reference',exact:true})).toBeEnabled();
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'Save reference',exact:true}).click();
  const file=testInfo.outputPath('reference.json');await (await downloadPromise).saveAs(file);
  expect(JSON.parse(await fs.readFile(file,'utf8')).reference_animation.keyframes.at(-1).time).toBe(6);
  await page.getByRole('button',{name:'Use demo reach',exact:true}).click();
  await expect(page.getByLabel('Import worker capture.json')).toBeEnabled();
  await page.getByLabel('Import worker capture.json').setInputFiles(file);
  await page.getByLabel('I checked the overlay, person and axis mapping').check();
  await page.getByRole('button',{name:'Use captured motion',exact:true}).click();
  await expect(page.locator('#time')).toContainText('/ 6.00 s');
});

test('mismatched source cannot apply the capture',async({page})=>{
  await page.goto('/');
  await expect(page.getByLabel('Import worker capture.json')).toBeEnabled();
  await page.getByLabel('Import worker capture.json').setInputFiles(path.resolve('outputs/browser-fixture.json'));
  await page.getByLabel('Preview your video locally').setInputFiles({name:'mismatch.webm',mimeType:'video/webm',buffer:Buffer.from('not the source')});
  await page.getByLabel('I checked the overlay, person and axis mapping').check();
  await page.getByRole('button',{name:'Use captured motion',exact:true}).click();
  await expect(page.locator('#capture-status')).toContainText('mismatch');
});
