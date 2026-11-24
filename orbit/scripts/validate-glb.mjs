import {readFileSync} from 'node:fs';
import {parseGLB} from '../lib/glb.mjs';
const data=readFileSync(process.argv[2]);
const mesh=parseGLB(data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength));
if(!mesh.triangles)throw new Error('GLB has no triangles.');
console.log(JSON.stringify({triangles:mesh.triangles,viewerCompatible:true}));
