import Choices from './Choices';
import {MODEL_ROLES,VIEW_CONVENTIONS,reconstructionSelection} from '../lib/reconstruction.mjs';
import {SLOT_NAMES} from '../lib/session.mjs';
export default function ReconstructionSelection({state,dispatch,disabled}){
 const selected=reconstructionSelection(state), multi=state.reconstructionMode==='multiview';
 return <div className="reconstruction-selection">
 <Choices segmented label="Reconstruction mode" value={state.reconstructionMode} disabled={disabled}
 options={[{value:'multiview',label:'Multiview'},{value:'front_only',label:'Front only'}]}
 onChange={value=>dispatch({type:'RECONSTRUCTION_MODE',value})}/>
 <div className="panel-kicker source-heading">Source views</div>
 {MODEL_ROLES.map(role=>{
 const photo=state.photos.find(p=>p.slot===role),id=selected[role],active=role==='front'||multi;
 return <div className="source-row" key={role} title={VIEW_CONVENTIONS[role]}><label><input type="checkbox" id={'reconstruction-'+role}
 checked={Boolean(id)&&active} disabled={disabled||!active||(!photo&&!id)}
 onChange={e=>dispatch({type:'RECONSTRUCTION_PHOTO',role,id:e.target.checked?photo.id:''})}/>
 <strong>{SLOT_NAMES[role]}</strong><small>{state.photos.find(p=>p.id===id)?.name||photo?.name||'No photo'}</small></label></div>;
 })}
 </div>;
}
