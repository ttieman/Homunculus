const $=id=>document.getElementById(id);
const names=['duration','shoulder_deg','elbow_deg','strength','damping'];
let current=null, result=null, gltf=null, history=[], audit=[], proposal=null, busy=false;
let playing=true, cursor=0, exported=false, replayFrames=null, previous=performance.now();
function fields(){return Object.fromEntries([...names.map(n=>[n,Number($(n).value)]),['obstacle',$('obstacle').checked]]);}
function labels(){for(const n of names)$(n+'-value').textContent=$(n).value+(n==='duration'?' s':n.endsWith('_deg')?'°':'×');}
function fill(e){for(const n of names)$(n).value=e[n];$('obstacle').checked=e.obstacle;labels();}
for(const n of names)$(n).oninput=labels;
labels();
async function api(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const j=await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j;}
function lock(value){busy=value;for(const id of ['apply','undo','propose','accept'])$(id).disabled=value; $('undo').disabled=value||!history.length;}
async function simulate(edit,source='manual',remember=true){
  if(busy)return;lock(true);$('message').textContent='Simulating physical response…';
  try{const payload=await api('/api/simulate',{edit});if(remember&&current)history.push(structuredClone(current));
    current=edit;result=payload.result;gltf=payload.gltf;cursor=0;exported=false;replayFrames=null;proposal=null;$('accept').hidden=true;$('proposal').textContent='';
    audit.push({source,edit:structuredClone(edit),at:new Date().toISOString()});fill(edit);
    $('error').textContent=result.metrics.tracking_rmse_deg.toFixed(2)+'°';$('contact').textContent=result.metrics.contact_steps;
    $('speed').textContent=Math.round(result.metrics.simulation_wall_s*1000)+' ms';
    $('message').textContent='Result ready. Peak penetration '+(result.metrics.max_penetration_m*1000).toFixed(2)+' mm. Export contains the actual simulated motion.';
    $('view-label').textContent='Physical result · fixed shoulder';$('replay').textContent='Replay export';return true;
  }catch(e){$('message').textContent=e.message;return false;}finally{lock(false);}
}
$('apply').onclick=()=>simulate(fields());
$('undo').onclick=async()=>{const e=history.at(-1);if(e&&await simulate(e,'undo',false)){history.pop();$('undo').disabled=!history.length;}};
$('propose').onclick=async()=>{if(busy)return;lock(true);$('meta-status').textContent='Asking Muse Spark…';proposal=null;$('accept').hidden=true;$('proposal').textContent='';
  try{proposal=await api('/api/propose',{edit:fields(),prompt:$('prompt').value});$('proposal').textContent=JSON.stringify(proposal.edit,null,2);$('accept').hidden=false;$('meta-status').textContent='Live '+proposal.provenance.model+' proposal. Review before applying.';}
  catch(e){$('meta-status').textContent=e.message;}finally{lock(false);}};
