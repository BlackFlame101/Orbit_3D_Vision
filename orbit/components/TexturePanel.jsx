import {useState,useRef} from 'react';
import LandmarkPicker from './LandmarkPicker';
import {api,JOB_STAGES} from '../lib/api.mjs';
import {SLOT_NAMES} from '../lib/session.mjs';

export default function TexturePanel({state,version,onView}){
  const dialog=useRef(null);
  const [photo,setPhoto]=useState(''),[raw,setRaw]=useState(''),[profiles,setProfiles]=useState({});
  const [resolution,setResolution]=useState(512),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
  const [excluded,setExcluded]=useState([]);
  const profileKey='orbit-calibration-v1:'+state.id+':'+version.id+':'+version.modelSha256;
  function open(){
    try{setProfiles(JSON.parse(localStorage.getItem(profileKey)||'{}'));}catch{setProfiles({});}
    dialog.current.showModal();
  }
  function save(next){setProfiles(next);localStorage.setItem(profileKey,JSON.stringify(next));}
  function edit(value){
    setRaw(value);const next={...profiles};delete next[photo];save(next);
  }
  const photos=(state.photos||[]).filter(p=>p.confirmed&&p.cutoutUrl);
  const current=photos.find(p=>p.id===photo);
  const usable=photos.filter(p=>profiles[p.id]?.hash===p.confirmed_sha256);
  const automatic=photos.filter(p=>p.slot&&!excluded.includes(p.id));
  const base='/sessions/'+state.id;
  const jobs=(state.jobs||[]).filter(j=>j.kind==='texture'&&j.parentVersionId===version.id);
  async function perform(fn){
    setBusy(true);
    try{await fn();}catch(error){setMessage(error.message);}finally{setBusy(false);}
  }
  async function fit(){
    const result=await api('/calibration/orthographic',{method:'POST',body:{landmarks:JSON.parse(raw)}});
    const {axes,scale,offset,landmarks,maxPixels}=result;
    save({...profiles,[photo]:{hash:current.confirmed_sha256,view:{photo_id:photo,axes,scale,offset,landmarks}}});
    setMessage('Maximum landmark error '+maxPixels.toFixed(2)+' px.');
  }
  async function submit(views){
    const result=await api(base+'/versions/'+version.id+'/textures',{method:'POST',body:{resolution,views}});
    setMessage(result.cacheHit?'Verified cached texture available.':'Texture job '+result.status+'.');
  }
  return <><button onClick={open}>Texture model</button>
    <dialog className="texture-dialog" ref={dialog} aria-label="Photo texture"><h2>Photo texture · V{version.number}</h2>
      <fieldset><legend>Atlas resolution</legend>{[64,128,256,512,1024,2048].map(n=><button key={n} disabled={busy} aria-pressed={resolution===n} onClick={()=>setResolution(n)}>{n}</button>)}</fieldset>
      <fieldset><legend>Automatic photo projection</legend>
        <p>Uses the assigned capture directions and silhouette alignment. Small sampling gaps are repaired; unseen areas stay neutral. Color placement is approximate.</p>
        {photos.filter(p=>p.slot).map(p=><label key={p.id} style={{display:'block'}}><input type="checkbox" checked={!excluded.includes(p.id)} disabled={busy} onChange={e=>setExcluded(ids=>e.target.checked?ids.filter(id=>id!==p.id):[...ids,p.id])}/>{SLOT_NAMES[p.slot]||p.slot} — {p.name}</label>)}
        <button disabled={busy||!automatic.length} onClick={()=>perform(()=>submit(automatic.map(p=>({photo_id:p.id,mode:'automatic'}))))}>Bake from {automatic.length} photos automatically</button>
      </fieldset>
      <details><summary>Manual calibration</summary><p>Select a confirmed cutout to calibrate.</p>
      {photos.map(p=><button key={p.id} disabled={busy} aria-pressed={photo===p.id} onClick={()=>{setPhoto(p.id);setRaw(JSON.stringify(profiles[p.id]?.view.landmarks||[]));}}>{p.name}</button>)}
      {current&&<section><LandmarkPicker key={photo} version={version} photo={current} add={row=>{try{edit(JSON.stringify([...JSON.parse(raw||'[]'),row]));}catch{setMessage('Correct the landmark JSON before adding another pair.');}}}/>
        <label>Native mesh XYZ and cutout pixel coordinates [X,Y,Z,u,v]
          <textarea disabled={busy} value={raw} onChange={e=>edit(e.target.value)}/></label>
        <button disabled={busy} onClick={()=>perform(fit)}>Fit camera</button>
        <small>Use at least four landmarks at different depths.</small></section>}
      <button disabled={busy||!usable.length} onClick={()=>perform(()=>submit(usable.map(p=>profiles[p.id].view)))}>Bake from {usable.length} calibrated views</button></details>
      <p role="status">{message}</p>
      {jobs.map(j=><p key={j.id}>{j.sources.join(', ')} · {j.resolution}px · {j.status} {JOB_STAGES[j.stage]||({calibration:'Aligning photos',uv:'Unwrapping mesh',projection:'Projecting colors',glb_validation:'Validating textured GLB',input:'Checking inputs'}[j.stage])||''} {j.progress}% {j.error}
        {j.textureMetrics&&<small style={{display:'block'}}>Photo coverage: {Math.round(100*(j.textureMetrics.observedFraction??j.textureMetrics.observed_texels/j.textureMetrics.atlas_texels))}% of occupied atlas texels. {j.textureMetrics.filled_texels>0&&`${j.textureMetrics.filled_texels} small gaps repaired. `}{(j.textureMetrics.alignments||[]).filter(a=>a.mode==='automatic').map(a=>a.role+': '+Math.round(a.silhouetteIoU*100)+'% silhouette overlap').join(' · ')}</small>}
        {j.status==='completed'&&<><button onClick={()=>{onView('/api/orbit'+base+'/textures/'+j.id+'/model.glb');dialog.current.close();}}>View texture</button><a href={'/api/orbit'+base+'/textures/'+j.id+'/model.glb'} download>Download textured GLB</a></>}
        {j.status==='failed'&&<button disabled={busy} onClick={()=>perform(()=>api(base+'/jobs/'+j.id+'/retry',{method:'POST'}))}>Retry bake</button>}</p>)}
      <button onClick={()=>{onView(null);dialog.current.close();}}>View original geometry</button><button onClick={()=>dialog.current.close()}>Close</button></dialog></>;
}
