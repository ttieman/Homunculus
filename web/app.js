import {createStage} from './stage3d.js';
import {createWorkspace} from './workspace.js';
const $=id=>document.getElementById(id);
const names=['duration','shoulder_deg','elbow_deg','strength','damping'];
let current=null, result=null, gltf=null, characterGlb=null, history=[], redoHistory=[], audit=[], proposal=null, busy=false;
let activeCapture=null, pendingCapture=null, videoHash=null, videoURL=null, hashingVideo=false;
let maxDocumentBytes=0;
fetch('/api/contracts').then(r=>r.json()).then(c=>{maxDocumentBytes=c.max_document_bytes;});
let playing=true, cursor=0, exported=false, replayFrames=null, previous=performance.now();
function fields(){return Object.fromEntries([...names.map(n=>[n,Number($(n).value)]),['obstacle',$('obstacle').checked]]);}
function labels(){for(const n of names)$(n+'-value').textContent=$(n).value+(n==='duration'?' s':n.endsWith('_deg')?'°':'×');}
function fill(e){for(const n of names)$(n).value=e[n];$('obstacle').checked=e.obstacle;labels();}
for(const n of names)$(n).oninput=labels;
labels();
async function api(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const j=await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j;}
function lock(value){busy=value;for(const id of ['apply','undo','redo','propose','accept','use-fixture','capture-file','video-file','process-file'])$(id).disabled=value; $('undo').disabled=value||!history.length; $('redo').disabled=value||!redoHistory.length; for(const id of ['optimize','three-poses','save-reference','edit-key'])$(id).disabled=value||activeCapture?.retargeting!=='spatial_arm_v1'; $('propose').disabled=value||(!!activeCapture&&activeCapture.retargeting!=='spatial_arm_v1');$('video-file').disabled=value||hashingVideo;$('use-capture').disabled=value||hashingVideo||!pendingCapture||!$('review-capture').checked;}
async function simulate(edit,source='manual',remember=true,capture=activeCapture,optimize=false){
  if(busy)return;lock(true);$('message').textContent='Simulating physical response…';
  try{const view=$('character-view').value;const payload=await api(optimize?'/api/synthesize':'/api/simulate',{edit,capture,physics_arm:$('physics-arm').checked,...(view==='auto'?{}:{view})});if(remember)redoHistory=[];if(remember&&current)history.push(structuredClone({edit:current,capture:activeCapture}));
    edit=payload.result.edit;current=edit;activeCapture=capture;showSegments();result=payload.result;gltf=payload.gltf;characterGlb=payload.character_glb||null;cursor=0;exported=false;replayFrames=null;stage?.setReplayClip(null);$('export-character').disabled=!characterGlb;proposal=null;$('accept').hidden=true;$('proposal').textContent='';
    $('shoulder_deg').disabled=!!capture;$('elbow_deg').disabled=!!capture;
    $('source-note').textContent=capture?'Imported '+capture.provenance.kind+' arm motion · Fixed shoulder · Recorded angles own the pose; duration, strength and damping remain editable. Muse can edit timing and bounded joint-local pose corrections; full-body poses and forces are not supported.':'Original procedural reference · MuJoCo torque control · Fixed shoulder. Arm-to-character retargeting is available; full-body balance is not included.';
    audit.push({source,edit:structuredClone(edit),at:new Date().toISOString()});fill(edit);
    $('error').textContent=result.metrics.tracking_rmse_deg.toFixed(2)+'°';$('contact').textContent=result.metrics.contact_steps;
    $('speed').textContent=Math.round(result.metrics.simulation_wall_s*1000)+' ms';
    $('message').textContent=(result.feasibility&&!result.feasibility.passed?'Feasibility limits exceeded. ':'Result ready. ')+'Peak penetration '+(result.metrics.max_penetration_m*1000).toFixed(2)+' mm. Export contains the actual simulated motion.';
    $('view-label').textContent='Physical result · fixed shoulder';$('replay').textContent='Replay export';return true;
  }catch(e){$('message').textContent=e.message;return false;}finally{lock(false);}
}
async function editReference(three=false,save=false){
  if(busy||!activeCapture)return;lock(true);
  try{let payload=await api('/api/reference',{capture:activeCapture,three_poses:three,duration:current.duration});
    if(!three&&!save){const key=payload.reference.keyframes[Number($('key-index').value)-1];if(!key)throw Error('Keyframe number is outside this timeline');
      payload=await api('/api/reference',{capture:payload.capture,commands:[{operation:'move_keyframe',targetId:key.id,parameters:{time:Number($('key-time').value)}},{operation:'set_interpolation',targetId:key.id,parameters:{interpolation:$('key-curve').value}}]});}
    if(save){download('homunculus-reference.json',payload.capture);return;}
    lock(false);await simulate({...fields(),duration:payload.reference.keyframes.at(-1).time},'timeline edit',true,payload.capture);
    $('capture-status').textContent=payload.reference.keyframes.length+' editable keyframes. Save reference to retain this timeline.';
  }catch(e){$('message').textContent=e.message;}finally{lock(false);}
}
$('three-poses').onclick=()=>editReference(true);$('save-reference').onclick=()=>editReference(false,true);$('edit-key').onclick=()=>editReference();
$('apply').onclick=()=>simulate(fields());
$('optimize').onclick=()=>simulate(fields(),'bounded controller optimization',true,activeCapture,true);
$('undo').onclick=async()=>{const e=history.at(-1),before=structuredClone({edit:current,capture:activeCapture});if(e&&await simulate(e.edit,'undo',false,e.capture)){history.pop();redoHistory.push(before);lock(false);}};
$('redo').onclick=async()=>{const e=redoHistory.at(-1),before=structuredClone({edit:current,capture:activeCapture});if(e&&await simulate(e.edit,'redo',false,e.capture)){redoHistory.pop();history.push(before);lock(false);}};
$('propose').onclick=async()=>{if(busy)return;lock(true);$('meta-status').textContent='Asking Muse Spark…';proposal=null;$('accept').hidden=true;$('proposal').textContent='';
  try{proposal=await api('/api/propose',{edit:fields(),capture:activeCapture,prompt:$('prompt').value});proposal.captureBase=JSON.stringify(activeCapture);$('proposal').textContent=JSON.stringify(proposal.commands||proposal.edit,null,2);$('accept').hidden=false;$('meta-status').textContent='Live '+proposal.provenance.model+' proposal. Review before applying.';}
  catch(e){$('meta-status').textContent=e.message;}finally{lock(false);}};
