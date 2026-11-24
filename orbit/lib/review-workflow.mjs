import {reconstructionSelection} from './reconstruction.mjs';
import {realGenerationProblem,JOB_STAGES} from './api.mjs';

export function readyForReview(p){
  return p.status==='ready' && Boolean(p.cutoutUrl) && p.validation?.valid!==false && !p.confirmed;
}

export function reviewWorkflow(state,health){
  const selection=reconstructionSelection(state);
  const multi=state.reconstructionMode!=='front_only';
  const roles=multi?['front','left','right']:['front'];
  const selected=roles.map(r=>state.photos.find(p=>p.id===selection[r])).filter(Boolean);
  const pending=selected.filter(readyForReview);
  const result=(kind,label,hint='',photo=null,role=null)=>({kind,label,hint,photo,role,pending,selected});
  const job=state.jobs?.find(j=>j.kind==='reconstruct'&&['queued','running'].includes(j.status));
  if(job)return result('progress',JOB_STAGES[job.stage]||job.status,job.status==='running'?job.progress+'% complete':'Reconstruction queued');
  if(!state.photos.length)return result('upload','Upload photos','Start with the front photograph.',null,'front');
  const wrong=roles.find(r=>selection[r]&&!state.photos.some(p=>p.id===selection[r]&&p.slot===r));
  if(wrong){
    const p=state.photos.find(p=>p.id===selection[wrong]);
    if(p)return result('inspect','Review viewpoint',realGenerationProblem(state),p);
    return result('select','Clear missing '+wrong+' view',realGenerationProblem(state),null,wrong);
  }
  const failed=selected.find(p=>['invalid','failed'].includes(p.status)||p.validation?.valid===false);
  if(failed)return result('inspect','Review failed cutout',failed.error||'Inspect or replace the failed photo.',failed);
  if(pending.length)return result('review','Review '+pending.length+(pending.length===1?' photo':' photos'),'Check the background removal before generating.',pending[0]);
  if(selected.some(p=>!p.confirmed&&(p.status!=='ready'||!p.cutoutUrl)))return result('preparing','Preparing photos…','The CPU worker is preparing your selected cutouts.');
  if(!selection.front||multi&&!selection.left&&!selection.right){
    const needed=!selection.front?['front']:['left','right'];
    const p=state.photos.find(p=>needed.includes(p.slot));
    if(p)return result('select','Select '+p.slot+' view',realGenerationProblem(state),p,p.slot);
    const unassigned=state.photos.find(p=>!p.slot);
    if(unassigned)return result('inspect','Assign viewpoint','Choose a viewpoint for this photo.',unassigned);
    if(state.photos.length>=state.budget)return result('budget','Review capture budget','Increase the budget or remove a photo to add the missing view.');
    return result('upload','Upload '+(needed.length===1?'front':'side')+' photo',realGenerationProblem(state),null,needed[0]);
  }
  const problem=realGenerationProblem(state);
  if(problem)return result('settings','Review settings',problem);
  return result('generate','Generate from '+selected.length+(selected.length===1?' view':' views'),health?.gpuSubmissionEnabled?'Ready to generate.':'Enable GPU jobs with the Orbit launcher to generate.');
}
