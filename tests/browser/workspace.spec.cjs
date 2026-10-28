const {test,expect}=require('@playwright/test');
const path=require('node:path');

async function command(page,name,args){
  await page.getByLabel('Command',{exact:true}).selectOption(name);
  await page.getByLabel('JSON arguments').fill(JSON.stringify(args));
  await page.getByRole('button',{name:'Run command',exact:true}).click();
  await expect(page.locator('#command-result')).toContainText('"command": "'+name+'"');
}

test('shared tools configure scenes, undo, reject invalid settings and attach captures',async({page})=>{
  await page.goto('/');await expect(page.getByRole('button',{name:'Simulate edit',exact:true})).toBeEnabled();
  await page.getByText('Command inspector - same tools as Muse',{exact:true}).click();
  await command(page,'set_scene',{background:'#112233',camera:'front',props:[{id:'marker',shape:'box',position:[.7,.15,0],scale:[.3,.3,.3],color:'#4488cc'}]});
  await expect(page.locator('#scene-background')).toHaveValue('#112233');
  await command(page,'undo',{});await expect(page.locator('#scene-background')).toHaveValue('#142024');
  await page.getByLabel('Command',{exact:true}).selectOption('set_settings');
  await page.getByLabel('JSON arguments').fill('{"edit":{"strength":99}}');
  await page.getByRole('button',{name:'Run command',exact:true}).click();
  await expect(page.locator('#command-result')).toContainText('outside supported range');
  await page.getByLabel('Attach images, video, capture or scene JSON').setInputFiles(path.resolve('outputs/browser-fixture.json'));
  await expect(page.locator('#chat-attachments')).toContainText('capture');
  await page.locator('#chat-attachments').getByRole('button',{name:'Use',exact:true}).click();
  await expect(page.getByRole('button',{name:'Optimize captured motion',exact:true})).toBeEnabled();
  await command(page,'adjust_pose',{keyId:'key-20',joint:'shoulder',axis:'y',degrees:5});
  await expect(page.locator('#command-result')).toContainText('Pose adjusted');
});

test('fixture Muse tool loop executes and sends receipts, without claiming live inference',async({page})=>{
  let calls=0;
  await page.route('**/api/chat',async route=>{
    const body=route.request().postDataJSON();calls++;
    if(calls===1)await route.fulfill({json:{model:'test-fixture',message:{role:'assistant',content:'',tool_calls:[{id:'fixture-1',type:'function',function:{name:'set_scene',arguments:'{"camera":"side"}'}}]}}});
    else{
      expect(body.messages.at(-1).tool_call_id).toBe('fixture-1');
      expect(JSON.parse(body.messages.at(-1).content).ok).toBe(true);
      await route.fulfill({json:{model:'test-fixture',message:{role:'assistant',content:'Fixture scene action completed.'}}});
    }
  });
  await page.goto('/');await expect(page.getByRole('button',{name:'Simulate edit',exact:true})).toBeEnabled();
  await page.getByLabel('Message Muse').fill('Show the side camera');
  await page.getByRole('button',{name:'Send to Muse',exact:true}).click();
  await expect(page.locator('#chat-log')).toContainText('Fixture scene action completed.');
  await expect(page.locator('#scene-camera')).toHaveValue('side');expect(calls).toBe(2);
});
