import Choices from './Choices';
import {useEffect,useRef,useState} from 'react';
import {SLOTS,SLOT_NAMES} from '../lib/session.mjs';
export default function PhotoReview({photo,photos,pending=[],dispatch,onClose,onConfirm,onNext,importing}){
  const dialog=useRef(null);const [error,setError]=useState('');
  useEffect(()=>{dialog.current.showModal();},[]);
  const ready=photo.status==='ready'&&photo.validation?.valid&&photo.cutoutUrl;
  const [seen,setSeen]=useState({}),[loaded,setLoaded]=useState({}),[saving,setSaving]=useState(false);
  const signature=p=>JSON.stringify([p.id,p.slot,p.cutoutUrl,p.confirmed_sha256,p.updated,p.validation]);
  const key=signature(photo);
  const others=pending.filter(p=>p.id!==photo.id);
  const allSeen=pending.length>1&&pending.every(p=>seen[signature(p)]);
  function imageReady(which){
    setLoaded(old=>({...old,[key]:{...old[key],[which]:true}}));
  }
  useEffect(()=>{
    if(ready&&loaded[key]?.original&&loaded[key]?.cutout)setSeen(old=>old[key]?old:{...old,[key]:true});
  },[key,ready,loaded]);
  useEffect(()=>{setError('');},[key]);
  async function confirm(batch=false){
    if(saving||importing)return;
    setSaving(true);setError('');
    try{
      for(const p of batch?pending:[photo]){
        if(!await onConfirm(p.id)){onNext?.(p.id);setError('Confirmation failed. Inspect the session status and try again.');return;}
      }
      if(!batch&&others.length)onNext(others[0].id);else onClose();
    }finally{setSaving(false);}
  }
  return <dialog ref={dialog} className="photo-review" aria-labelledby="review-title" onCancel={e=>{if(importing||saving)e.preventDefault();else onClose();}} onClose={onClose}>
    <div className="row"><div><div className="eyebrow">CPU IMAGE PROCESSING - REVIEW REQUIRED</div><h2 id="review-title">Check the photograph &amp; cutout</h2></div><button disabled={importing||saving} aria-label="Close image review" onClick={onClose}>&times;</button></div>
    <p className="field-help">The original RGB pixels are preserved. Inspect thin parts, openings and silhouette edges before confirming. Validation cannot guarantee correct segmentation or pose.</p>
    <div className="review-images" key={key}><figure><figcaption>Original photograph</figcaption><div className="image-well"><img onLoad={()=>imageReady('original')} src={photo.url} alt={`Original: ${photo.name}`}/></div></figure><figure><figcaption>CPU-processed transparent cutout</figcaption><div className="image-well checker">{photo.cutoutUrl?<img onLoad={()=>imageReady('cutout')} src={photo.cutoutUrl} alt={`Processed transparent cutout: ${photo.name}`}/>:<p>{photo.status==='failed'?'Preprocessing failed. Check the worker log and retry.':'Waiting for the CPU worker to process this photo.'}</p>}</div></figure></div>
    <p className="review-filename">{photo.name}</p><Choices label="Review viewpoint" value={photo.slot} disabled={importing||saving} options={SLOTS.map(value=>({value,label:SLOT_NAMES[value]+(photos.some(p=>p.id!==photo.id&&p.slot===value)?' (swap)':'')}))} onChange={slot=>dispatch({type:'ASSIGN',id:photo.id,slot})}/>
    <p className="field-help">Front is the reference view. Model left is front clockwise 90°, and right is front clockwise 270°. Physical camera directions are not verified. Changing an occupied slot swaps assignments and clears both confirmations; review both photos again. Back is not supported for reconstruction. Cached fixtures remain independent.</p>
    {photo.validation&&<p className="field-help">{photo.validation.valid?'Framing and RGB screening passed. Please inspect the cutout visually.':photo.validation.errors.join(' ')}</p>}
    <p role="alert" className="error-message">{error||photo.error}</p><div className="review-actions"><button className="secondary" disabled={importing||saving} onClick={onClose}>Close review</button> {others.length>0&&<button className="secondary" disabled={importing||saving||(ready&&!seen[key])} onClick={()=>onNext(others.find(p=>!seen[signature(p)])?.id||others[0].id)}>Inspect next</button>}
    {allSeen&&<button disabled={importing||saving} onClick={()=>confirm(true)}>Confirm all {pending.length} reviewed photos</button>}
    <button className="primary" disabled={importing||saving||!ready||!photo.slot||!seen[key]} onClick={()=>confirm()}>{others.length?'Confirm and next':'Confirm processed photo'}</button></div>
    <p className="field-help">Images are stored locally by the API. Preprocessing runs on CPU. Model generation requires a separate explicitly enabled worker.</p>
  </dialog>;
}
