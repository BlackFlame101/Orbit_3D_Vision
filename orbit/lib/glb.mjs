// GLB 2 loader for the project's uncompressed, untextured Hunyuan geometry.
// No network buffers, scripts, decoder downloads, or inference dependencies.
const COMPONENTS={5120:[Int8Array,1],5121:[Uint8Array,1],5122:[Int16Array,2],5123:[Uint16Array,2],5125:[Uint32Array,4],5126:[Float32Array,4]};
const WIDTHS={SCALAR:1,VEC2:2,VEC3:3,VEC4:4,MAT4:16};
export function parseGLB(buffer){
  const view=new DataView(buffer);
  if(buffer.byteLength<20||view.getUint32(0,true)!==0x46546c67||view.getUint32(4,true)!==2||view.getUint32(8,true)!==buffer.byteLength)throw new Error('Not a complete GLB 2 file.');
  let json,bin,offset=12;
  while(offset+8<=buffer.byteLength){const length=view.getUint32(offset,true),kind=view.getUint32(offset+4,true);offset+=8;if(offset+length>buffer.byteLength||length%4)throw new Error('Invalid GLB chunk.');if(kind===0x4e4f534a)json=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,offset,length)));if(kind===0x004e4942)bin=buffer.slice(offset,offset+length);offset+=length;}
  if(offset!==buffer.byteLength||!json||!bin||json.asset?.version!=='2.0')throw new Error('Missing GLB geometry.');
  if(json.extensionsRequired?.length||json.buffers?.some(b=>b.uri)||json.buffers?.length!==1)throw new Error('Only self-contained, uncompressed GLB fixtures are supported.');
  function accessor(index){
    const a=json.accessors?.[index],bv=json.bufferViews?.[a?.bufferView],format=COMPONENTS[a?.componentType],width=WIDTHS[a?.type];
    if(!a||!bv||!format||!width||a.sparse||bv.buffer!==0)throw new Error('Unsupported GLB accessor.');
    const [Type,bytes]=format,stride=bv.byteStride||bytes*width,start=(bv.byteOffset||0)+(a.byteOffset||0),count=a.count;
    const last=(a.byteOffset||0)+(count?((count-1)*stride+width*bytes):0);
    if(!Number.isSafeInteger(count)||count<0||count>10_000_000||stride<width*bytes||last>bv.byteLength||start+Math.max(0,last-(a.byteOffset||0))>bin.byteLength)throw new Error('Invalid GLB accessor bounds.');
    const output=new Float32Array(count*width),dv=new DataView(bin),reader={5120:'getInt8',5121:'getUint8',5122:'getInt16',5123:'getUint16',5125:'getUint32',5126:'getFloat32'}[a.componentType];
    for(let i=0;i<count;i++)for(let k=0;k<width;k++){let value=dv[reader](start+i*stride+k*bytes,true);if(a.normalized&&a.componentType!==5126){const max=a.componentType===5120?127:a.componentType===5122?32767:a.componentType===5121?255:a.componentType===5123?65535:4294967295;value=Math.max(-1,value/max);}if(!Number.isFinite(value))throw new Error('Nonfinite geometry value.');output[i*width+k]=value;}
    return {data:output,width,count,componentType:a.componentType};
  }
  const primitives=[];
  function visit(index,parent,ancestry){
    if(ancestry.has(index))throw new Error('Cyclic GLB scene.');
    const node=json.nodes?.[index];if(!node)throw new Error('Invalid scene node.');
    const next=new Set(ancestry);next.add(index);const transform=multiply(parent,nodeMatrix(node));
    if(node.skin!==undefined)throw new Error('Skinned GLBs are not supported in this fixture viewer.');
    if(node.mesh!==undefined){const mesh=json.meshes?.[node.mesh];if(!mesh)throw new Error('Invalid mesh.');for(const p of mesh.primitives){
      if((p.mode??4)!==4||p.targets||p.extensions)throw new Error('Only uncompressed triangle geometry is supported.');
      const pos=accessor(p.attributes.POSITION);if(pos.width!==3)throw new Error('Invalid positions.');
      const positions=new Float32Array(pos.data.length);
      for(let i=0;i<pos.count;i++){const x=pos.data[i*3],y=pos.data[i*3+1],z=pos.data[i*3+2];for(let k=0;k<3;k++)positions[i*3+k]=transform[k]*x+transform[4+k]*y+transform[8+k]*z+transform[12+k];}
      const idx=p.indices===undefined?null:accessor(p.indices);
      if(idx&&(idx.width!==1||![5121,5123,5125].includes(idx.componentType)))throw new Error('Invalid triangle indices.');
      const indices=idx?Uint32Array.from(idx.data):Uint32Array.from({length:pos.count},(_,i)=>i);
      if(indices.length%3||indices.some(i=>i>=pos.count))throw new Error('Invalid triangle indices.');
      // Recompute normals after scene transforms, including nonuniform scale.
      const normals=new Float32Array(positions.length);
      for(let i=0;i<indices.length;i+=3){const a=indices[i]*3,b=indices[i+1]*3,c=indices[i+2]*3;const u=[0,1,2].map(k=>positions[b+k]-positions[a+k]),v=[0,1,2].map(k=>positions[c+k]-positions[a+k]);const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];for(const j of [a,b,c])for(let k=0;k<3;k++)normals[j+k]+=n[k];}
      for(let i=0;i<normals.length;i+=3){const length=Math.hypot(normals[i],normals[i+1],normals[i+2])||1;for(let k=0;k<3;k++)normals[i+k]/=length;}
      const material=json.materials?.[p.material],pbr=material?.pbrMetallicRoughness;
      if(pbr?.baseColorTexture||material?.normalTexture||material?.extensions)throw new Error('Textured/material-extension GLBs require the later general-purpose viewer. Use a cached geometry fixture.');
      const color=pbr?.baseColorFactor||[.72,.75,.65,1];
      primitives.push({positions,normals,indices,color});
    }}
    for(const child of node.children||[])visit(child,transform,next);
  }
  const scene=json.scenes?.[json.scene??0];if(!scene)throw new Error('GLB scene is missing.');
  for(const node of scene.nodes||[])visit(node,identity(),new Set());
  if(!primitives.length)throw new Error('No triangle meshes found.');
  const min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];
  for(const p of primitives)for(let i=0;i<p.positions.length;i++) {const k=i%3;min[k]=Math.min(min[k],p.positions[i]);max[k]=Math.max(max[k],p.positions[i]);}
  const center=min.map((v,i)=>(v+max[i])/2),size=Math.max(...max.map((v,i)=>v-min[i]));if(!size)throw new Error('Degenerate GLB bounds.');
  for(const p of primitives)for(let i=0;i<p.positions.length;i++)p.positions[i]=(p.positions[i]-center[i%3])*2/size;
  return {primitives,triangles:primitives.reduce((n,p)=>n+p.indices.length/3,0)};
}
function identity(){return [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];}
export function multiply(a,b){const c=new Float32Array(16);for(let col=0;col<4;col++)for(let row=0;row<4;row++)for(let k=0;k<4;k++)c[col*4+row]+=a[k*4+row]*b[col*4+k];return c;}
function nodeMatrix(node){if(node.matrix){if(node.matrix.length!==16||!node.matrix.every(Number.isFinite))throw new Error('Invalid node transform.');return node.matrix;}const [x,y,z,w]=node.rotation||[0,0,0,1],[sx,sy,sz]=node.scale||[1,1,1],[tx,ty,tz]=node.translation||[0,0,0];return [(1-2*y*y-2*z*z)*sx,(2*x*y+2*z*w)*sx,(2*x*z-2*y*w)*sx,0,(2*x*y-2*z*w)*sy,(1-2*x*x-2*z*z)*sy,(2*y*z+2*x*w)*sy,0,(2*x*z+2*y*w)*sz,(2*y*z-2*x*w)*sz,(1-2*x*x-2*y*y)*sz,0,tx,ty,tz,1];}

