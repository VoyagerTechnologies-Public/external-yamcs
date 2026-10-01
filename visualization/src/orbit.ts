import type {Sample} from './packet';

// Diagnostic two-body forecast from the current 42 truth state. 42's Cwn
// maps inertial coordinates into Earth-fixed coordinates at the sample epoch.
const MU = 3.986004418e14;
const EARTH_RADIUS = 6378137;
const EARTH_RATE = 7.292115e-5;
type Vector = [number, number, number];
export type ForecastPoint = {longitude:number; latitude:number; eclipse:boolean};
const dot=(a:Vector,b:Vector)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const cross=(a:Vector,b:Vector):Vector=>[
  a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const scale=(a:Vector,n:number):Vector=>[a[0]*n,a[1]*n,a[2]*n];
const add=(a:Vector,b:Vector):Vector=>[a[0]+b[0],a[1]+b[1],a[2]+b[2]];
const unit=(a:Vector):Vector=>scale(a,1/Math.hypot(...a));
const mul=(m:number[][],a:Vector):Vector=>m.map(row=>dot(row as Vector,a)) as Vector;
const transpose=(m:number[][],a:Vector):Vector=>[
  m[0][0]*a[0]+m[1][0]*a[1]+m[2][0]*a[2],
  m[0][1]*a[0]+m[1][1]*a[1]+m[2][1]*a[2],
  m[0][2]*a[0]+m[1][2]*a[1]+m[2][2]*a[2]];

export function expectedGroundTrack(s:Sample):ForecastPoint[] {
  const r=s.pos,v=s.vel,R=Math.hypot(...r),v2=dot(v,v);
  const semimajor=1/(2/R-v2/MU);
  const h=unit(cross(r,v));
  const eccentric=scale(add(scale(r,v2-MU/R),scale(v,-dot(r,v))),1/MU);
  const e=Math.hypot(...eccentric);
  if(!Number.isFinite(semimajor)||semimajor<=EARTH_RADIUS||e>=1||!Number.isFinite(e)) return [];
  const p=e>1e-7?unit(eccentric):unit(r);
  const q=unit(cross(h,p));
  const cosE=Math.max(-1,Math.min(1,dot(r,p)/semimajor+e));
  const sinE=dot(r,q)/(semimajor*Math.sqrt(1-e*e));
  const e0=Math.atan2(sinE,cosE),m0=e0-e*Math.sin(e0);
  const meanMotion=Math.sqrt(MU/(semimajor**3));
  const period=2*Math.PI/meanMotion;
  // Cbn maps inertial to body. Convert the measured body Sun direction back
  // to inertial once, then hold it fixed across this one-orbit forecast.
  const [x,y,z,w]=s.q;
  const cbn=[
    [1-2*(y*y+z*z),2*(x*y+z*w),2*(x*z-y*w)],
    [2*(x*y-z*w),1-2*(x*x+z*z),2*(y*z+x*w)],
    [2*(x*z+y*w),2*(y*z-x*w),1-2*(x*x+y*y)]];
  const sun=unit(transpose(cbn,s.sun));
  const result:ForecastPoint[]=[];
  const steps=120;
  for(let i=0;i<=steps;i++) {
    const dt=period*i/steps,m=m0+meanMotion*dt;
    let E=m;
    for(let k=0;k<8;k++) E-=(E-e*Math.sin(E)-m)/(1-e*Math.cos(E));
    const inertial=add(scale(p,semimajor*(Math.cos(E)-e)),
      scale(q,semimajor*Math.sqrt(1-e*e)*Math.sin(E)));
    const fixed0=mul(s.cwn,inertial),angle=EARTH_RATE*dt;
    const fixed:Vector=[Math.cos(angle)*fixed0[0]+Math.sin(angle)*fixed0[1],
      -Math.sin(angle)*fixed0[0]+Math.cos(angle)*fixed0[1],fixed0[2]];
    const radius=Math.hypot(...fixed);
    const longitude=Math.atan2(fixed[1],fixed[0])/(2*Math.PI)+.5;
    const latitude=.5-Math.asin(fixed[2]/radius)/Math.PI;
    const behind=dot(inertial,sun)<0;
    const shadowDistance=Math.hypot(...cross(inertial,sun));
    result.push({longitude,latitude,eclipse:behind&&shadowDistance<EARTH_RADIUS});
  }
  return result;
}
