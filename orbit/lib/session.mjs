import {backendProblem} from './api.mjs';
export const SLOTS = ['front', 'left', 'back', 'right'];
export const SLOT_NAMES = {front: 'Front', left: 'Left side', back: 'Opposite side', right: 'Right side'};
export function initialSession() {
  return {reconstructionMode:"multiview",photos: [], versions: [], selectedId: null, budget: 3, settings: {seeds: 1, steps: 30, octree: 256}, guidance: false, busy: false, progress: 0, message: ''};
}
export function generationProblem(state) {
  if (state.server) return backendProblem(state);
  if (!state.photos.length) return 'Add a photograph to begin.';
  if (state.photos.some(p => !p.slot)) return 'Assign a viewpoint to every photograph.';
  if (!state.photos.some(p => p.slot === 'front')) return 'Assign a front photograph before generating.';
  if (state.photos.some(p => !p.confirmed)) return 'Review and confirm every photograph before generating the demo.';
  return '';
}
export function recommendation(state) {
  if (!state.guidance) return {slot: null, title: 'Another perspective, if you want it.', text: 'Enable optional demo guidance to explore a missing view. You decide whether to take another photo.'};
  if (state.photos.length >= state.budget) return {slot: null, title: 'Your photo budget is filled.', text: 'You can keep a version or change your budget. This limit does not assess model quality.'};
  if (state.photos.some(p => !p.slot)) return {slot: null, title: 'Assign your viewpoints first.', text: 'Choose an approximate direction for each photograph. Automatic view recognition is not connected.'};
  const slot = SLOTS.find(slot => !state.photos.some(p => p.slot === slot));
  return {slot, title: slot === 'front' ? 'Start with a front view.' : `Consider the ${SLOT_NAMES[slot].toLowerCase()}.`, text: 'Optional demo suggestion in fixed slot order. It may help reveal another side; improvement is not guaranteed. No disagreement analysis runs.'};
}
export function snapshot(state) {
  return {photos: state.photos.map(({id, name, slot, cutoutUrl}) => ({id, name, slot, hasCutout: Boolean(cutoutUrl)})), settings: {...state.settings}, budget: state.budget};
}
export function sessionReducer(state, action) {
  if (state.busy && !['LOAD', 'PROGRESS', 'FINISH', 'FAIL', 'MESSAGE'].includes(action.type)) return state;
  switch (action.type) {
    case 'RECONSTRUCTION_MODE': return ['front_only','multiview'].includes(action.value)?{...state,reconstructionMode:action.value}:state;
    case 'RECONSTRUCTION_PHOTO': return ['front','left','right'].includes(action.role)?{...state,reconstructionPhotos:{...state.reconstructionPhotos,[action.role]:action.id}}:state;
    case 'LOAD': return {...state,...action.session,server:true,message:action.text??state.message};
    case 'MESSAGE': return {...state, message: action.text};
    case 'BUDGET': {
      if (![2,3,4].includes(action.value)) return state;
      return action.value < state.photos.length ? {...state, message: 'Remove photos before lowering the budget.'} : {...state, budget: action.value, message: ''};
    }
    case 'ADD': {
      if (state.photos.length >= state.budget) return {...state, message: 'Photo budget reached. Remove a photo or increase the budget.'};
      const slot = SLOTS.includes(action.photo.slot) && !state.photos.some(p => p.slot === action.photo.slot) ? action.photo.slot : null;
      return {...state, photos: [...state.photos, {...action.photo, slot, confirmed: false}], message: 'Photo added. Confirm its manually assigned viewpoint and review the image.'};
    }
    case 'REMOVE': return {...state, photos: state.photos.filter(p => p.id !== action.id), message: 'Photo removed. Existing versions retain their input snapshots.'};
    case 'ASSIGN': {
      if (!SLOTS.includes(action.slot)) return state;
      const current = state.photos.find(p => p.id === action.id);
      if (!current || current.slot === action.slot) return state;
      return {...state, photos: state.photos.map(p => p.id === action.id ? {...p, slot: action.slot, confirmed: false} : p.slot === action.slot ? {...p, slot: current.slot, confirmed: false} : p), message: 'Viewpoints updated. Occupied slots are swapped; review the affected photos again.'};
    }
    case 'CUTOUT': return {...state, photos: state.photos.map(p => p.id === action.id ? {...p, cutoutUrl: action.url, confirmed: false} : p), message: 'Prepared cutout attached. Check its colors and silhouette before confirming.'};
    case 'CONFIRM': return {...state, photos: state.photos.map(p => p.id === action.id && p.slot ? {...p, confirmed: true} : p), message: 'Photo confirmed for the mock workflow. No segmentation or GPU call was made.'};
    case 'SETTINGS': {
      const allowed = {seeds: [1,3], steps: [20,30,50], octree: [256,384]};
      if (!allowed[action.key]?.includes(action.value)) return state;
      return {...state, settings: {...state.settings, [action.key]: action.value}};
    }
    case 'GUIDANCE': return {...state, guidance: action.value};
    case 'SELECT': return state.versions.some(v => v.id === action.id) ? {...state, selectedId: action.id} : state;
    case 'START': {
      const problem = generationProblem(state);
      return problem ? {...state, message: problem} : {...state, busy: true, progress: 0, message: 'Simulating generation. No model is running.'};
    }
    case 'PROGRESS': return state.busy ? {...state, progress: action.value} : state;
    case 'FINISH': {
      if (!state.busy) return state;
      const id = state.versions.length + 1;
      return {...state, busy: false, progress: 100, versions: [...state.versions, {id, ...snapshot(state), kind: 'procedural-demo'}], selectedId: id, message: 'Demo version ready. The procedural mug is not reconstructed from your photograph.'};
    }
    case 'FAIL': return {...state, busy: false, progress: 0, message: action.text};
    case 'RESET': return initialSession();
    default: return state;
  }
}
