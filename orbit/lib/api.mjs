import {selectionProblem} from './reconstruction.mjs';
export async function api(path,{method='GET',body,signal}={}){
  const form=typeof FormData!=='undefined'&&body instanceof FormData;
  let response;
  try{response=await fetch('/api/orbit'+path,{method,signal,cache:'no-store',headers:{'X-Orbit-Client':'1',...(!form&&body?{'Content-Type':'application/json'}:{})},body:body?(form?body:JSON.stringify(body)):undefined});}
  catch(error){if(error.name==='AbortError')throw error;throw new Error('The local Orbit API is unavailable. Start the FastAPI server on port 8000.');}
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}const error=new Error(typeof detail==='string'?detail:`Orbit API request failed (${response.status}).`);error.status=response.status;throw error;}
  return response.json();
}
export function backendProblem(state){
  if(!state.id)return 'Connect to the local API to begin.';
  const front=state.photos.find(p=>p.slot==='front');
  if(!front)return 'Upload and manually assign a front photograph.';
  if(front.status==='invalid'||front.status==='failed')return front.error||'The front photograph failed preprocessing.';
  if(front.status!=='ready'||!front.cutoutUrl)return 'Wait for CPU preprocessing to finish.';
  if(!front.confirmed)return 'Review and confirm the processed front cutout.';
  return '';
}
export function realGenerationProblem(state){
  if(!state.id)return 'Connect to the local API to begin.';
  const problem=selectionProblem(state);if(problem)return problem;
  if(state.settings?.seeds!==1||state.settings?.steps!==30||state.settings?.octree!==256)return 'Real generation requires one seed, 30 steps and octree 256.';
  return '';
}
export const JOB_STAGES={waiting_ram:'Waiting for free RAM',waiting_vram:'Waiting for free GPU memory',waiting_gpu_probe:'Waiting for GPU memory information',waiting_heavy_job:'Waiting for another memory-intensive job',queued:'Queued',loading_model:'Loading model',generating:'Generating geometry',saving_glb:'Saving GLB',validating_glb:'Validating GLB',completed:'Completed',failed:'Failed'};
