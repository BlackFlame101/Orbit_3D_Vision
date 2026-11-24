import {multiply} from './glb.mjs';

function check(value,message){if(!value)throw new Error(message);}

export function readTextureMesh(data){
  const dv=new DataView(data);
  check(data.byteLength>=28&&dv.getUint32(0,true)===0x46546c67&&dv.getUint32(4,true)===2&&dv.getUint32(8,true)===data.byteLength,'Incomplete GLB 2 file');
  const jsonSize=dv.getUint32(12,true),binHeader=20+jsonSize;
  check(binHeader+8<=data.byteLength&&dv.getUint32(16,true)===0x4e4f534a&&dv.getUint32(binHeader+4,true)===0x004e4942,'Invalid GLB chunks');
  const doc=JSON.parse(new TextDecoder().decode(new Uint8Array(data,20,jsonSize)));
  const bin=binHeader+8,size=dv.getUint32(binHeader,true);
  check(bin+size===data.byteLength&&doc.asset.version==='2.0'&&doc.buffers.length===1&&!doc.buffers[0].uri&&!doc.extensionsRequired?.length,'Unsupported texture container');
  const primitive=doc.meshes[0].primitives[0];
  check(doc.meshes.length===1&&doc.meshes[0].primitives.length===1&&(primitive.mode??4)===4&&
    doc.nodes.every(n=>!['matrix','translation','rotation','scale','skin'].some(k=>k in n)),'Unsupported texture geometry');
  function range(id){
    const v=doc.bufferViews[id],offset=v?.byteOffset??0;
    check(v?.buffer===0&&!v.byteStride&&Number.isSafeInteger(offset)&&offset>=0&&Number.isSafeInteger(v.byteLength)&&v.byteLength>0&&offset+v.byteLength<=Math.min(size,doc.buffers[0].byteLength),'Invalid GLB buffer range');
    return [bin+offset,v.byteLength];
  }
  function accessor(id,type,width,types){
    const a=doc.accessors[id],Type=types[a?.componentType];
    check(Type&&a.type===type&&!a.sparse&&!a.normalized&&Number.isSafeInteger(a.count)&&a.count>0,'Invalid texture mesh accessor');
    const [start,length]=range(a.bufferView),offset=a.byteOffset??0;
    check(Number.isSafeInteger(offset)&&offset>=0&&offset+a.count*width*Type.BYTES_PER_ELEMENT<=length,'Invalid accessor range');
    return new Type(data,start+offset,a.count*width);
  }
  const positions=accessor(primitive.attributes.POSITION,'VEC3',3,{5126:Float32Array});
  const uv=accessor(primitive.attributes.TEXCOORD_0,'VEC2',2,{5126:Float32Array});
  const indices=accessor(primitive.indices,'SCALAR',1,{5125:Uint32Array,5123:Uint16Array,5121:Uint8Array});
  check(uv.length/2===positions.length/3&&indices.length%3===0&&indices.every(i=>i<positions.length/3)&&positions.every(Number.isFinite)&&uv.every(n=>n>=0&&n<=1),'Invalid positions, UVs or indices');
  const ref=doc.materials[primitive.material].pbrMetallicRoughness.baseColorTexture;
  const png=doc.images[doc.textures[ref.index].source];
  check((ref.texCoord??0)===0&&png.mimeType==='image/png'&&!png.uri,'Expected an embedded base-color PNG');
  const [start,length]=range(png.bufferView);
  check(length>=24&&dv.getUint32(start)===0x89504e47&&dv.getUint32(start+4)===0x0d0a1a0a&&dv.getUint32(start+16)<=2048&&dv.getUint32(start+20)<=2048,'Invalid atlas PNG');
  return {positions,uv,indices,image:new Blob([new Uint8Array(data,start,length)],{type:'image/png'}),triangles:indices.length/3};
}

