import * as C from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import './style.css';
import {decode, j2000Millis, sampleDate, type Sample} from './packet';
import {expectedGroundTrack, type ForecastPoint} from './orbit';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const status = $('status');
const diagnostics = $('diagnostics');
const timeline = $<HTMLInputElement>('timeline');
const fpsInput = $<HTMLInputElement>('fps');
const cameraInput = $<HTMLSelectElement>('camera');
const speedInput = $<HTMLInputElement>('speed');
const bookList = $('bookmarks');
const groundMap = $<HTMLCanvasElement>('ground-map');
const params = new URLSearchParams(location.search);
const archivedOnly = params.get('mode') === 'replay';
const expectedRun = params.get('run') || '';
const packetName = '/SHIRE_VISUAL/SHIRE_VISUAL_DATA';
const packetUrl = '/api/archive/shire/packets';
const bucket = '/api/storage/buckets/shireRuns/objects';
const viewer = new C.Viewer('globe', {
  baseLayer: false, baseLayerPicker:false, geocoder:false, homeButton:false,
  sceneModePicker:false, navigationHelpButton:false, animation:false,
  timeline:false, infoBox:false, selectionIndicator:false,
  terrainProvider: new C.EllipsoidTerrainProvider(),
  skyAtmosphere:false,
  scene3DOnly:true, requestRenderMode:true, maximumRenderTimeChange:Infinity
});
viewer.scene.globe.enableLighting = true;
viewer.scene.backgroundColor = C.Color.fromCssColorString('#080d1a');
viewer.scene.skyBox = C.SkyBox.createEarthSkyBox();
viewer.scene.moon = new C.Moon();
viewer.clock.shouldAnimate = false;
viewer.scene.screenSpaceCameraController.enableCollisionDetection = false;
viewer.scene.screenSpaceCameraController.minimumZoomDistance = 0.1;
fetch('/visualization/earth-imagery.json').then(response => response.json()).then(asset => {
  const url=`/visualization/${asset.file}`;
  $('map-image').style.backgroundImage=`url('${url}')`;
  return C.SingleTileImageryProvider.fromUrl(url);
}).then(provider => viewer.imageryLayers.addImageryProvider(provider)).catch(err => {
  status.textContent = `Offline Earth imagery unavailable: ${err}`;
});
// The build manifest declares how the mesh sits in 42's center-of-mass body
// frame after Cesium's glTF up/forward-axis correction.
let spacecraft: C.Model | undefined;
let modelRadius = 1;
let cameraMode = '';
let modelToBody=C.Matrix4.clone(C.Matrix4.IDENTITY);
type ModelAsset = {sourceName?:string;upAxis:'X'|'Y'|'Z';forwardAxis:'X'|'Y'|'Z';modelToBody:number[]};
void fetch('/visualization/model-asset.json').then(response => {
  if(!response.ok) throw new Error(`Model manifest ${response.status}`);
  return response.json() as Promise<ModelAsset>;
}).then(asset => {
  modelToBody=C.Matrix4.fromRowMajorArray(asset.modelToBody);
  $('model-name').textContent=asset.sourceName||'model.glb';
  return C.Model.fromGltfAsync({url:'/visualization/model.glb',show:false,
    upAxis:C.Axis[asset.upAxis],forwardAxis:C.Axis[asset.forwardAxis],
    modelMatrix:C.Matrix4.fromTranslation(new C.Cartesian3(7000000,0,0))});
}).then(model => {
  spacecraft=viewer.scene.primitives.add(model);
  model.readyEvent.addEventListener(() => {
    modelRadius=Math.max(0.1,model.boundingSphere.radius);
    cameraMode='';
    viewer.scene.requestRender();
  });
  viewer.scene.requestRender();
}).catch(err => {$('model-name').textContent='Unavailable';status.textContent=`Spacecraft model unavailable: ${err}`;});
const lines=viewer.scene.primitives.add(new C.PolylineCollection());
const makeLine=(color:C.Color,width:number)=>lines.add({
  positions:[new C.Cartesian3(7000000,0,0),new C.Cartesian3(7000001,0,0)],
  width,material:C.Material.fromType('Color',{color}),show:false
});
// Primitive polylines update synchronously and retain their GPU objects.
const trailLines=viewer.scene.primitives.add(new C.PolylineCollection());
const trailSegments: C.Polyline[] = [];
let activeTrailCount=0;
let trailDirty = true;
const sun = makeLine(C.Color.YELLOW.withAlpha(.7),2);
const axes = [C.Color.RED,C.Color.LIME,C.Color.DEEPSKYBLUE].map(color => makeLine(color,3));
let mode: 'live'|'replay' = archivedOnly ? 'replay' : 'live';
let transitionId=0;
let playing = true;
let samples: Sample[] = [];
let first: Sample | undefined;
let last: Sample | undefined;
let currentUtc = 0;
let lastFrame = performance.now();
let socket: WebSocket | undefined;
let fetchSerial = 0;
let loading = false;
let pendingUtc: number | undefined;
let recordHz = 20;
let lastHeadPoll=0;
let headPolling=false;
let frameRate = 30;
let playbackSpeed = 1;
let bookmarks: {utc:number; note:string}[] = [];
let observedRun = expectedRun;
let expectedStep = 0;
const track = new Map<number, [number, number, boolean]>();
let trackSerial = 0;
let trackCoverage: [number, number] | undefined;

