"""CPU-only control plane; no Torch/model imports. Live execution is gated."""
import hashlib
import importlib.metadata
import io
import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from .config import PROJECT

MODEL = {'model':'tencent/Hunyuan3D-2mv','subfolder':'hunyuan3d-dit-v2-mv','variant':'fp16',
         'execution':'CPU offloading + CUDA','steps':30,'octree':256,'chunks':20000,'remove_bg':False}
STAGES = ('queued','loading_model','generating','saving_glb','validating_glb','completed')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=32)
def _file_digest(path, size, mtime):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def file_digest(path):
    stat=path.stat()
    return _file_digest(str(path.resolve()),stat.st_size,stat.st_mtime_ns)


def runner_manifest():
    paths=[PROJECT/'phase0_mv_test.py',Path(__file__),PROJECT/'orbit_backend/run_hunyuan.py',PROJECT/'orbit_backend/multiview.py',PROJECT/'orbit_backend/diagnostics.py',PROJECT/'orbit/lib/glb.mjs']
    paths+=sorted((PROJECT/'hy3dgen/shapegen').rglob('*.py'))
    code={p.relative_to(PROJECT).as_posix():file_digest(p) for p in paths}
    packages={}
    for package in ('torch','diffusers','accelerate','transformers','trimesh','safetensors'):
        packages[package]=importlib.metadata.version(package)
    # Resolve only existing cached model files. Never download weights in the API.
    directory=Path(os.path.expanduser(os.environ.get('HY3DGEN_MODELS','~/.cache/hy3dgen')))/MODEL['model']/MODEL['subfolder']
    artifacts={}
    for name in ('config.yaml','model.fp16.safetensors'):
        path=directory/name
        if not path.is_file():
            from huggingface_hub import try_to_load_from_cache
            cached=try_to_load_from_cache(MODEL['model'],f"{MODEL['subfolder']}/{name}")
            if not isinstance(cached,str):
                raise ValueError('Hunyuan model files must already be cached locally; automatic downloads are disabled.')
            path=Path(cached)
        artifacts[name]=file_digest(path)
    return {'code':code,'packages':packages,'modelFiles':artifacts,'schema':1}


def fingerprint(data,settings,manifest):
    config={**MODEL,'seed':settings.get('seed',12345)}
    if settings.get('seeds',1)!=1 or settings.get('steps',30)!=30 or settings.get('octree',256)!=256:
        raise ValueError('B4 requires one seed, 30 steps and octree 256; chunks are fixed to 20000.')
    if type(config['seed']) is not int or not 0<=config['seed']<=4294967295:
        raise ValueError('Seed must be an integer from 0 to 4294967295.')
    identity={'inputSha256':sha256(data),'config':config,'runner':manifest}
    return sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()),identity


def validate_mesh(path):
    """Validate both real geometry and compatibility with Orbit's exact GLB parser."""
    if not path.is_file() or not 20<path.stat().st_size<=64*1024*1024:
        raise ValueError('Missing, empty or oversized reconstruction GLB.')
    import numpy as np
    import trimesh
    data=path.read_bytes()
    scene=trimesh.load(io.BytesIO(data),file_type='glb',force='scene',process=False)
    meshes=list(scene.geometry.values())
    if not meshes or any(not isinstance(m,trimesh.Trimesh) or len(m.vertices)<3 or len(m.faces)<1 or
                         not np.isfinite(m.vertices).all() or m.faces.min()<0 or m.faces.max()>=len(m.vertices) for m in meshes):
        raise ValueError('Reconstruction contains no valid finite triangle mesh.')
    # CPU-only Node parsing; this does not create a WebGL context or use the GPU.
    subprocess.run(['node',str(PROJECT/'orbit/scripts/validate-glb.mjs'),str(path.resolve())],
                   cwd=PROJECT,check=True,capture_output=True,text=True,timeout=60)
    return {'sha256':sha256(data),'bytes':len(data),'triangles':sum(len(m.faces) for m in meshes)}


def cached_result(store,conn,key):
    row=conn.execute('SELECT * FROM reconstruction_cache WHERE fingerprint=?',(key,)).fetchone()
    if row:
        path=store.path(row['model'])
        if path.is_file() and 20<path.stat().st_size<=64*1024*1024 and file_digest(path)==row['sha256']:
            return dict(row)
        conn.execute('DELETE FROM reconstruction_cache WHERE fingerprint=?',(key,))
    return None


class HunyuanRunner:
    def __init__(self,enabled=False):
        self.enabled=enabled

    def command(self,input_path,outdir,identity,root):
        from .multiview import identity_hashes, ROLES
        paths=input_path if isinstance(input_path,dict) else {'front':input_path}
        if set(paths)!=set(identity_hashes(identity)):
            raise ValueError('Command inputs do not match the frozen role set.')
        c=identity['config']
        command=[str(PROJECT/'.venv/Scripts/python.exe'),'-u','-m','orbit_backend.run_hunyuan','--execute']
        for role in ROLES:
            if role in paths:command.extend(['--'+role,str(paths[role])])
        return command+['--outdir',str(outdir),'--seed',str(c['seed']),
                '--steps',str(c['steps']),'--octree',str(c['octree']),'--chunks',str(c['chunks']),
                '--input-sha256',identity['inputSha256'],'--identity',str(outdir/'identity.json'),
                '--gpu-lock',str(root/'gpu.lock')]

    def run(self,input_path,outdir,identity,root,on_stage):
        if not self.enabled or os.environ.get('ORBIT_ENABLE_GPU_JOBS')!='1':
            raise RuntimeError('Live Hunyuan execution is disabled pending explicit approval.')
        outdir.mkdir(parents=True,exist_ok=True)
        (outdir/'identity.json').write_text(json.dumps(identity,sort_keys=True),encoding='utf-8')
        env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_DATASETS_OFFLINE':'1'}
        command=self.command(input_path,outdir,identity,root)
        with (outdir/'runner.log').open('w',encoding='utf-8') as log:
            log.write('Command: '+subprocess.list2cmdline(command)+'\n');log.flush()
            process=subprocess.Popen(command,cwd=PROJECT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                     text=True,encoding='utf-8',errors='replace',bufsize=1)
            failure_stage='starting';classification='process_error'
            try:
                for line in process.stdout:
                    log.write(line);log.flush()
                    if line.startswith('ORBIT_DIAGNOSTIC:'):
                        try:
                            event=json.loads(line.split(':',1)[1])
                            failure_stage=event.get('stage',failure_stage)
                            if event.get('classification')=='cuda_oom':classification='cuda_oom'
                        except (ValueError,TypeError):pass
                    if 'cuda' in line.lower() and 'out of memory' in line.lower():classification='cuda_oom'
                    if line.startswith('ORBIT_STAGE:'):
                        stage=line.strip().split(':',1)[1]
                        failure_stage=stage
                        # Completion belongs exclusively to validated DB publication.
                        if stage in ('loading_model','generating','saving_glb'):on_stage(stage)
                code=process.wait()
                log.write(f'ORBIT_EXIT: {json.dumps({"exitCode":code,"failureStage":failure_stage if code else None,"classification":classification if code else "success"})}\n');log.flush()
                if code!=0:
                    raise RuntimeError(f'Hunyuan child process failed: {classification}, exit {code}, stage {failure_stage}. See the per-attempt runner.log.')
            finally:
                if process.poll() is None:
                    process.terminate();process.wait()
                process.stdout.close()
        return outdir/'mesh.glb'
