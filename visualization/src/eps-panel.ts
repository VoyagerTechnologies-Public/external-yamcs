import {batteryName, epsNames, switchNames, switchLabel, EpsTelemetry, fetchEpsHistory,
  historyMillis, type ParameterData} from './eps.ts';

export class EpsPanel {
  private live=new EpsTelemetry();
  private archived=new EpsTelemetry();
  private mode='';
  private cursor=0;
  private requested=NaN;
  private lastRequest=0;
  private controller:AbortController|undefined;
  private error='';
  private signature='';
  private receivedAt=0;
  private windowMillis=historyMillis;
  private liveController:AbortController|undefined;
  private backfillNeeded=true;
  private backfilled=false;
  private rows:{label:HTMLElement; state:HTMLElement}[]=[];
  private note:HTMLElement;
  private voltage:HTMLElement;
  private chart:HTMLCanvasElement;
  private range:HTMLElement;
  private body:HTMLElement;
  constructor(element:HTMLElement) {
    this.note=element.querySelector('#eps-status')!;
    this.voltage=element.querySelector('#eps-voltage')!;
    this.chart=element.querySelector('#eps-battery')!;
    this.range=element.querySelector('#eps-range')!;
    const toggle=element.querySelector<HTMLButtonElement>('#eps-toggle')!;
    const body=element.querySelector<HTMLElement>('#eps-body')!;this.body=body;
    toggle.onclick=()=>{
      body.hidden=!body.hidden;toggle.textContent=body.hidden?'+':'−';
      toggle.setAttribute('aria-expanded',String(!body.hidden));
      toggle.setAttribute('aria-label',body.hidden?'Expand EPS':'Minimize EPS');
      this.signature='';this.draw();
    };
    const minutes=element.querySelector<HTMLInputElement>('#eps-history-minutes')!;
    minutes.onchange=()=>{
      if(!minutes.checkValidity()) {minutes.reportValidity();return;}
      this.windowMillis=minutes.valueAsNumber*60000;
      this.controller?.abort();this.liveController?.abort();
      this.requested=NaN;this.lastRequest=-Infinity;this.backfillNeeded=true;this.signature='';
      this.update(this.mode==='replay'?'replay':'live',this.cursor);
    };
    const switches=element.querySelector('#eps-switches')!;
    switchNames.forEach((name,index)=>{
      const row=document.createElement('div');row.className='eps-switch';
      const label=document.createElement('span');label.className='eps-label';label.textContent=`${index} · Switch ${index}`;
      const state=document.createElement('strong');state.textContent='—';
      row.append(label,state);switches.append(row);this.rows.push({label,state});
      void fetch(`/api/mdb/shire/parameters${name}`,{credentials:'same-origin'}).then(async response=>{
        if(!response.ok) throw new Error('Mapping unavailable');
        return response.json() as Promise<{shortDescription?:string}>;
      }).then(info=>{
        const mapping=switchLabel(index,info.shortDescription);
        label.textContent=`${index} · ${mapping.label}`;row.title=mapping.detail;
      }).catch(()=>{row.title=switchLabel(index).detail;});
    });
  }
  subscribe(socket:WebSocket) {
    // Numeric identifiers belong to this subscription only, including after reconnects.
    this.liveController?.abort();this.backfillNeeded=true;this.backfilled=false;
    this.live.reset();this.error='';this.signature='';
    socket.send(JSON.stringify({type:'parameters',id:2,options:{instance:'shire',processor:'realtime',
      id:epsNames.map(name=>({name})),abortOnInvalid:false,sendFromCache:true,updateOnExpiration:true}}));
  }
  receive(data:ParameterData) {
    this.live.ingest(data);
    if(data.values?.length) {this.receivedAt=performance.now();this.error='';}
  }
  subscriptionError(message:string) {this.error=message;this.signature='';}
  update(mode:'live'|'replay', at:number) {
    const changed=mode!==this.mode;
    if(changed) {
      this.mode=mode;this.controller?.abort();this.archived.reset();this.error='';
      this.requested=NaN;this.signature='';
    }
    this.cursor=at;
    const liveTime=this.live.latest(batteryName,Infinity)?.time;
    if(mode==='live' && liveTime && this.backfillNeeded) {
      this.backfillNeeded=false;this.liveController?.abort();
      const controller=new AbortController();this.liveController=controller;
      void fetchEpsHistory(liveTime,controller.signal,fetch,this.windowMillis,[batteryName]).then(telemetry=>{
        if(controller.signal.aborted || controller!==this.liveController) return;
        // Cache older archive samples without replacing newer subscription status/value.
        const existing=new Set(this.live.history.get(batteryName)?.map(p=>p.time));
        for(const point of telemetry.history.get(batteryName) || []) if(!existing.has(point.time))
          this.live.add(batteryName,{generationTime:new Date(point.time).toISOString(),
            engValue:typeof point.value==='number'?{doubleValue:point.value}:undefined});
        this.backfilled=true;this.signature='';this.draw();
      }).catch(()=>{ /* Live readings remain available when the archive is not indexed yet. */ });
    }
    if(mode==='replay' && at>0 && (at!==this.requested || !!this.error) &&
        (changed || performance.now()-this.lastRequest>2000)) {
      this.controller?.abort();const controller=new AbortController();this.controller=controller;
      this.requested=at;this.lastRequest=performance.now();this.error='';
      void fetchEpsHistory(at,controller.signal,fetch,this.windowMillis).then(telemetry=>{
        if(controller!==this.controller || controller.signal.aborted || this.mode!=='replay') return;
        this.archived=telemetry;this.signature='';this.draw();
      }).catch(error=>{
        if(controller!==this.controller || controller.signal.aborted || this.mode!=='replay') return;
        this.error=String(error);this.archived.reset();this.signature='';this.draw();
      });
    }
    this.draw();
  }
  private draw() {
    const telemetry=this.mode==='live'?this.live:this.archived;
    // Live uses FSW generation timestamps; replay uses the visualization UTC cursor.
    const at=this.mode==='live'?Math.max(0,...[...telemetry.history.values()].map(p=>p.at(-1)?.time || 0)):this.cursor;
    const readings=switchNames.map(name=>telemetry.latest(name,at));
    const battery=telemetry.latest(batteryName,at);
    const stale=this.mode==='live' && (!!this.error || !this.receivedAt || performance.now()-this.receivedAt>15000);
    const signature=JSON.stringify([this.mode,Math.floor(at/1000),readings,battery,telemetry.revision,this.error,stale,this.windowMillis,this.backfilled]);
    if(signature===this.signature) return;this.signature=signature;
    readings.forEach((point,i)=>{
      const valid=!stale && point?.value!==undefined && at-point.time<=15000;
      this.rows[i].state.textContent=valid?String(point.value):'—';
      this.rows[i].state.className=valid?`eps-${String(point.value).toLowerCase()}`:'eps-unknown';
      this.rows[i].state.title=point?`Reported ${new Date(point.time).toISOString()}${valid?'':' · unavailable or stale'}`:'No FSW reading';
    });
    const valid=!stale && battery?.value!==undefined && at-battery.time<=15000;
    this.voltage.textContent=valid?`${Number(battery!.value).toFixed(2)} V`:'— V';
    this.note.textContent=this.error || (battery?`${this.mode==='live'?'FSW':'Archived FSW'} · ${new Date(battery.time).toISOString()}${valid?'':' · stale / unavailable'}`:
      this.mode==='replay'?'No EPS telemetry at this time':'Waiting for EPS FSW telemetry…');
    if(this.body.hidden) return;
    const points=telemetry.battery(at,this.windowMillis);
    const ctx=this.chart.getContext('2d');if(!ctx) return;
    const width=this.chart.width,height=this.chart.height;
    ctx.clearRect(0,0,width,height);
    const values=points.filter(p=>typeof p.value==='number');
    if(!values.length) {this.range.textContent='No battery history available';return;}
    const min=Math.max(0,Math.min(...values.map(p=>Number(p.value)))-.25);
    const max=Math.min(32,Math.max(...values.map(p=>Number(p.value)))+.25);
    const from=at-this.windowMillis,span=this.windowMillis;
    ctx.font='11px system-ui';ctx.fillStyle='#b9cbdc';ctx.strokeStyle='#395978';
    for(let i=0;i<3;i++) {
      const y=12+i*(height-30)/2;
      ctx.fillText(`${(max-(max-min)*i/2).toFixed(2)}`,2,y+4);
      ctx.beginPath();ctx.moveTo(42,y);ctx.lineTo(width-8,y);ctx.stroke();
    }
    ctx.strokeStyle='#71efff';ctx.lineWidth=2;ctx.beginPath();
    let previous:number|undefined;
    for(const point of points) {
      if(typeof point.value!=='number') {previous=undefined;continue;}
      const x=42+(point.time-from)/span*(width-50);
      const y=12+(max-point.value)/(max-min)*(height-30);
      if(previous===undefined || point.time-previous>15000) ctx.moveTo(x,y);else ctx.lineTo(x,y);
      previous=point.time;
    }
    ctx.stroke();
    // A single telemetry sample remains visible before a line can be drawn.
    for(const point of values) {
      ctx.beginPath();ctx.arc(42+(point.time-from)/span*(width-50),
        12+(max-Number(point.value))/(max-min)*(height-30),1.5,0,Math.PI*2);ctx.fillStyle='#71efff';ctx.fill();
    }
    const clock=(time:number)=>new Date(time).toISOString().slice(11,19);
    this.range.textContent=`${clock(from)} – ${clock(at)} UTC · ${values.length} samples`;
    this.chart.setAttribute('aria-label',`Battery voltage history: ${values.length} samples, ${min.toFixed(2)} to ${max.toFixed(2)} volts`);
  }
}
