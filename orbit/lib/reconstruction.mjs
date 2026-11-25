export const MODEL_ROLES=['front','left','back','right'];
export const VIEW_CONVENTIONS={front:'Reference view',back:'Opposite 180 degrees',left:'Front clockwise 90°',right:'Front clockwise 270°'};
export function reconstructionSelection(state){
  const chosen=state.reconstructionPhotos||{};
  return {front:Object.hasOwn(chosen,'front')?chosen.front:state.photos.find(p=>p.slot==='front')?.id||'',left:chosen.left||'',back:Object.hasOwn(chosen,'back')?chosen.back:state.photos.find(p=>p.slot==='back')?.id||'',right:chosen.right||''};
}
export function selectionProblem(state){
  const mode=state.reconstructionMode||'multiview',selected=reconstructionSelection(state);
  if(!['front_only','multiview'].includes(mode))return 'Choose a supported reconstruction mode.';
  if(!selected.front)return 'Select a confirmed front photograph.';
  if(mode==='multiview'&&!selected.left&&!selected.back&&!selected.right)return 'Multiview requires at least one confirmed additional photograph.';
  const roles=mode==='front_only'?['front']:MODEL_ROLES.filter(r=>selected[r]);
  if(new Set(roles.map(r=>selected[r])).size!==roles.length)return 'Select a different photograph for each role.';
  for(const role of roles){
    const photo=state.photos.find(p=>p.id===selected[role]);
    if(!photo)return `The selected ${role} photograph is missing. Select another photo.`;
    if(photo.slot!==role)return `The selected ${role} photo is assigned to ${photo.slot||'no viewpoint'}. Use Review to correct its viewpoint, then confirm again.`;
    if(photo.status==='invalid'||photo.status==='failed'||photo.validation?.valid===false)return photo.error||`The ${role} cutout is invalid. Review or replace it.`;
    if(photo.status!=='ready'||!photo.cutoutUrl)return `Wait for the ${role} photograph to finish preprocessing.`;
    if(!photo.confirmed)return `Review and confirm the processed ${role} cutout.`;
  }
  return '';
}
export function reconstructionPayload(state){
  const problem=selectionProblem(state);if(problem)throw new Error(problem);
  const mode=state.reconstructionMode||'multiview',selected=reconstructionSelection(state);
  return {mode,photos:MODEL_ROLES.filter(role=>selected[role]&&(mode==='multiview'||role==='front')).map(role=>({photo_id:selected[role],role}))};
}
export function versionProvenance(version){
  if(version.kind!=='hunyuan-reconstruction')return null;
  const photos=version.photos||[],views=version.views||photos.map(p=>p.role||p.slot).filter(Boolean);
  const mode=version.mode||(views.length>1?'multiview':'front_only');
  return {label:mode==='multiview'?'Multiview':'Front-only',inputs:photos.map(p=>`${p.role||p.slot||'Unknown view'}: ${p.name||'Source name unavailable'}`).join(' · ')||'Source photos not recorded',cache:version.cacheHit===true?'Cache hit':version.cacheHit===false?'Fresh generation':'Cache status not recorded',settings:version.settings?`Seed ${version.settings.seed??12345} · ${version.settings.steps??'—'} steps · octree ${version.settings.octree??'—'}`:''};
}
