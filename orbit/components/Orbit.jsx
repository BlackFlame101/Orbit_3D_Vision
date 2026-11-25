'use client';
import {useEffect,useReducer,useRef,useState} from 'react';
import {initialSession,sessionReducer,generationProblem} from '../lib/session.mjs';
import {api,realGenerationProblem} from '../lib/api.mjs';
import {reviewWorkflow,readyForReview} from '../lib/review-workflow.mjs';
import PhotoTiles from './PhotoTiles';
import CapturePanel from './CapturePanel';
import SessionHistory from './SessionHistory';
import PhotoReview from './PhotoReview';
import ModelStage from './ModelStage';
import ResearchLab from './ResearchLab';
import {reconstructionPayload} from '../lib/reconstruction.mjs';

const SESSION_KEY='orbit-local-session-v1';
export default function Orbit(){
  const [state,dispatch]=useReducer(sessionReducer,undefined,initialSession);
  const [tab,setTab]=useState('studio'),[targetSlot,setTargetSlot]=useState('front'),[reviewId,setReviewId]=useState(null);
  const [connection,setConnection]=useState('connecting'),[working,setWorking]=useState(false),[health,setHealth]=useState(null),[fixtures,setFixtures]=useState([]),[fixture,setFixture]=useState('perfume');
  const [demo,setDemo]=useState(false),[mobile,setMobile]=useState("capture");
  const [imported,setImported]=useState(null);
  const glbInput=useRef(null);
  const previousSession=useRef({id:state.id,selected:state.selectedId});
  useEffect(()=>{
    const previous=previousSession.current;
    if((previous.id&&previous.id!==state.id)||(previous.selected!==state.selectedId&&state.selectedId))setImported(null);
    previousSession.current={id:state.id,selected:state.selectedId};
  },[state.id,state.selectedId]);
  function openGLB(file){
    if(!file)return;
    if(!file.name.toLowerCase().endsWith('.glb')||file.size>64*1024*1024||file.size<20){dispatch({type:'MESSAGE',text:'Choose a GLB file up to 64 MB.'});return;}
    setImported(file);setMobile('model');
  }
  const lock=useRef(false),revision=useRef(0),mounted=useRef(true);
  function accept(session,text){dispatch({type:'LOAD',session,text});}
  async function connect(signal){
    setConnection('connecting');
    try{
      const id=localStorage.getItem(SESSION_KEY);let session;
      if(id&&/^[a-f0-9]{32}$/.test(id)){try{session=await api(`/sessions/${id}`,{signal});}catch(error){if(error.status!==404&&error.status!==422)throw error;}}
      if(!session)session=await api('/sessions',{method:'POST',signal});
      if(signal?.aborted||!mounted.current)return;
      localStorage.setItem(SESSION_KEY,session.id);
      let saved;
      try{saved=JSON.parse(localStorage.getItem('orbit-source-views:'+session.id));}catch{}
      const defaults=Object.fromEntries(session.photos.filter(p=>['front','left','back','right'].includes(p.slot)).map(p=>[p.slot,p.id]));
      accept({...session,reconstructionMode:saved?.mode==='front_only'?'front_only':'multiview',reconstructionPhotos:saved?.photos||defaults});
      setConnection('ready');
      const [info,available]=await Promise.all([api('/health',{signal}),api('/fixtures',{signal})]);
      if(signal?.aborted||!mounted.current)return;setHealth(info);setFixtures(available);if(available.length&&!available.some(f=>f.id===fixture))setFixture(available[0].id);
    }catch(error){if(error.name!=='AbortError'&&mounted.current){setConnection('error');dispatch({type:'MESSAGE',text:error.message});}}
  }
  useEffect(()=>{mounted.current=true;const controller=new AbortController();connect(controller.signal);return()=>{mounted.current=false;controller.abort();};},[]);
  useEffect(()=>{
    if(!state.id||connection!=='ready')return;
    let stopped=false;const controller=new AbortController();
    const timer=setInterval(async()=>{
      if(lock.current)return;const version=revision.current;
      try{const [session,info]=await Promise.all([api(`/sessions/${state.id}`,{signal:controller.signal}),api('/health',{signal:controller.signal})]);if(!stopped&&!lock.current&&version===revision.current){accept(session);setHealth(info);}}
      catch(error){if(error.name!=='AbortError'&&!stopped)dispatch({type:'MESSAGE',text:error.message});}
    },1500);
    return()=>{stopped=true;controller.abort();clearInterval(timer);};
  },[state.id,connection]);
  useEffect(()=>{
    if(state.id&&connection==='ready')localStorage.setItem('orbit-source-views:'+state.id,JSON.stringify({mode:state.reconstructionMode,photos:state.reconstructionPhotos}));
  },[state.id,state.reconstructionMode,state.reconstructionPhotos,connection]);
  async function mutate(operation){
    if(lock.current||connection!=='ready')return false;
    lock.current=true;revision.current++;setWorking(true);
    try{await operation();return true;}catch(error){if(mounted.current)dispatch({type:'MESSAGE',text:error.message});return false;}
    finally{lock.current=false;if(mounted.current)setWorking(false);}
  }
  async function action(a){
    if(['GUIDANCE','RECONSTRUCTION_MODE','RECONSTRUCTION_PHOTO'].includes(a.type)){dispatch(a);return true;}
    return mutate(async()=>{
      let result;
      if(a.type==='BUDGET')result=await api(`/sessions/${state.id}`,{method:'PATCH',body:{budget:a.value}});
      if(a.type==='SETTINGS')result=await api(`/sessions/${state.id}`,{method:'PATCH',body:{settings:{...state.settings,[a.key]:a.value}}});
      if(a.type==='ASSIGN')result=await api(`/sessions/${state.id}/photos/${a.id}`,{method:'PATCH',body:{slot:a.slot}});
      if(a.type==='REMOVE')result=await api(`/sessions/${state.id}/photos/${a.id}`,{method:'DELETE'});
      if(a.type==='SELECT')result=await api(`/sessions/${state.id}`,{method:'PATCH',body:{selectedId:a.id}});
      if(result)accept(result,'Session updated. Stored versions retain their original snapshots.');
    });
  }
  async function addFiles(files,slot=targetSlot){
    if(!files.length||state.busy)return;
    await mutate(async()=>{
      let session=state;const errors=[];
      for(const [index,file]of files.entries()){
        if(session.photos.length>=session.budget){errors.push('Photo budget reached.');break;}
        const body=new FormData();body.append('image',file);
        if(index===0&&!session.photos.some(p=>p.slot===slot))body.append('slot',slot);
        try{const result=await api(`/sessions/${state.id}/photos`,{method:'POST',body});session=result.session;accept(session,'');
          const added=session.photos.find(p=>p.id===result.photo_id);
          if(added&&['front','left','back','right'].includes(added.slot)&&(added.slot==='front'||state.reconstructionMode==='multiview')){
            dispatch({type:'RECONSTRUCTION_PHOTO',role:added.slot,id:added.id});
          }}
        catch(error){errors.push(`${file.name}: ${error.message}`);}
      }
      if(errors.length)dispatch({type:'MESSAGE',text:errors.join(' ')});
    });
  }
  async function confirm(id){return mutate(async()=>{const session=await api(`/sessions/${state.id}/photos/${id}/confirm`,{method:'POST',body:{confirmed:true}});accept(session,'');});}
  const readyHistory=useRef({session:null,keys:new Set()});
  const [notice,setNotice]=useState('');
  useEffect(()=>{
    const keys=new Set(state.photos.filter(readyForReview).map(p=>p.id));
    const prev=readyHistory.current;
    if(prev.session===state.id&&[...keys].some(id=>!prev.keys.has(id)))setNotice('Your photos are ready for review.');
    if(!keys.size)setNotice('');
    readyHistory.current={session:state.id,keys};
  },[state.id,state.photos]);
  useEffect(()=>{if(notice){const timer=setTimeout(()=>setNotice(''),4000);return()=>clearTimeout(timer);}},[notice]);
  async function generate(){if(state.busy||realGenerationProblem(state)||!health?.gpuSubmissionEnabled)return;await mutate(async()=>{const result=await api(`/sessions/${state.id}/reconstructions`,{method:'POST',body:reconstructionPayload(state)});accept(result.session,'Reconstruction submitted. Progress and any validated cache result will appear here.');});}
  async function generateFixture(){if(state.busy||generationProblem(state))return;await mutate(async()=>{const front=state.photos.find(p=>p.slot==='front');const result=await api(`/sessions/${state.id}/jobs`,{method:'POST',body:{photo_id:front.id,fixture}});accept(result.session,'Demo job queued. The worker will copy a cached fixture, not reconstruct this photo.');});}
  async function reset(){if(state.busy)return;await mutate(async()=>{const session=await api('/sessions',{method:'POST'});localStorage.setItem(SESSION_KEY,session.id);setReviewId(null);setTargetSlot('front');dispatch({type:'RESET'});accept(session,'New empty session. The previous session remains stored locally.');});}
  async function retry(jid){await mutate(async()=>accept(await api(`/sessions/${state.id}/jobs/${jid}/retry`,{method:'POST'}),'Job queued for automatic retry.'));}
  function tabKey(e){const index=['studio','lab'].indexOf(tab);let next;if(e.key==='ArrowRight'||e.key==='ArrowLeft')next=['studio','lab'][1-index];if(e.key==='Home')next='studio';if(e.key==='End')next='lab';if(next){e.preventDefault();setTab(next);document.getElementById(`tab-${next}`).focus();}}
  const review=state.photos.find(p=>p.id===reviewId),blocked=working||connection!=='ready';
  return <div className="orbit-app"><header><a className="brand" href="./"><span className="mark" aria-hidden="true">&#9682;</span>orbit<span className="brand-note">PHOTO TO FORM</span></a><nav className="segmented" role="tablist" aria-label="Workspace">{['studio','lab'].map(t=><button key={t} className={`tab ${tab===t?'active':''}`} id={`tab-${t}`} role="tab" aria-selected={tab===t} aria-controls={t} tabIndex={tab===t?0:-1} onKeyDown={tabKey} onClick={()=>setTab(t)}>{t==='studio'?'Studio':'Research Lab'}</button>)}</nav><button aria-pressed={demo} onClick={()=>setDemo(!demo)}>Demo mode</button><span className="demo"><i/>{health?.gpuSubmissionEnabled?'Local Hunyuan':'Local preview - GPU disabled'}</span></header>
    {connection==='error'&&<div className="connection-notice" role="alert">{state.message}<button onClick={()=>connect()}>Reconnect local API</button></div>}
    <main className="workspace" data-mobile={mobile} id="studio" role="tabpanel" aria-labelledby="tab-studio" hidden={tab!=='studio'}><CapturePanel onImportGLB={()=>glbInput.current?.click()} demo={demo} state={state} dispatch={action} onFiles={addFiles} onReview={setReviewId} onGenerate={generate} onGenerateFixture={generateFixture} targetSlot={targetSlot} setTargetSlot={setTargetSlot} importing={blocked} connection={connection} health={health} fixtures={fixtures} fixture={fixture} setFixture={setFixture} onRetry={retry}/><div className={"studio-center "+(state.selectedId||imported?"loaded":"empty")}><input ref={glbInput} hidden aria-label="Choose GLB file" type="file" accept=".glb,model/gltf-binary" onChange={e=>{openGLB(e.target.files?.[0]);e.target.value='';}}/><ModelStage state={state} imported={imported} onCloseImported={()=>setImported(null)} onImportGLB={()=>glbInput.current?.click()}/><PhotoTiles state={state} blocked={blocked||state.busy} upload={addFiles} review={setReviewId} dispatch={action}/></div><SessionHistory state={state} dispatch={action} onReview={setReviewId} onReset={reset} targetSlot={targetSlot} setTargetSlot={setTargetSlot} importing={blocked}/></main>{tab==="studio"&&<nav className="phone-nav" aria-label="Studio panels">{["capture","model","versions"].map(t=><button key={t} aria-pressed={mobile===t} onClick={()=>setMobile(t)}>{t}</button>)}</nav>}
    <div hidden={tab!=='lab'}><ResearchLab/></div>
    {notice&&<div className="review-toast" role="status">{notice}</div>}
    {review&&<PhotoReview pending={reviewWorkflow(state,health).pending} onNext={setReviewId} photo={review} photos={state.photos} dispatch={action} onClose={()=>setReviewId(null)} onConfirm={confirm} importing={working}/>}</div>;
}