export function createGLBRenderer(canvas,mesh){
  const gl=canvas.getContext('webgl2',{antialias:true,alpha:true});if(!gl)throw new Error('WebGL 2 is unavailable. Try a browser with hardware rendering enabled.');
  const shaders=[];
  function shader(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error('The browser could not compile the viewer shader.');shaders.push(s);return s;}
  const program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,`#version 300 es
    in vec3 position; in vec3 normal; uniform mat4 transform; uniform mat4 rotation; out vec3 vNormal;
    void main(){gl_Position=transform*vec4(position,1.0);vNormal=mat3(rotation)*normal;}`));
  gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`#version 300 es
    precision highp float;in vec3 vNormal;uniform vec4 color;out vec4 outColor;
    void main(){float light=.38+.62*abs(dot(normalize(vNormal),normalize(vec3(.5,.8,1.0))));outColor=vec4(color.rgb*light,1.0);}`));
  gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error('The browser could not link the viewer shader.');
  const buffers=[];const models=mesh.primitives.map(p=>{const vao=gl.createVertexArray();gl.bindVertexArray(vao);for(const [name,data] of [['position',p.positions],['normal',p.normals]]){const b=gl.createBuffer();buffers.push(b);gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);const location=gl.getAttribLocation(program,name);gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,3,gl.FLOAT,false,0,0);}const index=gl.createBuffer();buffers.push(index);gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,index);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,p.indices,gl.STATIC_DRAW);const edges=gl.createBuffer();buffers.push(edges);const lines=new Uint32Array(p.indices.length*2);for(let i=0;i<p.indices.length;i+=3){const j=i*2;lines.set([p.indices[i],p.indices[i+1],p.indices[i+1],p.indices[i+2],p.indices[i+2],p.indices[i]],j);}gl.bindVertexArray(null);gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,edges);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,lines,gl.STATIC_DRAW);return {vao,index,edges,count:p.indices.length,lineCount:lines.length,color:p.color};});
  return {draw({yaw,pitch,zoom,wire}){const dpr=Math.min(window.devicePixelRatio||1,2),w=Math.max(1,canvas.clientWidth),h=Math.max(1,canvas.clientHeight);canvas.width=w*dpr;canvas.height=h*dpr;gl.viewport(0,0,canvas.width,canvas.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);gl.useProgram(program);
    const cy=Math.cos(yaw),sy=Math.sin(yaw),cx=Math.cos(pitch),sx=Math.sin(pitch);const rotation=multiply([cy,0,-sy,0,0,1,0,0,sy,0,cy,0,0,0,0,1],[1,0,0,0,0,cx,sx,0,0,-sx,cx,0,0,0,0,1]);
    const aspect=w/h,scale=zoom*.82;const projection=[scale/Math.max(1,aspect),0,0,0,0,scale*Math.min(1,aspect),0,0,0,0,-.2,0,0,0,0,1];gl.uniformMatrix4fv(gl.getUniformLocation(program,'transform'),false,multiply(projection,rotation));gl.uniformMatrix4fv(gl.getUniformLocation(program,'rotation'),false,rotation);
    for(const m of models){gl.bindVertexArray(m.vao);gl.uniform4fv(gl.getUniformLocation(program,'color'),m.color);gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,wire?m.edges:m.index);gl.drawElements(wire?gl.LINES:gl.TRIANGLES,wire?m.lineCount:m.count,gl.UNSIGNED_INT,0);}gl.bindVertexArray(null);
  },dispose(){for(const b of buffers)gl.deleteBuffer(b);for(const m of models)gl.deleteVertexArray(m.vao);for(const s of shaders)gl.deleteShader(s);gl.deleteProgram(program);}};
}
