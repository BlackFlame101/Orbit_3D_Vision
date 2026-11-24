import Choices from './Choices';
import {reviewWorkflow} from '../lib/review-workflow.mjs';
import {useRef} from 'react';
import ReconstructionSelection from './ReconstructionSelection';
import {realGenerationProblem,JOB_STAGES} from '../lib/api.mjs';
import {SLOT_NAMES, generationProblem} from '../lib/session.mjs';

export default function CapturePanel({demo,state, dispatch, onFiles, onReview, onGenerate, onGenerateFixture, targetSlot, setTargetSlot, importing, connection, health, fixtures=[], fixture, setFixture, onRetry}) {
  const blocked = state.busy || importing;
  const file=useRef(null);
  const flow=reviewWorkflow(state,health);
  function primary(){
    if(flow.kind==='upload')file.current.click();
    if(flow.kind==='review'||flow.kind==='inspect')onReview(flow.photo.id);
    if(flow.kind==='select')dispatch({type:'RECONSTRUCTION_PHOTO',role:flow.role,id:flow.photo?.id||''});
    if(flow.kind==='settings')document.getElementById('advanced-settings').showPopover();
    if(flow.kind==='budget')document.querySelector('[aria-label="Capture budget"] button:not(:disabled)')?.focus();
    if(flow.kind==='generate')onGenerate();
  }
  return <aside className="controls">
    <div className="panel-kicker">Reconstruction</div><h1>Capture budget</h1>
    <Choices label="Capture budget" disabled={blocked} value={state.budget} options={[2,3,4].map(value=>({value,disabled:value<state.photos.length}))} onChange={value=>dispatch({type:'BUDGET',value})}/>
    <p className="captured-count">{flow.selected.filter(p=>p.confirmed).length} of {flow.selected.length} selected confirmed</p><ReconstructionSelection state={state} dispatch={dispatch} disabled={blocked}/>
    <button popoverTarget="advanced-settings">Advanced settings</button><div popover="auto" id="advanced-settings">
    <p>One seed per reconstruction</p>
    {Object.entries({steps:[20,30,50],octree:[256,384],seed:[...new Set([12345,2027,31415,state.settings.seed??12345])]}).map(([key,values])=><Choices key={key} label={key} disabled={blocked} value={state.settings[key]??12345} options={values.map(value=>({value}))} onChange={value=>dispatch({type:'SETTINGS',key,value})}/>)}</div>
    {demo&&<> <Choices label="Cached viewer fixture" disabled={blocked} options={fixtures.map(f=>({value:f.id,label:f.label}))} value={fixture} onChange={setFixture}/>
    <p className="field-help">This will load an existing real GLB. It is not a reconstruction of your uploaded photo.</p>
    <button className="secondary" disabled={blocked||!fixtures.length||Boolean(generationProblem(state))} onClick={onGenerateFixture}>{state.busy?'Model job queued / running':'Load cached GLB (mock job)'}</button>
    </>}

    <input hidden ref={file} type="file" accept="image/*" multiple onChange={e=>{onFiles([...e.target.files],flow.role||'front');e.target.value='';}}/>
    <button className="primary" disabled={blocked||['preparing','progress'].includes(flow.kind)||(flow.kind==='generate'&&!health?.gpuSubmissionEnabled)} onClick={primary}>{flow.label}</button>
    <p className="field-help" aria-live="polite">{flow.hint}</p>
<p className="message" role="status" aria-live="polite">{connection==='connecting'?'Connecting to the local API…':state.message}</p>
    <div className="job-status" aria-live="polite">{state.jobs?.filter(j=>j.status==='queued'||j.status==='running'||j.status==='failed').map(j=><div key={j.id}><strong>{j.kind==='preprocess'?'CPU cutout':j.kind==='reconstruct'?'Hunyuan reconstruction':j.kind==='texture'?'CPU texture':'Cached GLB demo'}: {j.status==='queued'&&health?.workers&&!health.workers[j.kind==='reconstruct'?'gpu':'cpu']?'Waiting for worker':JOB_STAGES[j.stage]||j.status}</strong><small>Job {j.id}</small>{j.error&&<p className="error-message">{j.error}</p>}{j.status==='failed'&&j.attempts<3&&<button disabled={blocked||state.busy||(j.kind==='reconstruct'&&!health?.gpuSubmissionEnabled)} className="text-button" onClick={()=>onRetry(j.id)}>Retry job</button>}</div>)}</div>
    {health?.workers&&<p className="field-help">CPU worker {health.workers.cpu?'online':'offline'} · GPU worker {health.workers.gpu?'online':'offline'}</p>}
  </aside>;
}
