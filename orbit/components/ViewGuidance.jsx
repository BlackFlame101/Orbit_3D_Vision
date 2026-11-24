import {useState} from 'react';
import {api} from '../lib/api.mjs';
export default function ViewGuidance({sid,version,photos,budget,choose}){
  const [result,setResult]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function inspect(){
    setBusy(true);
    try{setResult(await api('/sessions/'+sid+'/versions/'+version.id+'/guidance'));setError('');}
    catch(e){setError(e.message);}finally{setBusy(false);}
  }
  const candidate=result?.candidates.find(c=>!photos.some(p=>p.slot===c.slot));
  return <details><summary>Capture guidance</summary>
    <button disabled={busy} onClick={inspect}>{busy?'Measuring…':'Estimate visible surface'}</button>
    {error&&<p role="alert">{error}</p>}
    {result&&<><p>Estimated angle-weighted coverage {Math.round(result.observed*100)}%. Assumes nominal camera directions.</p>
      {candidate?<><p>{candidate.slot} could add {Math.round(candidate.gain*100)} percentage points. Geometry improvement is uncertain.</p>
      <button disabled={photos.length>=budget} onClick={()=>choose(candidate.slot)}>Capture {candidate.slot}</button></>:<p>All available reconstruction directions are occupied.</p>}
      {photos.length>=budget&&<small>Capture budget reached.</small>}</>}
  </details>;
}
