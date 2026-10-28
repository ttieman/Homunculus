// The application and Muse call the same validated command dispatcher.
const $=id=>document.getElementById(id);
export const defaultScene={background:'#142024',grid:true,light:2.1,camera:'home',props:[]};
export function createWorkspace(app) {
  let scene=structuredClone(defaultScene), undo=[], redo=[], revision=0, executing=false, chatting=false, stopped=false;
  const attachments=new Map(); let messages=[]; let nextId=1;
  const log=(role,text)=>{const item=document.createElement('div');item.className='chat-entry';const label=document.createElement('strong');label.textContent=role;const body=document.createElement('p');body.textContent=text;item.append(label,body);$('chat-log').append(item);item.scrollIntoView({block:'nearest'});};
  function syncScene(){app.configureScene(scene);$('scene-background').value=scene.background;$('scene-grid').checked=scene.grid;$('scene-light').value=scene.light;$('scene-camera').value=scene.camera;}
  function snapshot(){return {app:app.snapshot(),scene:structuredClone(scene)};}
  async function restore(value){await app.restore(value.app);scene=structuredClone(value.scene);syncScene();}
  function state(){return {...app.inspect(),scene:structuredClone(scene),revision,undo:undo.length,redo:redo.length,
    attachments:[...attachments.values()].map(({id,name,kind})=>({id,name,kind}))};}
  const handlers={...app.actions,
    inspect_workspace:async()=>state(),
    set_scene:async args=>{scene={...scene,...structuredClone(args)};syncScene();return {scene,physics:'Props are visual only; simulated collision uses the obstacle setting.'};},
    undo:async()=>{if(!undo.length)throw Error('Nothing to undo');const before=snapshot();await restore(undo.at(-1));undo.pop();redo.push(before);},
    redo:async()=>{if(!redo.length)throw Error('Nothing to redo');const before=snapshot();await restore(redo.at(-1));redo.pop();undo.push(before);},
    use_attachment:async({id})=>{const item=attachments.get(id);if(!item)throw Error('Unknown attachment ID');
      if(item.kind==='video'){await app.useVideo(item.file);return {status:'Local video preview selected; SAM inference has not run.'};}
      if(item.kind==='capture')return app.useCapture(item.data);
      if(item.kind==='scene'){
        const d=item.data;if(d.schema!=='homunculus.scene.v1')throw Error('Unsupported scene');
        await app.validate('set_scene',d.scene);await app.validate('set_settings',d.settings);
        await app.actions.set_settings(d.settings);scene={...structuredClone(defaultScene),...d.scene};syncScene();return {status:'Scene loaded'};
      }
      throw Error('Images are chat references, not captured poses. Run SAM and attach its capture JSON to drive motion.');},
    export_asset:async({format})=>{if(format==='scene'){app.download('homunculus-scene.json',{schema:'homunculus.scene.v1',scene,settings:app.inspect().settings});return {status:'Scene download requested'};}return app.actions.export_asset({format});}
  };
  async function perform(name,args={},source='manual') {
    if(executing||app.busy())throw Error('Another operation is still running');
    executing=true;let before;
    try{
      await app.validate(name,args);if(!handlers[name])throw Error('Command is not implemented');
      before=snapshot();const value=await handlers[name](args);
      if(!['inspect_workspace','playback','export_asset','undo','redo'].includes(name)){
        undo.push(before);if(undo.length>30)undo.shift();redo=[];
      }
      if(name!=='inspect_workspace')revision++;
      $('undo').disabled=!undo.length;$('redo').disabled=!redo.length;
      return {ok:true,command:name,source,result:value??{status:'Applied'},revision};
    }catch(error){throw error;}finally{executing=false;}
  }
  function manual(name,args={}){return perform(name,args).catch(e=>{$('message').textContent=e.message;throw e;});}
  function bind(id,name,args=()=>({})){$(id).onclick=()=>manual(name,args()).catch(()=>{});}
  bind('apply','set_settings',()=>({edit:app.fields()}));bind('optimize','optimize');bind('use-fixture','use_demo');
  bind('undo','undo');bind('redo','redo');bind('three-poses','assemble_three_poses');
  bind('play','playback',()=>({playing:!app.inspect().playback.playing}));bind('replay','playback',()=>({replay:!app.inspect().playback.replay}));
  for(const [id,format] of [['export','arm'],['export-character','character'],['save','session'],['save-reference','reference'],['save-scene','scene']])bind(id,'export_asset',()=>({format}));
  bind('apply-scene','set_scene',()=>({background:$('scene-background').value,grid:$('scene-grid').checked,light:Number($('scene-light').value),camera:$('scene-camera').value}));
  bind('add-prop','set_scene',()=>({props:[...scene.props,{id:'prop-'+nextId++,shape:$('prop-shape').value,position:[Number($('prop-x').value),Number($('prop-y').value),Number($('prop-z').value)],scale:[.3,.3,.3],color:'#d7945b'}]}));
  bind('clear-props','set_scene',()=>({props:[]}));
  $('timeline').oninput=()=>manual('playback',{time:Number($('timeline').value)*(app.inspect().settings.edit.duration)}).catch(()=>{});
  $('character-view').onchange=()=>manual('set_settings',{view:$('character-view').value}).catch(()=>{});
  $('show-physics').onchange=()=>manual('set_settings',{showPhysics:$('show-physics').checked}).catch(()=>{});
  // A control edited while a model request is in flight makes its proposed calls stale.
  for(const id of ['duration','shoulder_deg','elbow_deg','strength','damping','obstacle'])$(id).addEventListener('input',()=>revision++);
  async function attach(file) {
    if(attachments.size>=12)throw Error('Remove an attachment before adding more (limit 12).');
    let kind=file.type.startsWith('video/')||/\.(mkv|mp4|webm)$/i.test(file.name)?'video':file.type.startsWith('image/')?'image':'json';
    const limit=kind==='video'?100*1024*1024:kind==='image'?1400000:8*1024*1024;
    if(file.size>limit)throw Error(`${file.name}: file exceeds ${Math.round(limit/1024/1024*10)/10} MB limit`);
    const item={id:'media-'+nextId++,name:file.name,kind,file};
    if(kind==='json'){item.data=JSON.parse(await file.text());item.kind=item.data.schema==='homunculus.scene.v1'?'scene':'capture';
      if(item.kind==='capture')await app.validateCapture(item.data);
      else{await app.validate('set_scene',item.data.scene);await app.validate('set_settings',item.data.settings);}}
    if(kind==='image')item.dataURL=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
    attachments.set(item.id,item);revision++;renderAttachments();return item;
  }
  function renderAttachments(){
    $('chat-attachments').replaceChildren();
    for(const item of attachments.values()){
      const row=document.createElement('div');row.className='attachment';const label=document.createElement('span');label.textContent=`${item.id}: ${item.name} (${item.kind})`;row.append(label);
      if(item.kind==='image'){const img=document.createElement('img');img.src=item.dataURL;img.alt=item.name;img.width=70;row.append(img);}
      else{const use=document.createElement('button');use.textContent='Use';use.onclick=()=>manual('use_attachment',{id:item.id}).catch(()=>{});row.append(use);}
      const remove=document.createElement('button');remove.textContent='Remove';remove.onclick=()=>{attachments.delete(item.id);revision++;renderAttachments();};row.append(remove);$('chat-attachments').append(row);
    }
  }
  $('chat-files').onchange=async()=>{for(const file of $('chat-files').files){try{await attach(file);}catch(e){log('Attachment error',e.message);}}$('chat-files').value='';};
  $('chat-prompt').addEventListener('paste',async event=>{const files=[...event.clipboardData.files];if(files.length){event.preventDefault();for(const file of files){try{await attach(file);}catch(e){log('Attachment error',e.message);}}}});
  $('chat-panel').ondragover=e=>e.preventDefault();$('chat-panel').ondrop=async e=>{e.preventDefault();for(const file of e.dataTransfer.files){try{await attach(file);}catch(error){log('Attachment error',error.message);}}};
  $('chat-stop').onclick=()=>{stopped=true;log('Workspace','Stopping after the current request or action completes.');};
  $('chat-clear').onclick=()=>{if(chatting)return;messages=[];$('chat-log').replaceChildren();};
  fetch('/api/commands').then(r=>r.json()).then(({tools})=>{for(const tool of tools){const option=document.createElement('option');option.value=option.textContent=tool.function.name;$('command-name').append(option);}});
  fetch('/api/status').then(r=>r.json()).then(s=>{$('chat-status').textContent='Muse Spark: '+s.meta;}).catch(e=>{$('chat-status').textContent=e.message;});
  $('run-command').onclick=async()=>{try{const receipt=await manual($('command-name').value,JSON.parse($('command-arguments').value));$('command-result').textContent=JSON.stringify(receipt,null,2);}catch(e){$('command-result').textContent=JSON.stringify({ok:false,error:e.message},null,2);}};
  $('chat-send').onclick=async()=>{
    if(chatting||executing||app.busy())return;
    const text=$('chat-prompt').value.trim();if(!text)return;
    const images=[...attachments.values()].filter(a=>a.kind==='image');if(images.length>4){log('Workspace','Use at most four image references per message.');return;}
    chatting=true;stopped=false;$('chat-send').disabled=true;$('chat-stop').disabled=false;
    messages.push({role:'user',content:[{type:'text',text},...images.map(a=>({type:'image_url',image_url:{url:a.dataURL}}))]});
    $('chat-prompt').value='';log('You',text);
    try{
      for(let step=0;step<8;step++){
        if(stopped)break;const base=revision;
        const response=await app.chat({messages,state:state()});const message=response.message;
        messages.push(message);if(message.content)log('Muse',message.content);
        const calls=message.tool_calls||[];if(!calls.length)break;
        let blocked=stopped||base!==revision;
        for(const call of calls){
          let receipt;
          try{if(blocked||stopped)throw Error('Actions skipped because the workspace changed, a previous action failed, or Stop was pressed. Ask again.');
            receipt=await perform(call.function.name,JSON.parse(call.function.arguments),'Muse');
          }catch(e){blocked=true;receipt={ok:false,error:e.message};}
          messages.push({role:'tool',tool_call_id:call.id,content:JSON.stringify(receipt)});
          log(receipt.ok?'Tool completed':'Tool failed',call.function.name+': '+JSON.stringify(receipt.result||receipt.error));
        }
        if(blocked)break;
        if(step===7)log('Workspace','Reached the eight-step limit. Ask Muse to continue if needed.');
      }
    }catch(e){log('Muse error',e.message);}finally{chatting=false;$('chat-send').disabled=false;$('chat-stop').disabled=true;}
  };
  syncScene();
  return {perform,manual,attach,state};
}
