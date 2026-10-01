/** SHIRE visualization packet v1. All multibyte values are little-endian. */
export interface Sample {
  run: string; spacecraft: number; sequence: number; sim: number; utc: number;
  pos: [number,number,number]; vel: [number,number,number];
  q: [number,number,number,number]; sun: [number,number,number];
  rates: [number,number,number]; cwn: number[][]; eclipse: boolean;
}
export function decode(base64: string): Sample {
  const raw = atob(base64);
  if (raw.length !== 256) throw new Error(`Visualization packet size ${raw.length}`);
  const buf = Uint8Array.from(raw, c => c.charCodeAt(0)).buffer;
  const v = new DataView(buf);
  if (v.getUint32(0, true) !== 0x31564853 || v.getUint16(4, true) !== 1)
    throw new Error('Unsupported visualization packet');
  const f = (offset: number) => v.getFloat64(offset, true);
  const vec = (offset: number): [number,number,number] => [f(offset), f(offset+8), f(offset+16)];
  const sample: Sample = {
    run: Array.from(new Uint8Array(buf, 8, 16), x => x.toString(16).padStart(2,'0')).join(''),
    spacecraft: v.getUint32(24,true), sequence: Number(v.getBigUint64(28,true)),
    sim: f(36), utc: f(44), pos: vec(52), vel: vec(76),
    q: [f(100),f(108),f(116),f(124)], sun: vec(132), rates: vec(156),
    cwn: [vec(180),vec(204),vec(228)], eclipse: !!v.getUint32(252,true)
  };
  if (![sample.sim,sample.utc,...sample.pos,...sample.vel,...sample.q,...sample.sun,
        ...sample.rates,...sample.cwn.flat()].every(Number.isFinite))
    throw new Error('Non-finite visualization state');
  return sample;
}
export const j2000Millis = 946728000000;
export const sampleDate = (s: Sample) => new Date(j2000Millis + s.utc * 1000);
