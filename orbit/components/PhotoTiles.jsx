import {readyForReview} from '../lib/review-workflow.mjs';
import {SLOT_NAMES} from '../lib/session.mjs';
import {reconstructionSelection} from '../lib/reconstruction.mjs';
export default function PhotoTiles({state,blocked,upload,review,dispatch}){
 const selected=reconstructionSelection(state);
 const entries=['front','left','right','back'].map(slot=>[slot,state.photos.find(p=>p.slot===slot)]);
 for(const p of state.photos.filter(p=>!p.slot)) entries.push([null,p]);
 return <section className="tiles" aria-label="Capture photos">{entries.map(([slot,p])=>{
 const full=state.photos.length>=state.budget;
 const chosen=p&&slot!=='back'&&selected[slot]===p.id&&(slot==='front'||state.reconstructionMode==='multiview');
 return <article className={"photo-tile"+(p&&readyForReview(p)?" pending-review":"")} key={slot||p.id} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();if(!blocked&&!p&&!full)upload([...e.dataTransfer.files],slot);}}>
 <strong>{SLOT_NAMES[slot]||'Unassigned'}</strong>
 {p?<><button className="tile-review" aria-label={'Review '+p.name} disabled={blocked} onClick={()=>review(p.id)}><img src={p.cutoutUrl||p.url} alt={p.name}/></button><small>{p.confirmed?(chosen?'Selected':'Confirmed'):readyForReview(p)?<button className="review-link" disabled={blocked} onClick={()=>review(p.id)}>Review cutout</button>:['invalid','failed'].includes(p.status)?'Cutout failed':'Preparing…'}{slot==='back'?' · Capture only':''}</small><button className="tile-remove" aria-label={'Remove '+p.name} disabled={blocked||p.status==='queued'} onClick={()=>dispatch({type:'REMOVE',id:p.id})}>×</button></>:<><small>{slot==='back'?'Capture only':full?'Budget filled':'Drop a photo'}</small><div>{['Upload','Camera'].map(action=><label key={action} className="tile-file">{action}<input type="file" aria-label={action+' '+slot} accept="image/*" capture={action==='Camera'?'environment':undefined} disabled={blocked||full} onChange={e=>{upload([...e.target.files],slot);e.target.value='';}}/></label>)}</div></>}
 </article>;})}</section>;
}
