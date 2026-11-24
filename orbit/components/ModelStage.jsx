import {versionProvenance} from '../lib/reconstruction.mjs';
import {useEffect,useRef,useState} from 'react';
import {JOB_STAGES} from '../lib/api.mjs';
import {parseGLB,createGLBRenderer} from '../lib/glb.mjs';
import {readTextureMesh,textureRenderer} from '../lib/textured-glb.mjs';
import TexturePanel from './TexturePanel';
export default function ModelStage({state}){
  const canvas=useRef(null),renderer=useRef(null),drag=useRef(null);
  const [camera,setCamera]=useState({yaw:-.5,pitch:-.28,zoom:1}),[wire,setWire]=useState(false),[status,setStatus]=useState('empty'),[error,setError]=useState(''),[triangles,setTriangles]=useState(0),[retry,setRetry]=useState(0);
  const version=state.versions.find(v=>v.id===state.selectedId);
  const generated=version?.kind==='hunyuan-reconstruction';
  const [texture,setTexture]=useState(null);
  const textured=texture?.parent===version?.id&&Boolean(texture);
  const modelUrl=textured?texture.url:version?.modelUrl;
  const active=state.jobs?.find(j=>j.kind==='reconstruct'&&(j.status==='queued'||j.status==='running'));
  const label=generated?(version.cacheHit?'reconstruction (cache hit)':'reconstruction'):'cached fixture';
  useEffect(()=>{
    if(!modelUrl){setStatus('empty');return;}
    let stopped=false;const controller=new AbortController();setStatus('loading');setError('');
    async function load(){try{const response=await fetch(modelUrl,{signal:controller.signal,cache:'no-store'});if(!response.ok)throw new Error('The stored GLB is unavailable. Retry or check the local API.');const data=await response.arrayBuffer();if(data.byteLength>64*1024*1024)throw new Error('The GLB exceeds the 64 MB viewer limit.');const mesh=textured?readTextureMesh(data):parseGLB(data);
      if(textured){
        const bitmap=await createImageBitmap(mesh.image,{imageOrientation:'none',premultiplyAlpha:'none'});
        try{if(stopped)return;renderer.current=textureRenderer(canvas.current,mesh,bitmap);}finally{bitmap.close();}
      }else{if(stopped)return;renderer.current=createGLBRenderer(canvas.current,mesh);}
      setTriangles(mesh.triangles);setCamera({yaw:-.5,pitch:-.28,zoom:1});setStatus('ready');}catch(err){if(!stopped&&err.name!=='AbortError'){setError(err.message);setStatus('error');}}}
    load();return()=>{stopped=true;controller.abort();renderer.current?.dispose();renderer.current=null;};
  },[modelUrl,textured,retry]);
  useEffect(()=>{const draw=()=>renderer.current?.draw({...camera,wire});draw();const observer=new ResizeObserver(draw);if(canvas.current)observer.observe(canvas.current);return()=>observer.disconnect();},[camera,wire,status]);
  useEffect(()=>{const el=canvas.current;if(!el)return;const wheel=e=>{e.preventDefault();setCamera(c=>({...c,zoom:Math.max(.4,Math.min(2.5,c.zoom-e.deltaY*.001))}));};el.addEventListener('wheel',wheel,{passive:false});const lost=e=>{e.preventDefault();setStatus('error');setError('The WebGL context was lost. Reload the model to restore the viewer.');};el.addEventListener('webglcontextlost',lost);return()=>{el.removeEventListener('wheel',wheel);el.removeEventListener('webglcontextlost',lost);};},[Boolean(version)]);
  useEffect(()=>{if(!state.versions.length){setWire(false);setError('');}},[state.versions.length]);
  function keyboard(e){if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-'].includes(e.key))return;e.preventDefault();setCamera(c=>({...c,yaw:c.yaw+(e.key==='ArrowLeft'?-.1:e.key==='ArrowRight'?.1:0),pitch:Math.max(-1.4,Math.min(1.4,c.pitch+(e.key==='ArrowUp'?-.1:e.key==='ArrowDown'?.1:0))),zoom:Math.max(.4,Math.min(2.5,c.zoom+(e.key==='+'?.1:e.key==='-'?-.1:0)))}));}
  return <section className="stage" aria-label="Model workspace"><div className="stage-heading"><div><div className="eyebrow">YOUR LOCAL SESSION</div><h2>Explore another perspective.</h2></div><span className="version-pill">{version?`Version ${version.number} - ${label}`:'No model yet'}</span></div>
    {version&&<p className="fixture-notice">{generated?`${versionProvenance(version).label} · ${versionProvenance(version).cache}. ${versionProvenance(version).inputs}. ${versionProvenance(version).settings}`:`Viewer fixture: ${version.source}. Not generated from your uploaded photograph.`}</p>}
    <div className="viewer" id="viewer" aria-busy={status==='loading'||state.busy}>{version?<>
      <div className="viewer-tools"><button disabled={status!=='ready'} aria-pressed={!wire} className={!wire?'selected':''} onClick={()=>setWire(false)}>Solid</button><button disabled={status!=='ready'} aria-pressed={wire} className={wire?'selected':''} onClick={()=>setWire(true)}>Wireframe</button><button disabled={status!=='ready'} aria-label="Zoom in" onClick={()=>setCamera(c=>({...c,zoom:Math.min(2.5,c.zoom+.15)}))}>+</button><button disabled={status!=='ready'} aria-label="Zoom out" onClick={()=>setCamera(c=>({...c,zoom:Math.max(.4,c.zoom-.15)}))}>&minus;</button><button disabled={status!=='ready'} aria-label="Reset camera" onClick={()=>setCamera({yaw:-.5,pitch:-.28,zoom:1})}>&#8634;</button></div>
      <canvas ref={canvas} tabIndex="0" aria-label={`${generated?'Hunyuan reconstruction from selected confirmed cutouts.':'Existing GLB fixture, unrelated to uploaded photo.'} Drag or use arrow keys to rotate; scroll or use plus and minus to zoom.`} onKeyDown={keyboard} onPointerDown={e=>{drag.current=[e.clientX,e.clientY];e.currentTarget.setPointerCapture(e.pointerId);}} onPointerMove={e=>{if(!drag.current)return;const [x,y]=drag.current;drag.current=[e.clientX,e.clientY];setCamera(c=>({...c,yaw:c.yaw+(e.clientX-x)*.009,pitch:Math.max(-1.4,Math.min(1.4,c.pitch+(e.clientY-y)*.006))}));}} onPointerUp={()=>drag.current=null} onPointerCancel={()=>drag.current=null}/>

    </>:<div className="empty-viewer"><span aria-hidden="true">&#11041;</span><h3>Your object, from a new perspective.</h3><p>Upload a photo and review its CPU cutout before generating a model.</p><small>Real inference requires explicit enablement; cached demos stay separate.</small></div>}
    {status==='error'&&<div className="render-error" role="alert"><p>{error}</p><button className="secondary" onClick={()=>setRetry(n=>n+1)}>Reload GLB</button></div>}
    {(status==='loading'||state.busy)&&<div id="progress"><div className="spinner" aria-hidden="true"/><strong>{active?JOB_STAGES[active.stage]||'Queued':state.busy?'Cached-fixture job queued / running':'Loading the real GLB'}</strong><span>{active?'One sequential reconstruction job. Stages reflect actual worker events.':'Loading existing geometry; no new reconstruction is running.'}</span><small>{state.busy?'Queued jobs run automatically when their worker and resources are available.':'Reading stored geometry.'}</small></div>}
    </div>
      {status==='ready'&&<div className="model-caption"><span className="status-dot"/>{textured?'Photo texture':generated?'Hunyuan reconstruction':'Real GLB - cached fixture'}<small>{triangles.toLocaleString()} triangles - drag / arrow keys to rotate</small><small>Scroll / + and - to zoom</small></div>}
    <div className="stage-bottom">{generated&&<TexturePanel key={version.id} state={state} version={version} onView={url=>setTexture(url?{parent:version.id,url}:null)}/>}<div className="export-bar"><div><span className="cube" aria-hidden="true">&#11041;</span><strong>{version?`Version ${version.number} - ${generated?'reconstruction':'existing GLB'}`:'Your first perspective'}</strong><small>{version?(generated?'From selected confirmed cutouts':'Cached fixture; unrelated to uploaded photo'):'No model loaded'}</small></div>{version?<a className="download-glb" href={modelUrl} download>{textured?'Download textured GLB':generated?'Download GLB':'Download fixture GLB'}</a>:<button disabled>Download fixture GLB</button>}</div></div>
  </section>;
}