export function textureRenderer(canvas,mesh,bitmap){
  const gl=canvas.getContext('webgl2');
  check(gl,'WebGL 2 required for photo textures');
  const program=gl.createProgram(),buffers=[],shaders=[],texture=gl.createTexture(),vao=gl.createVertexArray();
  function dispose(){buffers.forEach(b=>gl.deleteBuffer(b));shaders.forEach(s=>gl.deleteShader(s));gl.deleteVertexArray(vao);gl.deleteTexture(texture);gl.deleteProgram(program);}
  try{
    function compile(type,source){
      const s=gl.createShader(type);shaders.push(s);gl.shaderSource(s,source);gl.compileShader(s);
      check(gl.getShaderParameter(s,gl.COMPILE_STATUS),'Texture shader failed');gl.attachShader(program,s);
    }
    compile(gl.VERTEX_SHADER,'#version 300 es\nin vec3 position; in vec2 uv; out vec2 coord; uniform mat4 transform; uniform vec3 center; void main(){coord=uv;gl_Position=transform*vec4(position-center,1.0);}');
    compile(gl.FRAGMENT_SHADER,'#version 300 es\nprecision highp float; in vec2 coord; out vec4 color; uniform sampler2D atlas; uniform bool wire; void main(){color=wire?vec4(0.5,0.95,0.7,1.):texture(atlas,coord);}');
    gl.linkProgram(program);check(gl.getProgramParameter(program,gl.LINK_STATUS),'Texture shader linking failed');
    gl.bindVertexArray(vao);
    function buffer(target,data){
      const b=gl.createBuffer();buffers.push(b);gl.bindBuffer(target,b);gl.bufferData(target,data,gl.STATIC_DRAW);return b;
    }
    for(const [name,array,width] of [['position',mesh.positions,3],['uv',mesh.uv,2]]){
      buffer(gl.ARRAY_BUFFER,array);const loc=gl.getAttribLocation(program,name);gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,width,gl.FLOAT,false,0,0);
    }
    const indices=buffer(gl.ELEMENT_ARRAY_BUFFER,mesh.indices);
    const type=({1:gl.UNSIGNED_BYTE,2:gl.UNSIGNED_SHORT,4:gl.UNSIGNED_INT})[mesh.indices.BYTES_PER_ELEMENT];
    let edges;
    gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,bitmap);gl.generateMipmap(gl.TEXTURE_2D);
    const min=[Infinity,Infinity,Infinity],max=min.map(()=>-Infinity);
    mesh.positions.forEach((n,i)=>{const k=i%3;min[k]=Math.min(min[k],n);max[k]=Math.max(max[k],n);});
    const center=min.map((n,k)=>(n+max[k])/2);
    const radius=Math.hypot(...max.map((n,k)=>n-center[k]));
    check(radius>0,'Degenerate textured mesh');
    return {dispose,draw({yaw,pitch,zoom,wire}){
      const ratio=Math.min(devicePixelRatio,2);
      canvas.width=Math.max(1,canvas.clientWidth*ratio);canvas.height=Math.max(1,canvas.clientHeight*ratio);
      gl.viewport(0,0,canvas.width,canvas.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);
      const aspect=canvas.width/canvas.height,s=.85*zoom/radius;
      const cy=Math.cos(yaw),sy=Math.sin(yaw),cx=Math.cos(pitch),sx=Math.sin(pitch);
      const rotation=multiply([cy,0,-sy,0,0,1,0,0,sy,0,cy,0,0,0,0,1],[1,0,0,0,0,cx,sx,0,0,-sx,cx,0,0,0,0,1]);
      const proj=[s/Math.max(1,aspect),0,0,0,0,s*Math.min(1,aspect),0,0,0,0,-.9/radius,0,0,0,0,1];
      gl.useProgram(program);gl.uniformMatrix4fv(gl.getUniformLocation(program,'transform'),false,multiply(proj,rotation));
      gl.uniform3fv(gl.getUniformLocation(program,'center'),center);gl.uniform1i(gl.getUniformLocation(program,'wire'),wire);
      gl.bindVertexArray(vao);gl.bindTexture(gl.TEXTURE_2D,texture);
      if(wire&&!edges){
        const ids=mesh.indices,lines=new ids.constructor(ids.length*2);
        for(let i=0;i<ids.length;i+=3){const [a,b,c]=ids.subarray(i,i+3);lines.set([a,b,b,c,c,a],2*i);}
        edges=buffer(gl.ELEMENT_ARRAY_BUFFER,lines);
      }
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,wire?edges:indices);gl.drawElements(wire?gl.LINES:gl.TRIANGLES,mesh.indices.length*(wire?2:1),type,0);gl.bindVertexArray(null);
    }};
  }catch(error){dispose();throw error;}
}