function worldPoint(s: Sample): C.Cartesian3 {
  const w = s.cwn.map(row => row.reduce((a,x,i) => a+x*s.pos[i],0));
  return new C.Cartesian3(w[0],w[1],w[2]);
}
function recordTrack(s: Sample) {
  const second=Math.floor(s.utc);
  if(track.has(second)) return;
  const point=C.Cartographic.fromCartesian(worldPoint(s));
  track.set(second,[(point.longitude/C.Math.TWO_PI)+.5,
                    .5-point.latitude/C.Math.PI,s.eclipse]);
  while(track.size>5400) track.delete(track.keys().next().value!);
}
function drawGroundTrack(position: C.Cartesian3, anchor: Sample) {
  const ctx=groundMap.getContext('2d');
  if(!ctx) return;
  const width=groundMap.width,height=groundMap.height;
  ctx.clearRect(0,0,width,height);
  const ordered=[...track.entries()].sort((a,b)=>a[0]-b[0]);
  const draw=(points: {time:number;x:number;y:number;eclipse:boolean}[],
              color:string,dash:number[],strokeWidth:number,shadowOnly=false) => {
    ctx.strokeStyle=color;ctx.lineWidth=strokeWidth;
    ctx.lineCap='round';ctx.lineJoin='round';
    ctx.setLineDash(dash);
    ctx.beginPath();
    let previous: typeof points[number]|undefined;
    let penDown=false;
    for(const point of points) {
      const connected=!!previous && point.time-previous.time<=120 &&
        Math.abs(point.x-previous.x)<width/2;
      if(shadowOnly && (!point.eclipse || !previous?.eclipse)) {
        previous=point;penDown=false;continue;
      }
      if(connected) {
        if(!penDown) ctx.moveTo(previous!.x,previous!.y);
        ctx.lineTo(point.x,point.y);
        penDown=true;
      } else {ctx.moveTo(point.x,point.y);penDown=false;}
      previous=point;
    }
    ctx.stroke();ctx.setLineDash([]);
  };
  const recorded=ordered.map(([time,[longitude,latitude,eclipse]])=>
    ({time,x:longitude*width,y:latitude*height,eclipse}));
  const predicted:ForecastPoint[]=expectedGroundTrack(anchor);
  const projected=predicted.map((point,i)=>({time:i*60,
    x:point.longitude*width,y:point.latitude*height,eclipse:point.eclipse}));
  draw(projected,'#ff9b32',[8,5],2.5);
  draw(projected,'#101827',[3,4],7,true);
  draw(projected,'#c746ff',[3,4],4,true);
  draw(recorded,'#71efff',[],2);
  draw(recorded,'#101827',[],7,true);
  draw(recorded,'#c746ff',[],4,true);
  const here=C.Cartographic.fromCartesian(position);
  const x=(here.longitude/C.Math.TWO_PI+.5)*width;
  const y=(.5-here.latitude/C.Math.PI)*height;
  ctx.beginPath();ctx.arc(x,y,5,0,C.Math.TWO_PI);
  ctx.fillStyle='#ffdc69';ctx.fill();
  ctx.lineWidth=2;ctx.strokeStyle='#071322';ctx.stroke();
}
async function loadGroundTrack(center: number) {
  if(!first||!last) return;
  const from=Math.max(first.utc,center-1800),to=Math.min(last.utc,center+1800);
  if(trackCoverage && center>=trackCoverage[0] && center<=trackCoverage[1]) return;
  const serial=++trackSerial;
  const query=new URLSearchParams({name:packetName,order:'asc',limit:'400',
    start:new Date(j2000Millis+from*1000).toISOString(),
    stop:new Date(j2000Millis+to*1000).toISOString()});
  let lastRead=from;
  for(let count=0;count<12000;) {
    const page=await list(query);
    if(serial!==trackSerial) return;
    for(const packet of page.packets||[]) {
      const sample=packetSample(packet);
      if(sample) {recordTrack(sample);lastRead=sample.utc;}
    }
    count+=(page.packets||[]).length;
    if(!page.continuationToken||count>=12000) break;
    query.set('next',page.continuationToken);
  }
  trackCoverage=[from,lastRead];
}
function orientation(s: Sample): C.Quaternion {
  const [x,y,z,w] = s.q; // 42: vector first, scalar last; CBN maps N to body.
  const cbn = [
    [1-2*(y*y+z*z),2*(x*y+z*w),2*(x*z-y*w)],
    [2*(x*y-z*w),1-2*(x*x+z*z),2*(y*z+x*w)],
    [2*(x*z+y*w),2*(y*z-x*w),1-2*(x*x+y*y)]
  ];
  // Body -> Earth fixed = CWN * transpose(CBN).
  const rows = s.cwn.map(row => row.map((_,j) => row.reduce((a,x,k) => a+x*cbn[j][k],0)));
  const matrix = C.Matrix3.fromRowMajorArray(rows.flat());
  return C.Quaternion.normalize(C.Quaternion.fromRotationMatrix(matrix),new C.Quaternion());
}
function packetSample(value: {packet?:string}): Sample | undefined {
  if (!value.packet) return undefined;
  try {
    const s = decode(value.packet);
    if (observedRun && observedRun !== s.run) throw new Error('Run ID mismatch in Yamcs packet');
    observedRun ||= s.run;
    return s;
  } catch (err) { status.textContent = String(err); return undefined; }
}
function push(s: Sample) {
  const previous = samples.at(-1);
  if (previous && s.sequence <= previous.sequence) return;
  if (previous && s.sequence > previous.sequence)
    expectedStep = expectedStep ? Math.min(expectedStep, s.sequence-previous.sequence) : s.sequence-previous.sequence;
  samples.push(s);
  recordTrack(s);
  trailDirty = true;
  if (samples.length > 600) samples.splice(0,samples.length-600);
  first ||= s;
  last = s;
  if (mode === 'live') currentUtc = s.utc;
}
function selectedState(utc: number): {state:Sample; gap:boolean}|undefined {
  if (!samples.length) return undefined;
  let lo=0, hi=samples.length;
  while (lo<hi) {const m=(lo+hi)>>1; if(samples[m].utc<utc) lo=m+1; else hi=m;}
  if (lo===0) return {state:samples[0],gap:utc<samples[0].utc};
  if (lo===samples.length) return {state:samples.at(-1)!,gap:utc>samples.at(-1)!.utc+0.1};
  const a=samples[lo-1], b=samples[lo];
  if (!expectedStep || a.sequence+expectedStep!==b.sequence || b.sim-a.sim>1.5*expectedStep*.01)
    return {state:a,gap:true};
  const t=Math.min(1,Math.max(0,(utc-a.utc)/(b.utc-a.utc)));
  const lerp=(x:number,y:number)=>x+(y-x)*t;
  // Interpolate in Earth-fixed coordinates, then render with a slerped body attitude.
  const pa=worldPoint(a), pb=worldPoint(b);
  const qa=orientation(a), qb=orientation(b);
  const p=C.Cartesian3.lerp(pa,pb,t,new C.Cartesian3());
  const q=C.Quaternion.slerp(qa,qb,t,new C.Quaternion());
  const state={...a,sequence:t>=.5?b.sequence:a.sequence,pos:[p.x,p.y,p.z] as [number,number,number],
    q:[q.x,q.y,q.z,q.w] as [number,number,number,number],utc:lerp(a.utc,b.utc),sim:lerp(a.sim,b.sim)};
  return {state,gap:false};
}
function placeCamera(position: C.Cartesian3) {
  const selected=cameraInput.value;
  if(selected==='earth') {
    if(cameraMode!=='earth') {
      viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
      viewer.camera.flyTo({destination:new C.Cartesian3(0,-23000000,11000000),duration:1});
    }
  } else {
    const frame=C.Transforms.eastNorthUpToFixedFrame(position);
    if(cameraMode!==selected) {
      const range=Math.max(selected==='follow'?5:2.5,
                           modelRadius*(selected==='follow'?8:4));
      viewer.camera.lookAtTransform(frame,new C.HeadingPitchRange(0,-.35,range));
    } else {
      // A user orbit or zoom changes camera.position in the old local frame.
      // Reuse that offset as the spacecraft moves instead of resetting the view.
      const offset=C.Cartesian3.clone(viewer.camera.position);
      viewer.camera.lookAtTransform(frame,offset);
    }
  }
  cameraMode=selected;
}
function render() {
  const selection=selectedState(currentUtc);
  if (!selection) return;
  const {state, gap}=selection;
  // Interpolated states carry Earth-fixed position and orientation directly.
  const interpolated=state!==samples.find(x=>x===state);
  const pos=interpolated && !gap ? new C.Cartesian3(...state.pos) : worldPoint(state);
  const rot=interpolated && !gap ? new C.Quaternion(...state.q) : orientation(state);
  const matrix=C.Matrix3.fromQuaternion(rot);
  const bodyToWorld=C.Matrix4.fromRotationTranslation(matrix,pos);
  // Keep diagnostic vectors anchored to the truth position used by the orbit trail.
  if(spacecraft) {
    spacecraft.show=true;
    spacecraft.modelMatrix=C.Matrix4.multiply(bodyToWorld,modelToBody,new C.Matrix4());
  }
  axes.forEach((axis,i) => {
    axis.show=$<HTMLInputElement>('axes').checked;
    const length=Math.max(2,modelRadius*3);
    const v=new C.Cartesian3(i===0?length:0,i===1?length:0,i===2?length:0);
    axis.positions=[pos,C.Cartesian3.add(pos,C.Matrix3.multiplyByVector(matrix,v,
      new C.Cartesian3()),new C.Cartesian3())];
  });
  sun.show=$<HTMLInputElement>('sun').checked;
  const sunEnd=C.Cartesian3.add(pos,C.Matrix3.multiplyByVector(matrix,C.Cartesian3.multiplyByScalar(new C.Cartesian3(...state.sun),Math.max(3,modelRadius*4),new C.Cartesian3()),new C.Cartesian3()),new C.Cartesian3());
  sun.positions=[pos,sunEnd];
  if (trailDirty) {
    let points: C.Cartesian3[] = [];
    let used=0;
    const addSegment=()=>{
      if(points.length>1) {
        let line=trailSegments[used];
        if(!line) {
          line=trailLines.add({positions:points,width:2,
            material:C.Material.fromType(C.Material.PolylineDashType,{
              color:C.Color.fromCssColorString('#b0b7c1').withAlpha(.9),
              gapColor:C.Color.TRANSPARENT,dashLength:20,dashPattern:0xFF00
            })});
          trailSegments.push(line);
        } else line.positions=points;
        line.show=$<HTMLInputElement>('trail').checked;
        used++;
      }
      points=[];
    };
    samples.forEach((sample,i)=>{
      if(i && (!expectedStep || sample.sequence-samples[i-1].sequence!==expectedStep)) addSegment();
      points.push(worldPoint(sample));
    });
    addSegment();
    activeTrailCount=used;
    trailDirty=false;
  }
  trailSegments.forEach((line,i)=>line.show=$<HTMLInputElement>('trail').checked && i<activeTrailCount);
  // Rebuild entity draw commands before moving a close follow camera.
  viewer.clock.currentTime=C.JulianDate.fromDate(sampleDate(state));
  viewer.dataSourceDisplay.update(viewer.clock.currentTime);
  placeCamera(pos);
  const anchor=samples.reduce((best,s)=>Math.abs(s.utc-currentUtc)<Math.abs(best.utc-currentUtc)?s:best,samples[0]);
  drawGroundTrack(pos,anchor);
  viewer.scene.requestRender();
  const time=sampleDate(state).toISOString();
  status.textContent=`${mode==='replay'&&!playing?'PAUSED':mode.toUpperCase()} · ${time}${gap?' · TELEMETRY GAP':''}`;
  diagnostics.textContent=`Run ${state.run}\nSC ${state.spacecraft} · Tick ${state.sequence} · Sim ${state.sim.toFixed(2)} s\nAltitude ${(C.Cartesian3.magnitude(pos)-6378137).toFixed(0)} m · ${state.eclipse?'Eclipse':'Sunlit'}\nRates ${state.rates.map(v=>v.toFixed(5)).join(', ')} rad/s\nBuffer ${samples.length} samples · ${frameRate} FPS`;
  if(first && last && last.utc>first.utc)
    timeline.value=String(Math.round((currentUtc-first.utc)/(last.utc-first.utc)*1000));
}
async function list(query: URLSearchParams) {
  const response=await fetch(`${packetUrl}?${query}`,{credentials:'same-origin'});
  if(!response.ok) throw new Error(`Yamcs archive ${response.status}`);
  return await response.json() as {packets?:{packet?:string}[];continuationToken?:string};
}
async function bounds(preserveCurrent=false, token=transitionId) {
  const base=new URLSearchParams({name:packetName,limit:'1'});
  const a=await list(new URLSearchParams([...base,['order','asc']]));
  const b=await list(new URLSearchParams([...base,['order','desc']]));
  if(token!==transitionId) return;
  first=packetSample(a.packets?.[0]||{});
  last=packetSample(b.packets?.[0]||{});
  if(last && !preserveCurrent) currentUtc=first?.utc||last.utc;
  if(last) void loadGroundTrack(currentUtc).catch(err=>{status.textContent=String(err);});
  if(!last) status.textContent='No visualization packets in this run archive';
}
async function refreshHead() {
  if(archivedOnly||headPolling||performance.now()-lastHeadPoll<800) return;
  lastHeadPoll=performance.now();headPolling=true;
  try {
    const q=new URLSearchParams({name:packetName,limit:'1',order:'desc'});
    const page=await list(q);
    const head=packetSample(page.packets?.[0]||{});
    if(head && (!last||head.utc>last.utc)) last=head;
  } catch(err) {status.textContent=String(err);}
  finally {headPolling=false;}
}
async function windowAt(utc: number) {
  if(loading) { pendingUtc=utc; return; }
  loading=true;
  const serial=++fetchSerial;
  try {
    const halfWindow=Math.min(8,180/recordHz); // at most 360 samples at 100 Hz
    const start=new Date(j2000Millis+(utc-halfWindow)*1000).toISOString();
    const stop=new Date(j2000Millis+(utc+halfWindow)*1000).toISOString();
    const q=new URLSearchParams({name:packetName,order:'asc',start,stop,limit:'400'});
    const data=await list(q);
    if(serial!==fetchSerial) return;
    const loaded=(data.packets||[]).map(packetSample).filter((s):s is Sample=>!!s);
    if(loaded.length) {samples=loaded;trailDirty=true;loaded.forEach(recordTrack);}
    if(loaded.length>1) {
      const step=Math.min(...loaded.slice(1).map((sample,i)=>sample.sequence-loaded[i].sequence).filter(value=>value>0));
      expectedStep=expectedStep ? Math.min(expectedStep,step) : step;
      recordHz=Math.max(recordHz,100/expectedStep);
    }
    if(data.continuationToken) pendingUtc=utc;
  } catch(err) {status.textContent=String(err);}
  finally {
    loading=false;
    if(pendingUtc!==undefined) {
      const next=pendingUtc;pendingUtc=undefined;
      void windowAt(next).then(render);
    }
  }
}
function connectLive() {
  if(archivedOnly) return;
  transitionId++;fetchSerial++;pendingUtc=undefined;
  socket?.close();
  mode='live'; playing=true;
  lastFrame=performance.now();
  $('play').textContent='Pause';
  const url=`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/websocket`;
  const active=new WebSocket(url,'json');
  socket=active;
  active.onopen=()=>active.send(JSON.stringify({type:'packets',id:1,options:{instance:'shire',stream:'visual_data'}}));
  active.onmessage=e=>{
    const message=JSON.parse(e.data);
    if(message.type==='packets') {const s=packetSample(message.data); if(s)push(s);}
    if(message.type==='reply'&&message.data?.exception)status.textContent=JSON.stringify(message.data.exception);
  };
  active.onclose=()=>{
    if(socket===active&&mode==='live') setTimeout(()=>{
      // A pending reconnect must never undo an operator's later Pause.
      if(socket===active&&mode==='live') connectLive();
    },2000);
  };
}
async function loadBookmarks() {
  const listing=await fetch(`${bucket}?prefix=bookmarks.json`,{credentials:'same-origin'});
  if(!listing.ok) throw new Error(`Yamcs bookmarks ${listing.status}`);
  const index=await listing.json() as {objects?:{name:string}[]};
  if(index.objects?.some(object=>object.name==='bookmarks.json')) {
    const response=await fetch(`${bucket}/bookmarks.json`,{credentials:'same-origin'});
    if(response.ok) bookmarks=await response.json();
  }
  drawBookmarks();
}
function drawBookmarks() {
  bookList.replaceChildren(...bookmarks.map(b=>{
    const btn=document.createElement('button'); btn.textContent=`${new Date(j2000Millis+b.utc*1000).toISOString()} · ${b.note}`;
    btn.onclick=async()=>{
      const token=++transitionId;fetchSerial++;pendingUtc=undefined;
      mode='replay';playing=false;$('play').textContent='Play';socket?.close();
      currentUtc=b.utc;await bounds(true,token);
      if(token!==transitionId)return;
      await windowAt(currentUtc);
      if(token===transitionId)render();
    };
    return btn;
  }));
}
$('live').onclick=connectLive;
if(archivedOnly) ($<HTMLButtonElement>('live')).disabled=true;
$('replay').onclick=async()=>{
  const token=++transitionId;fetchSerial++;pendingUtc=undefined;
  socket?.close();mode='replay';playing=false;$('play').textContent='Play';
  await bounds(false,token);
  if(token!==transitionId)return;
  await windowAt(currentUtc);
  if(token===transitionId)render();
};
$('play').onclick=async()=>{
  if(mode==='live') {
    // Leave SHIRE running while the viewer freezes and reads Yamcs history.
    const frozen=currentUtc;
    const token=++transitionId;fetchSerial++;pendingUtc=undefined;
    mode='replay';playing=false;socket?.close();$('play').textContent='Play';
    render();
    await bounds(true,token);
    if(token!==transitionId)return;
    currentUtc=frozen;
    await windowAt(currentUtc);
    if(token===transitionId)render();
  } else if(playing) {
    transitionId++;playing=false;$('play').textContent='Play';render();
  } else {
    const token=++transitionId;
    await bounds(true,token);
    if(token!==transitionId)return;
    playing=true;lastFrame=performance.now();$('play').textContent='Pause';render();
  }
};
timeline.oninput=async()=>{
  const fraction=Number(timeline.value)/1000;
  const token=++transitionId;fetchSerial++;pendingUtc=undefined;
  mode='replay';playing=false;socket?.close();$('play').textContent='Play';
  await bounds(true,token);
  if(token!==transitionId||!first||!last)return;
  currentUtc=first.utc+(last.utc-first.utc)*fraction;
  if(!trackCoverage||currentUtc<trackCoverage[0]||currentUtc>trackCoverage[1])
    void loadGroundTrack(currentUtc).catch(err=>{status.textContent=String(err);});
  await windowAt(currentUtc);
  if(token===transitionId)render();
};
cameraInput.onchange=()=>{cameraMode='';render();};
fpsInput.onchange=()=>{frameRate=Math.max(1,Math.min(60,Number(fpsInput.value)||30));fpsInput.value=String(frameRate);};
const updatePlaybackSpeed=()=>{
  const value=speedInput.valueAsNumber;
  if(Number.isFinite(value)&&value>0)
    playbackSpeed=Math.max(0.01,Math.min(1000,value));
};
speedInput.oninput=updatePlaybackSpeed;
speedInput.onchange=()=>{updatePlaybackSpeed();speedInput.value=String(playbackSpeed);};
async function frame() {
  const now=performance.now();const delta=(now-lastFrame)/1000;lastFrame=now;
  if(mode==='replay'&&playing&&last) {
    const token=transitionId;
    // A live run advances the archive head while this viewer is replaying.
    await refreshHead();
    if(token===transitionId&&mode==='replay'&&playing) {
      currentUtc=Math.max(currentUtc,Math.min(last.utc,currentUtc+delta*playbackSpeed));
      if(!samples.length||currentUtc>samples.at(-1)!.utc-2)await windowAt(currentUtc);
      // Archive requests may finish after Pause, scrub, or Live is pressed.
      if(token===transitionId&&mode==='replay'&&playing&&currentUtc>=last.utc) {
        if(archivedOnly) {playing=false;$('play').textContent='Play';}
        else connectLive(); // Follow each new packet at SHIRE's current pace.
      }
    }
  }
  render();
  window.setTimeout(frame,1000/frameRate);
}
window.setTimeout(frame,1000/frameRate);
loadBookmarks().catch(()=>{});
fetch(`${bucket}/run.json`,{credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(meta=>{
  if(meta?.visualHz && 100%Number(meta.visualHz)===0) {
    recordHz=Number(meta.visualHz);
    expectedStep=100/recordHz;
  }
}).catch(()=>{});
if(archivedOnly) {bounds().then(()=>windowAt(currentUtc)).then(render).catch(err=>status.textContent=String(err));}
else connectLive();