$('accept').onclick=()=>{if(!proposal)return;if(JSON.stringify(fields())!==JSON.stringify(proposal.base)||JSON.stringify(activeCapture)!==proposal.captureBase){$('meta-status').textContent='Controls changed since this proposal. Ask again before applying.';return;}simulate(proposal.edit,proposal.provenance,true,proposal.capture||activeCapture);};
function download(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('export').onclick=()=>gltf&&download('force-puppet-reach.gltf',gltf);
function glbBytes(b64){return Uint8Array.from(atob(b64),c=>c.charCodeAt(0));}
$('export-character').onclick=()=>{if(!characterGlb)return;const url=URL.createObjectURL(new Blob([glbBytes(characterGlb)],{type:'model/gltf-binary'}));const a=document.createElement('a');a.href=url;a.download='homunculus-'+(result.retarget?.character||'character').replace(/\.glb$/i,'')+'.glb';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('save').onclick=()=>result&&download('force-puppet-session.json',{edit:current,capture:activeCapture,audit,result,gltf});
function reviewReady(){lock(busy);}
$('review-capture').onchange=reviewReady;
async function loadVideo(f){if(!f)return;
  if(f.size>100*1024*1024){$('capture-status').textContent='Choose a video under 100 MB.';return;}
  if(videoURL)URL.revokeObjectURL(videoURL);videoURL=URL.createObjectURL(f);$('source-video').src=videoURL;$('source-video').hidden=false;$('source-pane').hidden=false;$('comparison').classList.add('has-video');document.body.classList.add('comparison-active');
  videoHash=null;hashingVideo=true;$('review-capture').checked=false;reviewReady();
  try{videoHash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await f.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('');
    $('capture-status').textContent=pendingCapture&&pendingCapture.provenance.video_sha256!==videoHash?'Video does not match imported capture. Select the original video.':'Local video ready. Process it with the worker and import capture.json.';
  }catch(e){$('capture-status').textContent=e.message;}finally{hashingVideo=false;reviewReady();}
};
$('video-file').onchange=()=>loadVideo($('video-file').files[0]);
$('capture-file').onchange=async()=>{const f=$('capture-file').files[0];pendingCapture=null;$('review-capture').checked=false;reviewReady();if(!f)return;
  try{if(!maxDocumentBytes)throw Error('Document limits are loading; select the file again.');if(f.size>maxDocumentBytes)throw Error('Capture exceeds the '+maxDocumentBytes+' byte document limit.');const candidate=JSON.parse(await f.text());const checked=await api('/api/capture/validate',{capture:candidate});
    pendingCapture=candidate;const dimensionality=candidate.retargeting==='spatial_arm_v1'?'3D arm':checked.metadata.max_out_of_plane_deg.toFixed(1)+' degrees out of plane';$('capture-status').textContent=candidate.provenance.kind+' / '+checked.metadata.source_duration_s.toFixed(2)+' s / '+dimensionality+' / '+checked.metadata.missing_frames+' missing frames'+(checked.body_keypoints?' / full body ('+checked.body_keypoints+' keypoints)':'')+'. Inspect overlays and confirm the mapping.';
  }catch(e){$('capture-status').textContent=e.message;}finally{reviewReady();}
};
$('use-capture').onclick=async()=>{if(!pendingCapture||!$('review-capture').checked||hashingVideo)return;
  if(videoURL&&!videoHash){$('capture-status').textContent='Video hash could not be verified. Reload and reselect the source video.';return;}
  if(videoHash&&pendingCapture.provenance.video_sha256!==videoHash){$('capture-status').textContent='Video hash mismatch. Capture must belong to the selected source video.';return;}
  const frames=pendingCapture.frames;const duration=pendingCapture.reference_animation?.keyframes.at(-1).time??(frames.at(-1).t-frames[0].t);
  await simulate({...fields(),duration:duration,obstacle:false},'imported capture',true,pendingCapture);
};
$('character-view').onchange=()=>{if(current&&!busy)simulate(current,'recording view',false,activeCapture);};
$('physics-arm').onchange=()=>{if(current&&!busy)simulate(current,'physics arm toggle',false,activeCapture);};
$('use-fixture').onclick=()=>simulate(fields(),'procedural fixture',true,null);
function readAccessor(doc,index,width){const a=doc.accessors[index],v=doc.bufferViews[a.bufferView];const bytes=Uint8Array.from(atob(doc.buffers[v.buffer].uri.split(',')[1]),c=>c.charCodeAt(0));const view=new DataView(bytes.buffer);return Array.from({length:a.count},(_,i)=>Array.from({length:width},(_,j)=>view.getFloat32((v.byteOffset||0)+(a.byteOffset||0)+(i*width+j)*4,true)));}
$('replay').onclick=async()=>{if(!gltf)return;exported=!exported;if(exported){const samplers=gltf.animations[0].samplers;const tracks=samplers.map(s=>readAccessor(gltf,s.output,4));const times=readAccessor(gltf,samplers[0].input,1);replayFrames=times.map((t,i)=>({t:t[0],rotations:tracks.map(track=>track[i]),q:tracks.map(track=>2*Math.atan2(track[i][2],track[i][3])),...quaternionArm(tracks.map(track=>track[i]))}));}
  try{await stage?.setReplayClip(exported&&characterGlb?glbBytes(characterGlb).buffer:null);}catch(e){exported=false;throw e;}
  $('view-label').textContent=exported?'glTF replay · decoded animation buffers'+(characterGlb?' (arm + character clip)':''):'Physical result · fixed shoulder';$('replay').textContent=exported?'Back to simulation':'Replay export';};
$('play').onclick=()=>{playing=!playing;$('play').textContent=playing?'Pause':'Play';$('play').setAttribute('aria-label',playing?'Pause playback':'Play playback');};
$('timeline').oninput=()=>{if(current)cursor=Number($('timeline').value)*current.duration;};
function slerp(a,b,u){let dot=a.reduce((v,x,i)=>v+x*b[i],0);if(dot<0){b=b.map(x=>-x);dot=-dot;}let q;if(dot>.9995){q=a.map((x,i)=>(1-u)*x+u*b[i]);}else{const angle=Math.acos(Math.min(1,dot));q=a.map((x,i)=>(Math.sin((1-u)*angle)*x+Math.sin(u*angle)*b[i])/Math.sin(angle));}const n=Math.hypot(...q);return q.map(x=>x/n);}
function rigFrames(frames,t){let lo=0,hi=frames.length-1;while(lo+1<hi){const mid=(lo+hi)>>1;if(frames[mid].t<=t)lo=mid;else hi=mid;}const a=frames[lo],b=frames[hi];return [a,b,t>=b.t?1:Math.max(0,(t-a.t)/(b.t-a.t))];}
function sampleRig(frames,t){const [a,b,u]=rigFrames(frames,t);return a.rotations_xyzw.map((q,i)=>slerp(q,b.rotations_xyzw[i],u));}
function sampleTranslation(frames,t){const [a,b,u]=rigFrames(frames,t);return a.translation?a.translation.map((x,i)=>x+(b.translation[i]-x)*u):null;}
function sampleFrames(frames,t){let lo=0,hi=frames.length-1;while(lo+1<hi){const mid=(lo+hi)>>1;if(frames[mid].t<=t)lo=mid;else hi=mid;}if(t>=frames.at(-1).t)return frames.at(-1);const a=frames[lo],b=frames[hi],u=Math.max(0,(t-a.t)/(b.t-a.t));const out={...a};for(const k of ['q','target','elbow','hand','target_elbow','target_hand'])if(a[k])out[k]=a[k].map((x,i)=>x+(b[k][i]-x)*u);if(a.rotations){out.rotations=a.rotations.map((q,i)=>slerp(q,b.rotations[i],u));Object.assign(out,quaternionArm(out.rotations));out.q=out.rotations.map(q=>2*Math.atan2(q[2],q[3]));}return out;}
function rotate(q,v){const [x,y,z,w]=q;const t=[2*(y*v[2]-z*v[1]),2*(z*v[0]-x*v[2]),2*(x*v[1]-y*v[0])];return [v[0]+w*t[0]+y*t[2]-z*t[1],v[1]+w*t[1]+z*t[0]-x*t[2],v[2]+w*t[2]+x*t[1]-y*t[0]];}
function quaternionArm(q){const a=rotate(q[0],[.34,0,0]);const b=rotate(q[0],rotate(q[1],[.29,0,0]));return {elbow:[a[0],1.4+a[1],a[2]],hand:[a[0]+b[0],1.4+a[1]+b[1],a[2]+b[2]]};}
// Planar results carry joint angles only; place them in the Z=0 plane of the 3D world.
function planarArm(q){const elbow=[.34*Math.cos(q[0]),1.4+.34*Math.sin(q[0]),0];return {elbow,hand:[elbow[0]+.29*Math.cos(q[0]+q[1]),elbow[1]+.29*Math.sin(q[0]+q[1]),0]};}
function armPoints(f){return f.elbow&&f.hand?{elbow:f.elbow,hand:f.hand}:planarArm(f.q);}
function targetPoints(f){return f.target_elbow&&f.target_hand?{elbow:f.target_elbow,hand:f.target_hand}:planarArm(f.target);}
let stage=null,pathSource=null;
try{stage=createStage($('stage'));}catch(e){$('view-label').textContent=e.message;}
function syncPath(){const frames=exported?replayFrames:result?.frames;if(!stage||frames===pathSource)return;pathSource=frames;stage.setPath(frames?.map(f=>armPoints(f).hand),exported);}

function draw(now){const dt=Math.min((now-previous)/1000,.1);previous=now;if(result&&playing)cursor=(cursor+dt)%current.duration;
  let state={obstacle:current?.obstacle??$('obstacle').checked,actual:null,target:null};
  if(result){const frames=exported?replayFrames:result.frames;const f=sampleFrames(frames,cursor);const original=sampleFrames(result.frames,cursor);
    if(videoURL){
      const video=$('source-video');let sourceTime=null;
      if(activeCapture&&videoHash===activeCapture.provenance.video_sha256){
        const keys=activeCapture.reference_animation?.keyframes;
        if(keys&&keys.every(k=>Number.isFinite(k.sourceTime))){
          const time=cursor/current.duration*keys.at(-1).time;let i=0;while(i<keys.length-2&&keys[i+1].time<=time)i++;
          let u=Math.max(0,Math.min(1,(time-keys[i].time)/(keys[i+1].time-keys[i].time)));
          if(keys[i].interpolation==='smoothstep')u=u*u*(3-2*u);if(keys[i].interpolation==='hold')u=0;
          sourceTime=activeCapture.frames[0].t+keys[i].sourceTime+(keys[i+1].sourceTime-keys[i].sourceTime)*u;
        }else if(!keys){sourceTime=activeCapture.frames[0].t+cursor/current.duration*(activeCapture.frames.at(-1).t-activeCapture.frames[0].t);}
      }
      if(sourceTime!==null&&video.readyState>=1){
        if(!video.seeking&&Math.abs(video.currentTime-sourceTime)>.025)video.currentTime=sourceTime;
        $('sync-status').textContent='Matched source '+video.currentTime.toFixed(2)+' s / animation '+cursor.toFixed(2)+' s'+(video.seeking?' / seeking':'');
      }else{$('sync-status').textContent=video.error?'Source video cannot be decoded; use a browser-compatible recording':video.readyState<1?'Loading source video':hashingVideo?'Checking source hash':!activeCapture?'Apply a captured animation':videoHash!==activeCapture.provenance.video_sha256?'Source mismatch: playback is not synchronized':'No source time map: playback is not synchronized';}
    }
    state={obstacle:!!current.obstacle,actual:armPoints(f),target:targetPoints(original),replay:exported,contact:!exported&&!!original.contacts,
      label:exported?'EXPORTED MOTION':original.contacts?'CONTACT':'REACH',
      showPhysics:$('show-physics').checked,character:result.retarget?{side:result.retarget.side,toPuppet:result.retarget.character_to_puppet,rotations:sampleRig(result.retarget.frames,cursor),
        bones:result.retarget.mode==='body'?result.retarget.bones:null,translationBone:result.retarget.translation_bone||null,translation:sampleTranslation(result.retarget.frames,cursor),replayTime:exported?cursor:null}:null};
    $('timeline').value=cursor/current.duration;$('time').textContent=cursor.toFixed(2)+' / '+current.duration.toFixed(2)+' s';
  }
  if(stage){syncPath();stage.render(state);}
  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);
fetch('/api/status').then(r=>r.json()).then(s=>{$('meta-status').textContent='Muse Spark · '+s.meta;
  if(s.character&&stage){$('export-character').hidden=false;$('physics-toggle').hidden=false;$('view-toggle').hidden=false;stage.loadCharacter('/character.glb').then(()=>{$('character-note').textContent='Character: '+s.character.source+' · captures with body keypoints drive the whole skeleton (tick Drive arm from physics to use the simulated arm), others drive one arm; its own proportions are kept (tick Show physics arm to compare).';}).catch(e=>{$('character-note').textContent='Character failed to load: '+e.message;});}}).catch(e=>{$('meta-status').textContent=e.message;});
const initialRun=simulate(fields(),'initial procedural fixture',false);

// Manual buttons and Muse use this same action surface. No eval or DOM automation.
const originalReplay=$('replay').onclick, originalCharacterExport=$('export-character').onclick;
let appliedView=$('character-view').value, appliedPhysics=$('show-physics').checked;
async function segmentCommand(operation){
  if(activeCapture?.retargeting!=='spatial_arm_v1')throw Error('Load a spatial capture first');
  const payload=await api('/api/segments',{capture:activeCapture,operation});await requireSimulation(current,payload.capture);showSegments();
  return {segments:payload.segments,physicsArm:$('physics-arm').checked};
}
function showSegments(){const list=activeCapture?.timing?.segments||[];
  $('segment-list').textContent=list.length?list.map(s=>s.id+': '+s.start.toFixed(2)+'–'+s.end.toFixed(2)+' s'+('strength' in s?' · strength '+s.strength:'')+('damping' in s?' · damping '+s.damping:'')+(s.blend?' · blend '+s.blend+' s '+s.curve:'')).join(String.fromCharCode(10)):'No segments.';}
async function requireSimulation(edit=current,capture=activeCapture,optimize=false){
  if(!await simulate(edit,'workspace command',false,capture,optimize))throw Error($('message').textContent);
  appliedView=$('character-view').value;appliedPhysics=$('show-physics').checked;
}
async function timelineCommand(commands=null,three=false){
  if(activeCapture?.retargeting!=='spatial_arm_v1')throw Error('A spatial capture is required');
  const payload=await api('/api/reference',{capture:activeCapture,duration:current.duration,three_poses:three,...(commands?{commands}:{})});
  await requireSimulation({...current,duration:payload.reference.keyframes.at(-1).time},payload.capture);
  $('capture-status').textContent=payload.reference.keyframes.length+' editable keyframes. Save reference to retain this timeline.';
  return {keyframes:payload.reference.keyframes.length,duration:current.duration};
}
function inspect(){return {settings:{edit:current||fields(),view:appliedView,showPhysics:appliedPhysics},
  playback:{playing,time:cursor,replay:exported},characterLoaded:!!stage?.hasCharacter,
  capture:activeCapture?{kind:activeCapture.provenance.kind,retargeting:activeCapture.retargeting}:null,
  keyframes:activeCapture?.reference_animation?.keyframes?.map(k=>({id:k.id,time:k.time,interpolation:k.interpolation}))||[],
  segments:activeCapture?.timing?.segments||[],sourceDuration:activeCapture?activeCapture.frames.at(-1).t-activeCapture.frames[0].t:null,physicsArm:$('physics-arm').checked,
  metrics:result?.metrics||null,limits:'Supported arm only; other body joints remain at rest. Decorative scene props have no collision.'};}
const workspace=createWorkspace({
  inspect,fields,download,busy:()=>busy,
  configureScene:settings=>stage?.configure(settings),
  validate:(name,args)=>api('/api/commands/validate',{name,arguments:args}),
  validateCapture:capture=>api('/api/capture/validate',{capture}),
  chat:body=>api('/api/chat',body),
  snapshot:()=>structuredClone({edit:current||fields(),capture:activeCapture,view:appliedView,showPhysics:appliedPhysics,playing,time:cursor}),
  restore:async value=>{$('character-view').value=value.view;await requireSimulation(value.edit,value.capture);$('show-physics').checked=appliedPhysics=value.showPhysics;playing=value.playing;cursor=value.time;},
  useVideo:loadVideo,
  useCapture:async capture=>{
    await api('/api/capture/validate',{capture});
    if(hashingVideo)throw Error('Wait for source video hashing');
    if(videoHash&&capture.provenance.video_sha256!==videoHash)throw Error('Source video mismatch: capture does not match the selected video');
    const frames=capture.frames,duration=capture.reference_animation?.keyframes.at(-1).time??frames.at(-1).t-frames[0].t;
    if(capture.retargeting==='spatial_arm_v1')capture=(await api('/api/reference',{capture,duration})).capture;
    await requireSimulation({...fields(),duration,obstacle:false},capture);return {status:'Captured motion applied',duration};
  },
  actions:{
    set_settings:async args=>{
      const oldView=appliedView;
      if(activeCapture&&args.edit&&['shoulder_deg','elbow_deg'].some(k=>k in args.edit&&args.edit[k]!==current[k]))throw Error('Captured poses own these angles; use adjust_pose instead');
      if(args.view)$('character-view').value=args.view;
      try{if(args.edit||args.view)await requireSimulation({...current,...args.edit});}catch(e){$('character-view').value=oldView;throw e;}
      if(args.showPhysics!==undefined)$('show-physics').checked=appliedPhysics=args.showPhysics;
      return inspect().settings;
    },
    playback:async args=>{
      if(args.time!==undefined&&args.time>current.duration)throw Error('Seek exceeds animation duration');
      if(args.replay!==undefined&&args.replay!==exported){if(!gltf)throw Error('No export is available');await originalReplay();}
      if(args.playing!==undefined)playing=args.playing;if(args.time!==undefined)cursor=args.time;
      $('play').textContent=playing?'Pause':'Play';$('play').setAttribute('aria-label',playing?'Pause playback':'Play playback');return inspect().playback;
    },
    simulate:()=>requireSimulation(),optimize:()=>requireSimulation(current,activeCapture,true),
    use_demo:()=>requireSimulation(fields(),null),
    edit_timeline:args=>timelineCommand(args.commands),assemble_three_poses:()=>timelineCommand(null,true),
    export_asset:async({format})=>{
      if(!result)throw Error('No result available');
      if(format==='arm')download('homunculus-arm.gltf',gltf);
      if(format==='character'){if(!characterGlb)throw Error('No character export available');originalCharacterExport();}
      if(format==='session')download('homunculus-session.json',{edit:current,capture:activeCapture,audit,result,gltf});
      if(format==='reference'){if(!activeCapture)throw Error('No captured reference');const p=await api('/api/reference',{capture:activeCapture,duration:fields().duration});download('homunculus-reference.json',p.capture);}
      return {status:'Download requested',format};
    },
    set_segment:async args=>segmentCommand({operation:'set',segment:args}),
    clear_segments:async({ids})=>segmentCommand({operation:'clear',...(ids?{ids}:{})}),
    adjust_pose:async args=>{if(!activeCapture)throw Error('Load a spatial capture first');const payload=await api('/api/pose',{capture:activeCapture,...args});await requireSimulation(current,payload.capture);return {status:'Pose adjusted',keyId:args.keyId};}
  }
});
$('edit-key').onclick=async()=>{try{const k=activeCapture?.reference_animation?.keyframes[Number($('key-index').value)-1];if(!k)throw Error('Invalid key number');await workspace.manual('edit_timeline',{commands:[{operation:'move_keyframe',targetId:k.id,parameters:{time:Number($('key-time').value)}},{operation:'set_interpolation',targetId:k.id,parameters:{interpolation:$('key-curve').value}}]});}catch(e){$('message').textContent=e.message;}};
$('segment-apply').onclick=async()=>{try{const args={id:$('segment-id').value.trim()||'seg-'+((activeCapture?.timing?.segments.length||0)+1),start:Number($('segment-start').value),end:Number($('segment-end').value),blend:Number($('segment-blend').value),curve:$('segment-curve').value};
  for(const k of ['strength','damping'])if($('segment-'+k).value!=='')args[k]=Number($('segment-'+k).value);
  await workspace.manual('set_segment',args);}catch(e){$('message').textContent=e.message;}};
$('segment-clear').onclick=async()=>{try{await workspace.manual('clear_segments',{});}catch(e){$('message').textContent=e.message;}};
$('adjust-pose').onclick=async()=>{try{const k=activeCapture?.reference_animation?.keyframes[Number($('key-index').value)-1];if(!k)throw Error('Invalid key number');await workspace.manual('adjust_pose',{keyId:k.id,joint:$('pose-joint').value,axis:$('pose-axis').value,degrees:Number($('pose-angle').value)});}catch(e){$('message').textContent=e.message;}};
$('use-capture').onclick=async()=>{if(!pendingCapture||!$('review-capture').checked)return;try{const file=new File([JSON.stringify(pendingCapture)],'reviewed-capture.json',{type:'application/json'});const item=await workspace.attach(file);await workspace.manual('use_attachment',{id:item.id});}catch(e){$('message').textContent=e.message;$('capture-status').textContent=e.message;}};
// A processed clip goes through the same attach + use_attachment path as a manual import.
async function applyClip(capture,name){
  const item=await workspace.attach(new File([JSON.stringify(capture)],name+'-capture.json',{type:'application/json'}));const done=await workspace.manual('use_attachment',{id:item.id});if(done?.ok===false)throw Error(done.error||'capture rejected');}
// On load, preview the newest processed clip (or --clip) with its source video.
initialRun.then(async()=>{const r=await fetch('/api/clip');if(!r.ok)return;const clip=await r.json();
  try{if(clip.video){const blob=await (await fetch('/clip/video')).blob();await loadVideo(new File([blob],clip.video,{type:blob.type}));}
    await applyClip(clip.capture,clip.name);$('capture-status').textContent='Previewing clip '+clip.name+(clip.video?' with source video '+clip.video:'')+'.';
  }catch(e){$('capture-status').textContent='Clip '+clip.name+' failed to load: '+e.message;}});
// Submit a video to the SAM worker, follow the job, then apply the capture to the whole skeleton.
$('process-file').onchange=async()=>{const f=$('process-file').files[0];if(!f)return;const status=$('job-status');
  try{status.textContent='Uploading '+f.name+'…';
    const r=await fetch('/api/jobs?name='+encodeURIComponent(f.name)+'&start='+Number($('process-start').value||0),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:f});const job=await r.json();if(!r.ok)throw Error(job.error||'Upload failed');
    const started=performance.now();let s;
    do{await new Promise(done=>setTimeout(done,2000));const p=await fetch('/api/jobs/'+job.id);s=await p.json();if(!p.ok)throw Error(s.error||'Job status failed');
      status.textContent=s.status+' · '+s.message+(s.frames?' · frame '+s.frames+'/'+s.expected_frames:'')+' · '+Math.round((performance.now()-started)/1000)+' s'+(s.log?.length&&!s.frames?' · '+s.log.at(-1):'');
    }while(!['done','failed'].includes(s.status));
    if(s.status==='failed')throw Error(s.message+(s.log?.length?': '+s.log.slice(-3).join(' | '):''));
    const blob=await (await fetch('/clip/video')).blob();await loadVideo(new File([blob],s.name+'.mp4',{type:'video/mp4'}));  // the exact video SAM ran on
    await applyClip(s.capture,s.name);status.textContent='Processed '+job.seconds+' s of '+f.name+' in '+Math.round((performance.now()-started)/1000)+' s; whole skeleton retargeted. Saved as private/clips/'+s.name+'.';
  }catch(e){status.textContent=e.message;}finally{$('process-file').value='';}};
