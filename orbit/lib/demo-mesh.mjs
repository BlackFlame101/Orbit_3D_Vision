// Offline procedural preview only; replace with a GLB viewer in Gate B.
function mesh(detail=1){const vertices=[],faces=[];const N=64,M=24;const ring=(r,y)=>{const start=vertices.length;for(let j=0;j<N;j++){const a=j/N*Math.PI*2;vertices.push([r*Math.cos(a),y,r*Math.sin(a)]);}return start;};
 const profile=[[0,-1],[.73,-1],[.87,-.94],[.91,-.8],[.95,.85],[.94,.98],[.89,1.02],[.83,.98],[.84,.84],[.8,-.77],[0,-.77]];
 for(let i=0;i<profile.length;i++)ring(...profile[i]);
 for(let i=0;i<profile.length-1;i++)for(let j=0;j<N;j++){const a=i*N+j,b=i*N+(j+1)%N,c=b+N,d=a+N;faces.push([a,b,c],[a,c,d]);}
 const base=vertices.length;for(let i=0;i<=M;i++){const t=-Math.PI/2+i/M*Math.PI;for(let j=0;j<12;j++){const p=j/12*Math.PI*2,r=.14+(detail>1?.015:0);vertices.push([.86+.65*Math.cos(t)+r*Math.cos(p)*Math.cos(t),.03+.72*Math.sin(t)+r*Math.cos(p)*Math.sin(t),r*Math.sin(p)]);}}
 for(let i=0;i<M;i++)for(let j=0;j<12;j++){const a=base+i*12+j,b=base+i*12+(j+1)%12;faces.push([a,b,b+12],[a,b+12,a+12]);}return{vertices,faces};}

export function demoOBJ(detail) {
 const m=mesh(detail);
 return ['# Orbit procedural demo mesh - not an image reconstruction',...m.vertices.map(v=>'v '+v.join(' ')),...m.faces.map(f=>'f '+f.map(i=>i+1).join(' '))].join('\n');
}
export function drawDemo(canvas, {yaw,pitch,zoom,wire,disagreement,detail,compareDetail,split=50}) {
 const ctx=canvas.getContext('2d');if(!ctx)return false;
 const w=canvas.clientWidth,h=canvas.clientHeight,dpr=Math.min(window.devicePixelRatio||1,2);
 canvas.width=w*dpr;canvas.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);
 ctx.clearRect(0,0,w,h);if(!w||!h)return true;
function project(v,w,h){const [x,y,z]=v,c=Math.cos(yaw),s=Math.sin(yaw),xx=x*c+z*s,zz=-x*s+z*c,yy=y*Math.cos(pitch)-zz*Math.sin(pitch),depth=y*Math.sin(pitch)+zz*Math.cos(pitch),scale=Math.min(w*.24,h*.29)*zoom;return[w/2+xx*scale,h*.51-yy*scale,depth];}
function renderModel(detail,w,h){const m=mesh(detail),p=m.vertices.map(v=>project(v,w,h));const ordered=m.faces.map(f=>({f,z:f.reduce((s,i)=>s+p[i][2],0)/3})).sort((a,b)=>a.z-b.z);for(const{f}of ordered){const a=p[f[0]],b=p[f[1]],c=p[f[2]];if((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])>0)continue;const raw=m.vertices[f[0]],shade=Math.round(73+18*Math.sin(Math.atan2(raw[2],raw[0])+yaw+.6)+5*raw[1]);ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.lineTo(c[0],c[1]);ctx.closePath();ctx.fillStyle=disagreement?`hsl(${Math.round(35+105*(raw[2]+1)/2)},28%,${shade-12}%)`:`hsl(47,13%,${shade}%)`;if(!wire){ctx.fill();ctx.strokeStyle=ctx.fillStyle;ctx.lineWidth=.4;ctx.stroke();}else{ctx.strokeStyle='#929c7c';ctx.lineWidth=.45;ctx.stroke();}}}

 if(compareDetail!==null){
  const boundary=w*split/100;
  ctx.save();ctx.beginPath();ctx.rect(0,0,boundary,h);ctx.clip();renderModel(compareDetail,w,h);ctx.restore();
  ctx.save();ctx.beginPath();ctx.rect(boundary,0,w-boundary,h);ctx.clip();renderModel(detail,w,h);ctx.restore();
  ctx.strokeStyle='#7a8961';ctx.beginPath();ctx.moveTo(boundary,85);ctx.lineTo(boundary,h-65);ctx.stroke();
 }else renderModel(detail,w,h);
 return true;
}
