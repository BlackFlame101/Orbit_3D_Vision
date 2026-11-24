import {useState,useRef} from 'react';
import LandmarkPicker from './LandmarkPicker';
import {api} from '../lib/api.mjs';

export default function TexturePanel({state,version,onView}){
  const dialog=useRef(null);
  const [photo,setPhoto]=useState(''),[raw,setRaw]=useState(''),[profiles,setProfiles]=useState({});
  const [resolution,setResolution]=useState(512),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
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
  async function submit(){
    const result=await api(base+'/versions/'+version.id+'/textures',{method:'POST',body:{resolution,views:usable.map(p=>profiles[p.id].view)}});
    setMessage(result.cacheHit?'Verified cached texture available.':'Texture job '+result.status+'.');
  }
  return <><button onClick={open}>Texture model</button>
    <dialog className="texture-dialog" ref={dialog} aria-label="Photo texture"><h2>Photo texture · V{version.number}</h2>
      <p>Select a confirmed cutout to calibrate.</p>
      {photos.map(p=><button key={p.id} disabled={busy} aria-pressed={photo===p.id} onClick={()=>{setPhoto(p.id);setRaw(JSON.stringify(profiles[p.id]?.view.landmarks||[]));}}>{p.name}</button>)}
      {current&&<section><LandmarkPicker key={photo} version={version} photo={current} add={row=>{try{edit(JSON.stringify([...JSON.parse(raw||'[]'),row]));}catch{setMessage('Correct the landmark JSON before adding another pair.');}}}/>
        <label>Native mesh XYZ and cutout pixel coordinates [X,Y,Z,u,v]
          <textarea disabled={busy} value={raw} onChange={e=>edit(e.target.value)}/></label>
        <button disabled={busy} onClick={()=>perform(fit)}>Fit camera</button>
        <small>Use at least four landmarks at different depths.</small></section>}
      <fieldset><legend>Atlas resolution</legend>{[64,128,256,512,1024,2048].map(n=><button key={n} aria-pressed={resolution===n} onClick={()=>setResolution(n)}>{n}</button>)}</fieldset>
      <button disabled={busy||!usable.length} onClick={()=>perform(submit)}>Bake from {usable.length} calibrated views</button>
      <p role="status">{message}</p>
      {jobs.map(j=><p key={j.id}>{j.sources.join(', ')} · {j.resolution}px · {j.status} {j.error}
        {j.status==='completed'&&<><button onClick={()=>{onView('/api/orbit'+base+'/textures/'+j.id+'/model.glb');dialog.current.close();}}>View texture</button><a href={'/api/orbit'+base+'/textures/'+j.id+'/model.glb'} download>Download textured GLB</a></>}
        {j.status==='failed'&&<button disabled={busy} onClick={()=>perform(()=>api(base+'/jobs/'+j.id+'/retry',{method:'POST'}))}>Retry bake</button>}</p>)}
      <button onClick={()=>{onView(null);dialog.current.close();}}>View original geometry</button><button onClick={()=>dialog.current.close()}>Close</button></dialog></>;
}
