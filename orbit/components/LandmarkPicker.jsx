import {useEffect,useRef,useState} from 'react';
import {createGLBRenderer} from '../lib/glb.mjs';
import {calibrationMesh,pickPoint} from '../lib/calibration.mjs';

export default function LandmarkPicker({version,photo,add}){
  const canvas=useRef(null),model=useRef(null),renderer=useRef(null);
  const [pose,setPose]=useState({yaw:0,pitch:0,zoom:.8}),[pixel,setPixel]=useState(null),[message,setMessage]=useState('');
  useEffect(()=>{
    const controller=new AbortController();
    async function load(){
      try{
        const r=await fetch(version.modelUrl,{signal:controller.signal});
        if(!r.ok)throw new Error('Geometry unavailable');
        const mesh=calibrationMesh(await r.arrayBuffer());
        if(controller.signal.aborted)return;
        model.current=mesh;renderer.current=createGLBRenderer(canvas.current,mesh.mesh);
        renderer.current.draw({yaw:0,pitch:0,zoom:.8});setPose({yaw:0,pitch:0,zoom:.8});
      }catch(e){if(!controller.signal.aborted)setMessage(e.message);}
    }
    load();return()=>{controller.abort();renderer.current?.dispose();renderer.current=null;model.current=null;};
  },[version.modelUrl]);
  useEffect(()=>{renderer.current?.draw(pose);},[pose]);
  function pick(e){
    if(!pixel||!model.current)return;
    const rect=e.currentTarget.getBoundingClientRect();
    const xyz=pickPoint(model.current,pose,rect.width/rect.height,2*(e.clientX-rect.left)/rect.width-1,1-2*(e.clientY-rect.top)/rect.height);
    if(!xyz){setMessage('Click on the mesh surface.');return;}
    add([...xyz,...pixel]);setPixel(null);setMessage('Landmark pair added.');
  }
  return <section><p>{pixel?'Click the matching surface point on the mesh.':'Click an identifiable point on the cutout.'}</p>
    <div className="landmark-pair"><img src={photo.cutoutUrl} alt={'Landmark photo '+photo.name} onClick={e=>{
      const img=e.currentTarget,r=img.getBoundingClientRect();
      setPixel([Math.max(0,Math.min(img.naturalWidth-1,(e.clientX-r.left)*img.naturalWidth/r.width-.5)),Math.max(0,Math.min(img.naturalHeight-1,(e.clientY-r.top)*img.naturalHeight/r.height-.5))]);
    }}/><canvas ref={canvas} aria-label="Pick a corresponding mesh landmark" onClick={pick}/></div>
    {['Left','Right','Up','Down'].map((label,i)=><button key={label} onClick={()=>setPose(p=>({...p,yaw:p.yaw+[-.25,.25,0,0][i],pitch:p.pitch+[0,0,.25,-.25][i]}))}>{label}</button>)}
    <small role="status">{message}</small></section>;
}
