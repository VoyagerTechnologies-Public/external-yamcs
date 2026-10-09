/** EPS FSW engineering telemetry, shared by live subscriptions and archive replay. */
export const batteryName = '/EPS/BATTERY_VOLTAGE';
export const switchNames = Array.from({length:8}, (_, i) => `/EPS/SWITCH_${i}_STATE`);
export const epsNames = [batteryName, ...switchNames];
export const historyMillis = 10 * 60 * 1000;
export const maxHistoryMillis = 120 * 60 * 1000;
export const maxHistorySamples = 7200;
export type EngineeringValue = {type?:string; floatValue?:number; doubleValue?:number;
  stringValue?:string; sint64Value?:string; uint32Value?:number};
export type ParameterValue = {id?:{name:string}; numericId?:number; engValue?:EngineeringValue;
  generationTime?:string; acquisitionStatus?:string};
export type Reading = {time:number; value:number|string|undefined};
export type ParameterData = {mapping?:Record<string,{name:string}>; values?:ParameterValue[];
  invalid?:{name:string}[]};

export function reading(name:string, parameter:ParameterValue):Reading|undefined {
  const time=Date.parse(parameter.generationTime || '');
  if(!Number.isFinite(time)) return;
  let value:number|string|undefined;
  if(!parameter.acquisitionStatus || parameter.acquisitionStatus==='ACQUIRED') {
    const eng=parameter.engValue;
    if(name===batteryName) {
      const volts=eng?.doubleValue ?? eng?.floatValue;
      if(typeof volts==='number' && Number.isFinite(volts) && volts>=0 && volts<=32) value=volts;
    } else if(switchNames.includes(name)) {
      if(eng?.stringValue==='ON' || eng?.stringValue==='OFF') value=eng.stringValue;
    }
  }
  return {time,value};
}

export class EpsTelemetry {
  private mapping=new Map<number,string>();
  readonly history=new Map<string,Reading[]>();
  revision=0;
  reset() {this.mapping.clear();this.history.clear();this.revision++;}
  ingest(data:ParameterData) {
    for(const [id,parameter] of Object.entries(data.mapping || {})) this.mapping.set(Number(id),parameter.name);
    for(const parameter of data.values || []) {
      const name=parameter.id?.name ?? this.mapping.get(parameter.numericId!);
      if(name && epsNames.includes(name)) this.add(name,parameter);
    }
    for(const invalid of data.invalid || []) {this.history.delete(invalid.name);this.revision++;}
  }
  add(name:string, parameter:ParameterValue) {
    const point=reading(name,parameter);
    if(!point) return;
    const points=this.history.get(name) || [];
    let lo=0,hi=points.length;
    while(lo<hi) {const mid=(lo+hi)>>1;if(points[mid].time<point.time) lo=mid+1;else hi=mid;}
    if(points[lo]?.time===point.time) points[lo]=point;else points.splice(lo,0,point);
    const cutoff=points.at(-1)!.time-maxHistoryMillis;
    let expired=0;while(expired<points.length && points[expired].time<cutoff) expired++;
    points.splice(0,Math.max(expired,points.length-maxHistorySamples));
    this.history.set(name,points);this.revision++;
  }
  latest(name:string, at:number):Reading|undefined {
    const points=this.history.get(name) || [];
    for(let i=points.length-1;i>=0;i--) if(points[i].time<=at) return points[i];
  }
  battery(at:number, windowMillis=historyMillis):Reading[] {
    return (this.history.get(batteryName) || []).filter(p=>p.time<=at && p.time>=at-windowMillis);
  }
}

export function switchLabel(index:number, description?:string):{label:string; detail:string} {
  const detail=description?.trim() || `Switch ${index} · mapping unavailable`;
  const colon=description?.indexOf(':') ?? -1;
  const configured=colon>=0?description!.slice(0,colon).trim():description?.trim();
  const devices=colon>=0?description!.slice(colon+1).split(/,\s*(?:passive load\b|[0-9.]+\s*V\b|startup\b)/)[0].trim():'';
  const mapped=devices && devices!=='unloaded' && devices!=='no device';
  const base=configured || `Switch ${index}`;
  const label=mapped ? (/^Switch \d+$/i.test(base)?devices:
    base.toUpperCase()===devices.toUpperCase()?base:`${base} · ${devices}`) : base;
  return {label,detail};
}

/** Bounded battery history and switch reports at or before the cursor. */
export async function fetchEpsHistory(at:number, signal:AbortSignal,
    request:typeof fetch=fetch, windowMillis=historyMillis, names=epsNames):Promise<EpsTelemetry> {
  const telemetry=new EpsTelemetry();
  if(!Number.isFinite(windowMillis) || windowMillis<60000 || windowMillis>maxHistoryMillis)
    throw new Error("EPS history must be between 1 and 120 minutes");
  await Promise.all(names.map(async name=>{
    const query=new URLSearchParams({start:new Date(at-windowMillis).toISOString(),
      stop:new Date(at+1).toISOString(), order:'desc',limit:name===batteryName?'600':'1',
      norealtime:'true',noreplay:'true'});
    let count=0, pages=0;
    do {
      const response=await request(`/api/archive/shire/parameters${name}?${query}`,{credentials:'same-origin',signal});
      if(!response.ok) throw new Error(`EPS archive ${response.status}`);
      const body=await response.json() as {parameter?:ParameterValue[];continuationToken?:string};
      // Defend against future samples even if a server/cache disregards the bounds.
      for(const parameter of body.parameter || []) {
        if(Date.parse(parameter.generationTime || '')<=at) telemetry.add(name,parameter);
      }
      count+=(body.parameter || []).length;pages++;
      if(name!==batteryName || !body.continuationToken || count>=maxHistorySamples || pages>=12) break;
      query.set("next",body.continuationToken);
    } while(!signal.aborted);
    signal.throwIfAborted();
  }));
  return telemetry;
}
