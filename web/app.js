const $=id=>document.getElementById(id);
const names=['duration','shoulder_deg','elbow_deg','strength','damping'];
let current=null, result=null, gltf=null, history=[], redoHistory=[], audit=[], proposal=null, busy=false;
let activeCapture=null, pendingCapture=null, videoHash=null, videoURL=null, hashingVideo=false;
let cameraYaw=0;
let maxDocumentBytes=0;
fetch('/api/contracts').then(r=>r.json()).then(c=>{maxDocumentBytes=c.max_document_bytes;});
let playing=true, cursor=0, exported=false, replayFrames=null, previous=performance.now();
function fields(){return Object.fromEntries([...names.map(n=>[n,Number($(n).value)]),['obstacle',$('obstacle').checked]]);}
function labels(){for(const n of names)$(n+'-value').textContent=$(n).value+(n==='duration'?' s':n.endsWith('_deg')?'°':'×');}
function fill(e){for(const n of names)$(n).value=e[n];$('obstacle').checked=e.obstacle;labels();}
for(const n of names)$(n).oninput=labels;
labels();
async function api(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const j=await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j;}
function lock(value){busy=value;for(const id of ['apply','undo','redo','propose','accept','use-fixture','capture-file','video-file'])$(id).disabled=value; $('undo').disabled=value||!history.length; $('redo').disabled=value||!redoHistory.length; for(const id of ['optimize','three-poses','save-reference','edit-key'])$(id).disabled=value||activeCapture?.retargeting!=='spatial_arm_v1'; $('propose').disabled=value||(!!activeCapture&&activeCapture.retargeting!=='spatial_arm_v1');$('video-file').disabled=value||hashingVideo;$('use-capture').disabled=value||hashingVideo||!pendingCapture||!$('review-capture').checked;}
async function simulate(edit,source='manual',remember=true,capture=activeCapture,optimize=false){
  if(busy)return;lock(true);$('message').textContent='Simulating physical response…';
  try{const payload=await api(optimize?'/api/synthesize':'/api/simulate',{edit,capture});if(remember)redoHistory=[];if(remember&&current)history.push(structuredClone({edit:current,capture:activeCapture}));
    edit=payload.result.edit;current=edit;activeCapture=capture;result=payload.result;gltf=payload.gltf;cursor=0;exported=false;replayFrames=null;proposal=null;$('accept').hidden=true;$('proposal').textContent='';
    $('shoulder_deg').disabled=!!capture;$('elbow_deg').disabled=!!capture;
    $('source-note').textContent=capture?'Imported '+capture.provenance.kind+' arm motion · Fixed shoulder · Recorded angles own the pose; duration, strength and damping remain editable. Language edits can change timing; new poses and forces are not supported.':'Original procedural reference · MuJoCo torque control · Fixed shoulder. Full-body balance and game retargeting are not included.';
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
$('save').onclick=()=>result&&download('force-puppet-session.json',{edit:current,capture:activeCapture,audit,result,gltf});
function reviewReady(){lock(busy);}
$('review-capture').onchange=reviewReady;
$('video-file').onchange=async()=>{const f=$('video-file').files[0];if(!f)return;
  if(f.size>100*1024*1024){$('capture-status').textContent='Choose a video under 100 MB.';return;}
  if(videoURL)URL.revokeObjectURL(videoURL);videoURL=URL.createObjectURL(f);$('source-video').src=videoURL;$('source-video').hidden=false;$('source-pane').hidden=false;$('comparison').classList.add('has-video');document.body.classList.add('comparison-active');
  videoHash=null;hashingVideo=true;$('review-capture').checked=false;reviewReady();
  try{videoHash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await f.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('');
    $('capture-status').textContent=pendingCapture&&pendingCapture.provenance.video_sha256!==videoHash?'Video does not match imported capture. Select the original video.':'Local video ready. Process it with the worker and import capture.json.';
  }catch(e){$('capture-status').textContent=e.message;}finally{hashingVideo=false;reviewReady();}
};
$('capture-file').onchange=async()=>{const f=$('capture-file').files[0];pendingCapture=null;$('review-capture').checked=false;reviewReady();if(!f)return;
  try{if(!maxDocumentBytes)throw Error('Document limits are loading; select the file again.');if(f.size>maxDocumentBytes)throw Error('Capture exceeds the '+maxDocumentBytes+' byte document limit.');const candidate=JSON.parse(await f.text());const checked=await api('/api/capture/validate',{capture:candidate});
    pendingCapture=candidate;const dimensionality=candidate.retargeting==='spatial_arm_v1'?'3D arm':checked.metadata.max_out_of_plane_deg.toFixed(1)+' degrees out of plane';$('capture-status').textContent=candidate.provenance.kind+' / '+checked.metadata.source_duration_s.toFixed(2)+' s / '+dimensionality+' / '+checked.metadata.missing_frames+' missing frames. Inspect overlays and confirm the mapping.';
  }catch(e){$('capture-status').textContent=e.message;}finally{reviewReady();}
};
$('use-capture').onclick=async()=>{if(!pendingCapture||!$('review-capture').checked||hashingVideo)return;
  if(videoURL&&!videoHash){$('capture-status').textContent='Video hash could not be verified. Reload and reselect the source video.';return;}
  if(videoHash&&pendingCapture.provenance.video_sha256!==videoHash){$('capture-status').textContent='Video hash mismatch. Capture must belong to the selected source video.';return;}
  const frames=pendingCapture.frames;const duration=pendingCapture.reference_animation?.keyframes.at(-1).time??(frames.at(-1).t-frames[0].t);
  await simulate({...fields(),duration:duration,obstacle:false},'imported capture',true,pendingCapture);
};
$('use-fixture').onclick=()=>simulate(fields(),'procedural fixture',true,null);
function readAccessor(doc,index,width){const a=doc.accessors[index],v=doc.bufferViews[a.bufferView];const bytes=Uint8Array.from(atob(doc.buffers[v.buffer].uri.split(',')[1]),c=>c.charCodeAt(0));const view=new DataView(bytes.buffer);return Array.from({length:a.count},(_,i)=>Array.from({length:width},(_,j)=>view.getFloat32((v.byteOffset||0)+(a.byteOffset||0)+(i*width+j)*4,true)));}
$('replay').onclick=()=>{if(!gltf)return;exported=!exported;if(exported){const samplers=gltf.animations[0].samplers;const tracks=samplers.map(s=>readAccessor(gltf,s.output,4));const times=readAccessor(gltf,samplers[0].input,1);replayFrames=times.map((t,i)=>({t:t[0],rotations:tracks.map(track=>track[i]),q:tracks.map(track=>2*Math.atan2(track[i][2],track[i][3])),...quaternionArm(tracks.map(track=>track[i]))}));}
  $('view-label').textContent=exported?'glTF replay · decoded animation buffers':'Physical result · fixed shoulder';$('replay').textContent=exported?'Back to simulation':'Replay export';};
$('play').onclick=()=>{playing=!playing;$('play').textContent=playing?'Pause':'Play';$('play').setAttribute('aria-label',playing?'Pause playback':'Play playback');};
$('timeline').oninput=()=>{if(current)cursor=Number($('timeline').value)*current.duration;};
function slerp(a,b,u){let dot=a.reduce((v,x,i)=>v+x*b[i],0);if(dot<0){b=b.map(x=>-x);dot=-dot;}let q;if(dot>.9995){q=a.map((x,i)=>(1-u)*x+u*b[i]);}else{const angle=Math.acos(Math.min(1,dot));q=a.map((x,i)=>(Math.sin((1-u)*angle)*x+Math.sin(u*angle)*b[i])/Math.sin(angle));}const n=Math.hypot(...q);return q.map(x=>x/n);}
function sampleFrames(frames,t){let lo=0,hi=frames.length-1;while(lo+1<hi){const mid=(lo+hi)>>1;if(frames[mid].t<=t)lo=mid;else hi=mid;}if(t>=frames.at(-1).t)return frames.at(-1);const a=frames[lo],b=frames[hi],u=Math.max(0,(t-a.t)/(b.t-a.t));const out={...a};for(const k of ['q','target','elbow','hand','target_elbow','target_hand'])if(a[k])out[k]=a[k].map((x,i)=>x+(b[k][i]-x)*u);if(a.rotations){out.rotations=a.rotations.map((q,i)=>slerp(q,b.rotations[i],u));Object.assign(out,quaternionArm(out.rotations));out.q=out.rotations.map(q=>2*Math.atan2(q[2],q[3]));}return out;}
function rotate(q,v){const [x,y,z,w]=q;const t=[2*(y*v[2]-z*v[1]),2*(z*v[0]-x*v[2]),2*(x*v[1]-y*v[0])];return [v[0]+w*t[0]+y*t[2]-z*t[1],v[1]+w*t[1]+z*t[0]-x*t[2],v[2]+w*t[2]+x*t[1]-y*t[0]];}
function quaternionArm(q){const a=rotate(q[0],[.34,0,0]);const b=rotate(q[0],rotate(q[1],[.29,0,0]));return {elbow:[a[0],1.4+a[1],a[2]],hand:[a[0]+b[0],1.4+a[1]+b[1],a[2]+b[2]]};}
const canvas=$('stage'),ctx=canvas.getContext('2d');
let dragX=null;canvas.onpointerdown=e=>{dragX=e.clientX;canvas.setPointerCapture(e.pointerId);};canvas.onpointermove=e=>{if(dragX!==null){cameraYaw+=(e.clientX-dragX)*.01;dragX=e.clientX;}};canvas.onpointerup=canvas.onpointercancel=()=>{dragX=null;};

function draw(now){const dt=Math.min((now-previous)/1000,.1);previous=now;if(result&&playing)cursor=(cursor+dt)%current.duration;
  const rect=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;const w=rect.width,h=rect.height;if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const scale=Math.min(h/2.25,w/1.7),ox=w*.32,oy=h*.91;
  const point=(x,y,z=0)=>[ox+(x*Math.cos(cameraYaw)+z*Math.sin(cameraYaw))*scale,oy-y*scale];
  function line(a,b,color,width=2,dash=[]){ctx.beginPath();ctx.setLineDash(dash);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineCap='round';ctx.moveTo(...point(...a));ctx.lineTo(...point(...b));ctx.stroke();ctx.setLineDash([]);}
  function circle(x,y,r,color){ctx.beginPath();ctx.arc(...point(x,y),r*scale,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();}
  for(let x=-1;x<2;x+=.2)line([x,0],[x,2.1],'#2e3d3e',.5);for(let y=0;y<2.2;y+=.2)line([-1,y],[2,y],'#2e3d3e',.5);
  line([-1,0],[2,0],'#637672',1);line([0,0],[0,1.4],'#71837a',8,[3,5]);line([-.15,0],[.15,0],'#92a49a',8);
  // Context silhouette is fixed scenery, not an additional simulated body.
  line([-.12,1.4],[-.12,.8],'#3d5353',25);circle(-.12,1.7,.12,'#526765');line([-.12,.8],[-.25,.14],'#3d5353',14);line([-.12,.8],[.03,.14],'#3d5353',14);
  if(current?.obstacle){const a=point(.395,1.77);ctx.fillStyle='#bc794945';ctx.strokeStyle='#d7945b';ctx.lineWidth=1.5;ctx.fillRect(a[0],a[1],.15*scale,.24*scale);ctx.strokeRect(a[0],a[1],.15*scale,.24*scale);}
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
    function arm(q,color,width,dash=[]){const elbow=[.34*Math.cos(q[0]),1.4+.34*Math.sin(q[0])];const hand=[elbow[0]+.29*Math.cos(q[0]+q[1]),elbow[1]+.29*Math.sin(q[0]+q[1])];line([0,1.4],elbow,color,width,dash);line(elbow,hand,color,width*.8,dash);if(!dash.length){circle(...elbow,.044,'#e1f6dc');circle(...hand,.044,color);}return hand;}
    let hand;
    if(result.rig==='spatial_arm_v1'){
      line([0,1.4,0],original.target_elbow,'#9eafaa80',3,[6,6]);line(original.target_elbow,original.target_hand,'#9eafaa80',3,[6,6]);
      const color=exported?'#aacbff':'#b8f4b2';line([0,1.4,0],f.elbow,color,15);line(f.elbow,f.hand,color,12);hand=f.hand;
    }else{arm(original.target,'#9eafaa80',3,[6,6]);hand=arm(f.q,exported?'#aacbff':'#b8f4b2',15);}
    circle(0,1.4,.055,'#e4e8cf');
    ctx.fillStyle='#c2d1c9';ctx.font='11px Segoe UI';ctx.fillText(exported?'EXPORTED MOTION':original.contacts?'CONTACT':'REACH',point(...hand)[0]+18,point(...hand)[1]);
    $('timeline').value=cursor/current.duration;$('time').textContent=cursor.toFixed(2)+' / '+current.duration.toFixed(2)+' s';
  }requestAnimationFrame(draw);
}
requestAnimationFrame(draw);
fetch('/api/status').then(r=>r.json()).then(s=>{$('meta-status').textContent='Muse Spark · '+s.meta;}).catch(e=>{$('meta-status').textContent=e.message;});
simulate(fields(),'initial procedural fixture',false);
