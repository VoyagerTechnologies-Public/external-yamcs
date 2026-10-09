import {test} from 'node:test';
import assert from 'node:assert/strict';
import {batteryName, switchNames, epsNames, EpsTelemetry, reading, switchLabel,
  fetchEpsHistory, historyMillis, maxHistoryMillis, maxHistorySamples, type ParameterValue} from '../src/eps.ts';
const epoch=Date.parse('2026-10-08T12:00:00Z');
const volts=(value:number,time=epoch):ParameterValue=>({generationTime:new Date(time).toISOString(),
  acquisitionStatus:'ACQUIRED',engValue:{type:'DOUBLE',doubleValue:value}});
const state=(value:string,time=epoch):ParameterValue=>({generationTime:new Date(time).toISOString(),
  engValue:{type:'ENUMERATED',stringValue:value,sint64Value:value==='ON'?'1':'0'}});

test('uses calibrated volts and enumeration labels from FSW telemetry',()=>{
  assert.deepEqual(reading(batteryName,volts(27.5)),{time:epoch,value:27.5});
  assert.equal(reading(batteryName,{...volts(1),engValue:{floatValue:26.1}})?.value,26.1);
  for(const name of switchNames) for(const value of ['ON','OFF']) assert.equal(reading(name,state(value))?.value,value);
});
test('invalid, expired, missing and malformed readings never appear as OFF or zero volts',()=>{
  for(const acquisitionStatus of ['EXPIRED','INVALID','NOT_RECEIVED']) {
    assert.equal(reading(batteryName,{...volts(28),acquisitionStatus})?.value,undefined);
    assert.equal(reading(switchNames[0],{...state('ON'),acquisitionStatus})?.value,undefined);
  }
  for(const value of [NaN,Infinity,-1,33]) assert.equal(reading(batteryName,volts(value))?.value,undefined);
  assert.equal(reading(batteryName,{generationTime:'bad'}),undefined);
  assert.equal(reading(batteryName,{generationTime:new Date(epoch).toISOString()})?.value,undefined);
  assert.equal(reading(switchNames[0],state('UNKNOWN'))?.value,undefined);
});
test('subscription mappings are applied before values and cleared on reconnect',()=>{
  const telemetry=new EpsTelemetry();
  telemetry.ingest({mapping:{7:{name:batteryName},8:{name:switchNames[0]}},values:[
    {...volts(28),numericId:7},{...state('ON'),numericId:8}]});
  assert.equal(telemetry.latest(batteryName,epoch)?.value,28);
  assert.equal(telemetry.latest(switchNames[0],epoch)?.value,'ON');
  telemetry.reset();telemetry.ingest({values:[{...volts(28),numericId:7}]});
  assert.equal(telemetry.history.size,0);
});
test('fully qualified updates work and unrelated or inaccessible parameters are ignored',()=>{
  const telemetry=new EpsTelemetry();
  telemetry.ingest({values:[{...volts(28),id:{name:batteryName}}, {...volts(1),id:{name:'/OTHER/VALUE'}}]});
  assert.equal(telemetry.history.size,1);
  telemetry.ingest({invalid:[{name:batteryName}]});assert.equal(telemetry.history.size,0);
});
test('replay selects the last reading before cursor without looking into the future',()=>{
  const telemetry=new EpsTelemetry();
  telemetry.add(switchNames[0],state('OFF',epoch+2000));
  telemetry.add(switchNames[0],state('ON',epoch));
  assert.equal(telemetry.latest(switchNames[0],epoch-1),undefined);
  assert.equal(telemetry.latest(switchNames[0],epoch+1999)?.value,'ON');
  assert.equal(telemetry.latest(switchNames[0],epoch+2000)?.value,'OFF');
});
test('same-timestamp expiration replaces state; invalid points preserve graph gaps',()=>{
  const telemetry=new EpsTelemetry();
  telemetry.add(batteryName,volts(28));
  telemetry.add(batteryName,{...volts(28),acquisitionStatus:'EXPIRED'});
  assert.equal(telemetry.latest(batteryName,epoch)?.value,undefined);
  assert.equal(telemetry.battery(epoch).length,1);
});
test('history is bounded by both sample count and simulation-time window',()=>{
  const telemetry=new EpsTelemetry();
  for(let i=0;i<maxHistorySamples+100;i++) telemetry.add(batteryName,volts(28,epoch+i));
  assert.equal(telemetry.battery(epoch+maxHistorySamples+100,maxHistoryMillis).length,maxHistorySamples);
  telemetry.add(batteryName,volts(26,epoch+2*maxHistoryMillis+1000));
  assert.equal(telemetry.battery(epoch+2*maxHistoryMillis+1000).length,1);
  assert.equal(telemetry.history.get(batteryName)?.length,1);
  assert.equal(telemetry.battery(epoch+3*maxHistoryMillis+1001).length,0);
});
test('switch labels come from resolved MDB metadata with safe unmapped defaults',()=>{
  assert.deepEqual(switchLabel(4,'ADCS rail: ADCS, 12 V, startup ON'),{
    label:'ADCS rail · ADCS',detail:'ADCS rail: ADCS, 12 V, startup ON'});
  assert.deepEqual(switchLabel(3),{label:'Switch 3',detail:'Switch 3 · mapping unavailable'});
  assert.equal(switchLabel(2,'Rail: DEMO, RADIO, 24 V, startup ON').label,'Rail · DEMO, RADIO');
});
test('DRM connected devices appear in generic rail labels and passive-only loads stay named',()=>{
  for(const [index,device] of [[0,'DEMO'],[4,'ADCS'],[6,'RADIO']] as const)
    assert.equal(switchLabel(index,`Switch ${index}: ${device}, passive load 0.0 W, 12.0 V, startup ON`).label,device);
  assert.equal(switchLabel(5,'Load bank: no device, passive load 20.0 W, 12.0 V, startup OFF').label,'Load bank');
  assert.equal(switchLabel(1,'Switch 1: unloaded, passive load 0 W, 3.3 V, startup OFF').label,'Switch 1');
  assert.equal(switchLabel(2,'Switch 2: DEMO, RADIO, passive load 0 W, 5 V, startup ON').label,'DEMO, RADIO');
  assert.equal(switchLabel(0,'DEMO: DEMO, passive load 0 W, 3.3 V, startup ON').label,'DEMO');
});
test('archive queries use exclusive stop +1ms, bounded descending history and no live cache',async()=>{
  const urls:string[]=[];const signal=new AbortController().signal;
  const request:typeof fetch=async(input,init)=>{
    const url=new URL(String(input),'http://localhost');urls.push(url.pathname);
    assert.equal(init?.signal,signal);
    assert.equal(url.searchParams.get('stop'),new Date(epoch+1).toISOString());
    assert.equal(url.searchParams.get('start'),new Date(epoch-historyMillis).toISOString());
    assert.equal(url.searchParams.get('order'),'desc');
    assert.equal(url.searchParams.get('norealtime'),'true');
    assert.equal(url.searchParams.get('noreplay'),'true');
    const battery=url.pathname.endsWith('BATTERY_VOLTAGE');
    assert.equal(url.searchParams.get('limit'),battery?'600':'1');
    return new Response(JSON.stringify({parameter:battery?[volts(29,epoch+1),volts(28)]:[state('ON')]}));
  };
  const telemetry=await fetchEpsHistory(epoch,signal,request);
  assert.equal(urls.length,epsNames.length);
  assert.equal(telemetry.latest(batteryName,epoch)?.value,28);
  assert.equal(telemetry.battery(epoch+1).length,1);
  for(const name of switchNames) assert.equal(telemetry.latest(name,epoch)?.value,'ON');
});
test('empty archives remain unknown, failed requests and cancellations propagate',async()=>{
  const controller=new AbortController();
  const empty=await fetchEpsHistory(epoch,controller.signal,async()=>new Response('{}'));
  assert.equal(empty.history.size,0);
  await assert.rejects(fetchEpsHistory(epoch,controller.signal,async()=>new Response('',{status:503})),/EPS archive 503/);
  controller.abort();
  await assert.rejects(fetchEpsHistory(epoch,controller.signal,async(_input,init)=>{
    init?.signal?.throwIfAborted();return new Response('{}');
  }),{name:'AbortError'});
});
test('custom history windows paginate while keeping samples on the past side of the cursor',async()=>{
  let calls=0;
  const request:typeof fetch=async input=>{
    const query=new URL(String(input),'http://localhost').searchParams;
    assert.equal(query.get('start'),new Date(epoch-60*60000).toISOString());
    calls++;
    assert.equal(query.get('next'),calls===1?null:'second-page');
    return new Response(JSON.stringify({parameter:[volts(28,epoch-(calls-1)*600000)],
      ...(calls===1?{continuationToken:'second-page'}:{})}));
  };
  const history=await fetchEpsHistory(epoch,new AbortController().signal,request,60*60000,[batteryName]);
  assert.equal(calls,2);
  assert.equal(history.battery(epoch,60*60000).length,2);
  assert.equal(history.battery(epoch,60000).length,1);
  for(const minutes of [0,121,NaN,Infinity]) await assert.rejects(
    fetchEpsHistory(epoch,new AbortController().signal,request,minutes*60000),/1 and 120 minutes/);
});
test('archive pagination stays bounded even if a server repeats a continuation token',async()=>{
  let calls=0;
  await fetchEpsHistory(epoch,new AbortController().signal,async()=>{
    calls++;return new Response(JSON.stringify({continuationToken:'again'}));
  },historyMillis,[batteryName]);
  assert.equal(calls,12);
});
