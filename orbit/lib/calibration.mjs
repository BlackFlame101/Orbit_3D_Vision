import {multiply,parseGLB} from './glb.mjs';

// The baker accepts one primitive in native coordinates, with identity nodes.
export function calibrationMesh(bytes){
  const header=new DataView(bytes);
  const doc=JSON.parse(new TextDecoder().decode(new Uint8Array(bytes,20,header.getUint32(12,true))));
  const mesh=parseGLB(bytes);
  if(mesh.primitives.length!==1||doc.nodes.some(n=>n.matrix||n.scale||n.rotation||n.translation))throw new Error('Calibration requires one native-coordinate mesh.');
  const attr=doc.accessors[doc.meshes[0].primitives[0].attributes.POSITION];
  const view=doc.bufferViews[attr.bufferView];
  if(attr.componentType!==5126||view.byteStride)throw new Error('Unsupported position format');
  const data=new Float32Array(bytes,28+header.getUint32(12,true)+(view.byteOffset||0)+(attr.byteOffset||0),attr.count*3);
  const low=[Infinity,Infinity,Infinity],high=low.map(()=>-Infinity);
  data.forEach((v,i)=>{const k=i%3;low[k]=Math.min(low[k],v);high[k]=Math.max(high[k],v);});
  return {mesh,center:low.map((v,k)=>(v+high[k])/2),half:Math.max(...high.map((v,k)=>v-low[k]))/2};
}

export function pickPoint(model,{yaw,pitch,zoom},aspect,x,y){
  const {positions,indices}=model.mesh.primitives[0];
  const c=Math.cos(yaw),s=Math.sin(yaw),a=Math.cos(pitch),b=Math.sin(pitch);
  const m=multiply([c,0,-s,0,0,1,0,0,s,0,c,0,0,0,0,1],[1,0,0,0,0,a,b,0,0,-b,a,0,0,0,0,1]);
  const px=x*Math.max(1,aspect)/(.82*zoom),py=y/(.82*zoom*Math.min(1,aspect));
  const screen=new Float32Array(positions.length);
  for(let i=0;i<positions.length;i+=3){
    for(let k=0;k<3;k++)screen[i+k]=m[k]*positions[i]+m[4+k]*positions[i+1]+m[8+k]*positions[i+2];
  }
  let nearest=-Infinity, point=null;
  for(let i=0;i<indices.length;i+=3){
    const u=indices[i]*3,v=indices[i+1]*3,w=indices[i+2]*3;
    const ax=screen[u]-screen[w],ay=screen[u+1]-screen[w+1],bx=screen[v]-screen[w],by=screen[v+1]-screen[w+1];
    const det=ax*by-ay*bx;
    if(Math.abs(det)<1e-12)continue;
    const dx=px-screen[w],dy=py-screen[w+1],p=(dx*by-dy*bx)/det,q=(ax*dy-ay*dx)/det,r=1-p-q;
    if(Math.min(p,q,r)<0)continue;
    const depth=p*screen[u+2]+q*screen[v+2]+r*screen[w+2];
    if(depth>nearest){
      nearest=depth;point=model.center.map((n,k)=>n+model.half*(p*positions[u+k]+q*positions[v+k]+r*positions[w+k]));
    }
  }
  return point;
}
