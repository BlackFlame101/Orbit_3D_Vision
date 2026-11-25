"""Texture submission and publication. Texture artifacts never enter the geometry cache."""
import hashlib
import io
import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image

from .storage import now, valid_id


class View(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    photo_id: str = Field(pattern='^[a-f0-9]{32}$')
    axes: tuple[tuple[float,float,float],tuple[float,float,float],tuple[float,float,float]]
    scale: float = Field(gt=0)
    offset: tuple[float,float]
    landmarks: list[tuple[float,float,float,float,float]] = Field(min_length=3,max_length=256)


class AutomaticView(BaseModel):
    model_config = ConfigDict(extra='forbid')
    photo_id: str = Field(pattern='^[a-f0-9]{32}$')
    mode: Literal['automatic']


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid')
    resolution: Literal[64,128,256,512,1024,2048]
    views: list[View | AutomaticView] = Field(min_length=1,max_length=5)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def implementation():
    files = ('photo_texture.py','texture_validator.py','texture_jobs.py','texture_child.py','uv_layout.py','texture_alignment.py','guidance.py')
    return {'code':{n:digest(Path(__file__).with_name(n).read_bytes()) for n in files},
            'packages':{n:version(n) for n in ('numpy','scipy','Pillow','xatlas','trimesh')}}


def camera(data,spec):
    import numpy as np
    from .photo_texture import Camera
    with Image.open(io.BytesIO(data)) as im:
        if im.format!='PNG' or im.mode!='RGBA':
            raise ValueError('Expected confirmed RGBA PNG cutout')
        cam=Camera(np.array(im),np.array(spec['axes']),spec['scale'],np.array(spec['offset']),np.array(spec['landmarks']))
    cam.check()
    xy=cam.landmarks[:,3:]
    if np.any(xy<0) or np.any(xy>=[cam.rgba.shape[1],cam.rgba.shape[0]]):
        raise ValueError('Calibration landmarks outside image')
    return cam


def frozen(store,data):
    sha=digest(data)
    name=f'texture/inputs/{sha}'
    path=store.path(name)
    if path.exists():
        if digest(path.read_bytes())!=sha: raise ValueError('Frozen texture input checksum mismatch')
    else: store.atomic_bytes(name,data)
    return sha


def submit(store,sid,vid,body):
    from .texture_validator import read_mesh
    valid_id(sid);valid_id(vid)
    with store.transaction() as c:
        parent=c.execute("""SELECT v.* FROM versions v JOIN jobs j ON j.id=v.job_id
            WHERE v.id=? AND v.session_id=? AND v.kind='hunyuan-reconstruction' AND j.status='completed'""",(vid,sid)).fetchone()
        if not parent: raise HTTPException(404,'Completed parent geometry not found')
        path=store.path(parent['model'])
        data=path.read_bytes()
        parent_sha=digest(data)
        if parent_sha!=json.loads(parent['snapshot']).get('modelSha256'):
            raise ValueError('Parent geometry checksum mismatch')
        try: read_mesh(path)
        except Exception as exc: raise ValueError('Unsupported parent GLB profile') from exc
        manifest={'parent':vid,'parentSha256':parent_sha,'resolution':body.resolution,'implementation':implementation(),'views':[]}
        snapshots=[data]
        roles=set()
        cutouts=set()
        for selected in sorted(body.views,key=lambda v:v.photo_id):
            row=c.execute('SELECT * FROM photos WHERE id=? AND session_id=?',(selected.photo_id,sid)).fetchone()
            if not row or not row['confirmed'] or row['status']!='ready' or not row['slot'] or row['slot'] in roles:
                raise ValueError('Select distinct confirmed photos with assigned roles')
            raw=store.path(row['original']).read_bytes()
            cut=store.path(row['cutout']).read_bytes()
            sha=digest(cut)
            if sha!=row['confirmed_sha256'] or sha in cutouts: raise ValueError('Conflicting or changed cutout')
            spec=selected.model_dump(mode='json')
            if isinstance(selected, AutomaticView):
                from .texture_alignment import TEXTURE_DIRECTIONS
                if row['slot'] not in TEXTURE_DIRECTIONS:
                    raise ValueError('Automatic alignment requires an assigned capture direction')
            else:
                camera(cut,spec)
            manifest['views'].append(dict(spec,role=row['slot'],name=row['name'],originalSha256=digest(raw),cutoutSha256=sha))
            snapshots.extend((raw,cut));roles.add(row['slot']);cutouts.add(sha)
        key=digest(canonical(manifest))
        existing=c.execute("SELECT * FROM jobs WHERE kind='texture' AND fingerprint=?",(key,)).fetchone()
        if existing:
            hit=existing['status']=='completed'
            if hit: verified_artifact(store,c,sid,existing['id'])
            return {'jobId':existing['id'],'status':existing['status'],'fingerprint':key,'cacheHit':hit}
        for data in snapshots: frozen(store,data)
        jid=store.enqueue(c,sid,'texture',manifest,fingerprint=key)
        return {'jobId':jid,'status':'queued','fingerprint':key,'cacheHit':False}


def verified_artifact(store,c,sid,jid):
    row=c.execute('SELECT * FROM texture_artifacts WHERE session_id=? AND job_id=?',(sid,jid)).fetchone()
    if not row: raise HTTPException(404,'Texture artifact unavailable')
    path=store.path(row['model'])
    if not path.is_file() or digest(path.read_bytes())!=row['sha256']:
        raise HTTPException(409,'Texture cache integrity check failed')
    return row


def routes(api,store):
    @api.post('/sessions/{sid}/versions/{vid}/textures')
    def submit_texture(sid:str,vid:str,body:Request):
        return submit(store,sid,vid,body)

    @api.get('/sessions/{sid}/textures/{jid}')
    def texture_info(sid:str,jid:str):
        with store.transaction() as c:
            row=verified_artifact(store,c,sid,jid)
            return {'parentVersionId':row['parent_id'],'sha256':row['sha256'],'fingerprint':row['fingerprint'],
                    'manifest':json.loads(row['manifest']),'metrics':json.loads(row['metrics']),
                    'modelUrl':f'/api/orbit/sessions/{sid}/textures/{jid}/model.glb'}

    @api.get('/sessions/{sid}/textures/{jid}/model.glb')
    def texture_model(sid:str,jid:str):
        with store.transaction() as c: row=verified_artifact(store,c,sid,jid)
        return FileResponse(store.path(row['model']),media_type='model/gltf-binary',filename=f'texture-{jid}.glb')


class TextureFailure(Exception):
    pass


def execute(store,job):
    from .texture_validator import validate
    manifest=json.loads(job['payload'])
    key=job['fingerprint']
    run=store.path(f"texture/runs/{job['id']}/attempt-{job['attempts']+1}")
    run.mkdir(parents=True,exist_ok=False)
    source=store.path('texture/inputs')
    output=run/'candidate.glb'
    try:
        if digest(canonical(manifest))!=key or implementation()!=manifest['implementation']:
            raise TextureFailure('input: frozen manifest or baker identity changed')
        (run/'manifest.json').write_bytes(canonical(manifest))
        env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
        with (run/'runner.log').open('w',encoding='utf8') as log:
            stages={'input':15,'calibration':25,'uv':40,'projection':55,'glb_validation':90}
            with subprocess.Popen([sys.executable,'-B','-m','orbit_backend.texture_child',str(run),str(source)],
                    cwd=Path(__file__).resolve().parents[1],env=env,stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,text=True,errors='replace') as process:
                for line in process.stdout:
                    log.write(line);log.flush()
                    try: event=json.loads(line)
                    except ValueError: continue
                    stage=event.get('stage') if isinstance(event,dict) else None
                    if stage in stages:
                        with store.transaction() as c:
                            c.execute("UPDATE jobs SET stage=?,progress=max(progress,?),updated=? WHERE id=?",
                                      (stage,stages[stage],now(),job['id']))
            log.write(json.dumps({'exitCode':process.returncode})+'\n')
        if process.returncode:
            failure=run/'failure.json'
            report=json.loads(failure.read_text()) if failure.exists() else {}
            reason=report.get('category', 'memory' if process.returncode in (-1073741801,3221225495) else 'subprocess')
            if reason=='calibration' and report.get('detail','').startswith('Automatic alignment too weak'):
                raise TextureFailure('calibration: '+report['detail'])
            raise TextureFailure(f'{reason}: texture subprocess failed (exit {process.returncode})')
        with store.transaction() as c:
            parent=c.execute('SELECT model FROM versions WHERE id=? AND session_id=?',(manifest['parent'],job['session_id'])).fetchone()
            if not parent or digest(store.path(parent['model']).read_bytes())!=manifest['parentSha256']:
                raise TextureFailure('input: parent changed before publication')
            validate(store.path(parent['model']),output)
            data=output.read_bytes()
            relative=f'texture/cache/{key}/model.glb'
            store.atomic_bytes(relative,data)
            c.execute('INSERT INTO texture_artifacts VALUES(?,?,?,?,?,?,?,?,?)',(job['id'],job['session_id'],manifest['parent'],key,relative,digest(data),job['payload'],(run/'metrics.json').read_text(),now()))
            c.execute("UPDATE jobs SET status='completed',stage='completed',progress=100,error=NULL,updated=? WHERE id=?",(now(),job['id']))
    except TextureFailure: raise
    except MemoryError as exc: raise TextureFailure('memory: texture publication failed') from exc
    except Exception as exc: raise TextureFailure('glb_validation: texture publication failed') from exc