$('accept').onclick=()=>{if(!proposal)return;if(JSON.stringify(fields())!==JSON.stringify(proposal.base)){$('meta-status').textContent='Controls changed since this proposal. Ask again before applying.';return;}simulate(proposal.edit,proposal.provenance);};
function download(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('export').onclick=()=>gltf&&download('force-puppet-reach.gltf',gltf);
$('save').onclick=()=>result&&download('force-puppet-session.json',{edit:current,audit,result,gltf});
function readAccessor(doc,index,width){const a=doc.accessors[index],v=doc.bufferViews[a.bufferView];const bytes=Uint8Array.from(atob(doc.buffers[v.buffer].uri.split(',')[1]),c=>c.charCodeAt(0));const view=new DataView(bytes.buffer);return Array.from({length:a.count},(_,i)=>Array.from({length:width},(_,j)=>view.getFloat32((v.byteOffset||0)+(a.byteOffset||0)+(i*width+j)*4,true)));}
$('replay').onclick=()=>{if(!gltf)return;exported=!exported;if(exported){const samplers=gltf.animations[0].samplers;const tracks=samplers.map(s=>readAccessor(gltf,s.output,4));const times=readAccessor(gltf,samplers[0].input,1);replayFrames=times.map((t,i)=>({t:t[0],q:tracks.map(track=>2*Math.atan2(track[i][2],track[i][3]))}));}
  $('view-label').textContent=exported?'glTF replay · decoded animation buffers':'Physical result · fixed shoulder';$('replay').textContent=exported?'Back to simulation':'Replay export';};
$('play').onclick=()=>{playing=!playing;$('play').textContent=playing?'Pause':'Play';$('play').setAttribute('aria-label',playing?'Pause playback':'Play playback');};
$('timeline').oninput=()=>{if(current)cursor=Number($('timeline').value)*current.duration;};
const canvas=$('stage'),ctx=canvas.getContext('2d');
function draw(now){const dt=Math.min((now-previous)/1000,.1);previous=now;if(result&&playing)cursor=(cursor+dt)%current.duration;
  const rect=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;const w=rect.width,h=rect.height;if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const scale=Math.min(h/2.25,w/1.7),ox=w*.32,oy=h*.91;
  const point=(x,y)=>[ox+x*scale,oy-y*scale];
  function line(a,b,color,width=2,dash=[]){ctx.beginPath();ctx.setLineDash(dash);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineCap='round';ctx.moveTo(...point(...a));ctx.lineTo(...point(...b));ctx.stroke();ctx.setLineDash([]);}
  function circle(x,y,r,color){ctx.beginPath();ctx.arc(...point(x,y),r*scale,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();}
  for(let x=-1;x<2;x+=.2)line([x,0],[x,2.1],'#2e3d3e',.5);for(let y=0;y<2.2;y+=.2)line([-1,y],[2,y],'#2e3d3e',.5);
  line([-1,0],[2,0],'#637672',1);line([0,0],[0,1.4],'#71837a',8,[3,5]);line([-.15,0],[.15,0],'#92a49a',8);
  // Context silhouette is fixed scenery, not an additional simulated body.
  line([-.12,1.4],[-.12,.8],'#3d5353',25);circle(-.12,1.7,.12,'#526765');line([-.12,.8],[-.25,.14],'#3d5353',14);line([-.12,.8],[.03,.14],'#3d5353',14);
  if(current?.obstacle){const a=point(.395,1.77);ctx.fillStyle='#bc794945';ctx.strokeStyle='#d7945b';ctx.lineWidth=1.5;ctx.fillRect(a[0],a[1],.15*scale,.24*scale);ctx.strokeRect(a[0],a[1],.15*scale,.24*scale);}
  if(result){const frames=exported?replayFrames:result.frames;const f=frames[Math.min(Math.floor(cursor/.02),frames.length-1)];const original=result.frames[Math.min(Math.floor(cursor/.02),result.frames.length-1)];
    function arm(q,color,width,dash=[]){const elbow=[.34*Math.cos(q[0]),1.4+.34*Math.sin(q[0])];const hand=[elbow[0]+.29*Math.cos(q[0]+q[1]),elbow[1]+.29*Math.sin(q[0]+q[1])];line([0,1.4],elbow,color,width,dash);line(elbow,hand,color,width*.8,dash);if(!dash.length){circle(...elbow,.044,'#e1f6dc');circle(...hand,.044,color);}return hand;}
    arm(original.target,'#9eafaa80',3,[6,6]);const hand=arm(f.q,exported?'#aacbff':'#b8f4b2',15);circle(0,1.4,.055,'#e4e8cf');
    ctx.fillStyle='#c2d1c9';ctx.font='11px Segoe UI';ctx.fillText(exported?'EXPORTED MOTION':original.contacts?'CONTACT':'REACH',point(...hand)[0]+18,point(...hand)[1]);
    $('timeline').value=cursor/current.duration;$('time').textContent=cursor.toFixed(2)+' / '+current.duration.toFixed(2)+' s';
  }requestAnimationFrame(draw);
}
requestAnimationFrame(draw);
fetch('/api/status').then(r=>r.json()).then(s=>{$('meta-status').textContent='Muse Spark · '+s.meta;}).catch(e=>{$('meta-status').textContent=e.message;});
simulate(fields(),'initial procedural fixture',false);
