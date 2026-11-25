"""Loopback Orbit API; B4 inference submissions are disabled by default."""
import json
import hashlib
import io
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from PIL import Image
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import Config
from .images import decode, png_bytes, validate_cutout
from .storage import Store, identifier, now, valid_id
from .inference import fingerprint, runner_manifest, cached_result
from .multiview import canonical_roles, selection_identity, write_snapshots, legacy_cached_result, MAPPING_REVISION, VIEW_INDICES

SLOTS = ('front', 'left', 'back', 'right', 'top')
Slot = Literal['front', 'left', 'back', 'right', 'top']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Settings(StrictModel):
    seeds: Literal[1] = 1
    steps: Literal[20, 30, 50] = 30
    octree: Literal[256, 384] = 256
    seed: int = Field(default=12345,ge=0,le=4294967295,strict=True)


class CalibrationFit(StrictModel):
    landmarks: list[tuple[float,float,float,float,float]] = Field(min_length=4,max_length=256)


class SessionEdit(StrictModel):
    budget: Literal[2, 3, 4, 5] | None = None
    settings: Settings | None = None
    selectedId: str | None = None


class PhotoEdit(StrictModel):
    slot: Slot


class Confirmation(StrictModel):
    confirmed: Literal[True]


class MockRequest(StrictModel):
    photo_id: str
    fixture: Literal['perfume', 'mug'] = 'perfume'


class SelectedPhoto(StrictModel):
    photo_id: str
    role: Literal['front','left','back','right']


class ReconstructionRequest(StrictModel):
    photo_id: str | None = None
    mode: Literal['front_only','multiview'] = 'front_only'
    photos: list[SelectedPhoto] | None = Field(default=None,min_length=1,max_length=4)

    @model_validator(mode='after')
    def validate_selection(self):
        if (self.photo_id is None)==(self.photos is None):
            raise ValueError('Supply either legacy photo_id or an explicit photos selection, not both.')
        if self.photo_id is not None:
            if self.mode!='front_only':raise ValueError('Legacy photo_id supports front_only mode only.')
        else:
            canonical_roles(self.mode,[p.role for p in self.photos])
            if len({p.photo_id for p in self.photos})!=len(self.photos):raise ValueError('A photo cannot be selected for multiple roles.')
        return self

    def selected(self):
        if self.photo_id is not None:return [('front',self.photo_id)]
        by_role={p.role:p.photo_id for p in self.photos}
        return [(r,by_role[r]) for r in canonical_roles(self.mode,by_role)]


def create_app(config=None):
    config = config or Config()
    store = Store(config)
    api = FastAPI(title='Orbit B1-B3', version='0.2.0')
    api.state.store = store
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @api.middleware('http')
    async def local_requests(request: Request, call_next):
        origin = request.headers.get('origin')
        if origin and origin not in config.allowed_origins:
            return JSONResponse({'detail': 'Only local Orbit origins are allowed.'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('x-orbit-client') != '1':
                return JSONResponse({'detail': 'Missing Orbit request header.'}, status_code=403)
            try:
                length = int(request.headers.get('content-length', '0'))
            except ValueError:
                return JSONResponse({'detail': 'Invalid request length.'}, status_code=400)
            if length > config.max_bytes + 1024 * 1024:
                return JSONResponse({'detail': 'Request exceeds the upload limit.'}, status_code=413)
            # Also bound chunked requests before multipart parsing/spooling.
            receive = request._receive
            received = 0
            async def limited_receive():
                nonlocal received
                message = await receive()
                received += len(message.get('body', b''))
                if received > config.max_bytes + 1024 * 1024:
                    raise HTTPException(413, 'Request exceeds the upload limit.')
                return message
            request._receive = limited_receive
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @api.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=422)

    def require_session(conn, sid, editable=False):
        valid_id(sid)
        row = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
        if not row:
            raise HTTPException(404, 'Session not found.')
        if editable and conn.execute("SELECT 1 FROM jobs WHERE session_id=? AND kind IN ('mock_reconstruct','reconstruct') AND status IN ('queued','running')", (sid,)).fetchone():
            raise HTTPException(409, 'A model job is active. Wait for it before editing inputs.')
        return row

    def require_photo(conn, sid, pid):
        require_session(conn, sid)
        valid_id(pid)
        row = conn.execute('SELECT * FROM photos WHERE id=? AND session_id=?', (pid, sid)).fetchone()
        if not row:
            raise HTTPException(404, 'Photo not found in this session.')
        return row

    @api.get('/health')
    def health():
        with store.transaction() as c:
            c.execute('SELECT 1')
            from .dispatch import online_workers
            roles=online_workers(c)
            worker = c.execute('SELECT heartbeat,gpu_enabled FROM worker_status WHERE id=1').fetchone()
            latest=c.execute('SELECT MAX(heartbeat) FROM worker_roles').fetchone()[0]
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(worker['heartbeat'])).total_seconds() if worker else None
        if latest:age=(datetime.now(timezone.utc)-datetime.fromisoformat(latest)).total_seconds()
        return {'status': 'ok', 'mode': 'B4; real reconstruction enabled' if config.enable_gpu_jobs else 'B1-B3; GPU inference disabled', 'database': 'ok',
                'workers':{'cpu':bool(roles.get('cpu')),'gpu':bool(roles.get('gpu'))}, 'workerSeen': any(roles.values()) or bool(worker and age is not None and age<20), 'workerHeartbeatAgeSeconds': age, 'fixtures': list(config.fixtures),
                'gpuSubmissionEnabled':config.enable_gpu_jobs,'workerGpuEnabled':bool(roles.get('gpu') or (not roles and worker and age<20 and worker['gpu_enabled']))}

    @api.get('/fixtures')
    def fixtures():
        return [{'id': k, 'label': f'Existing {k} Hunyuan GLB', 'kind': 'cached-fixture',
                 'notice': 'Viewer fixture only. Not generated from the newly uploaded photo.'} for k in config.fixtures]

    @api.post('/sessions', status_code=201)
    def new_session():
        sid = identifier()
        with store.transaction() as c:
            c.execute('INSERT INTO sessions(id,created,settings) VALUES(?,?,?)', (sid, now(), json.dumps(Settings().model_dump())))
        return store.session(sid)

    @api.get('/sessions/{sid}')
    def get_session(sid: str):
        result = store.session(sid)
        if not result:
            raise HTTPException(404, 'Session not found.')
        return result

    @api.patch('/sessions/{sid}')
    def edit_session(sid: str, body: SessionEdit):
        with store.transaction() as c:
            require_session(c, sid, editable=True)
            if body.budget is not None:
                n = c.execute('SELECT COUNT(*) FROM photos WHERE session_id=?', (sid,)).fetchone()[0]
                if n > body.budget:
                    raise HTTPException(409, 'Remove photos before lowering the budget.')
                c.execute('UPDATE sessions SET budget=? WHERE id=?', (body.budget, sid))
            if body.settings is not None:
                c.execute('UPDATE sessions SET settings=? WHERE id=?', (json.dumps(body.settings.model_dump()), sid))
            if body.selectedId:
                valid_id(body.selectedId)
                if not c.execute('SELECT 1 FROM versions WHERE id=? AND session_id=?', (body.selectedId, sid)).fetchone():
                    raise HTTPException(404, 'Version not found.')
                c.execute('UPDATE sessions SET selected_id=? WHERE id=?', (body.selectedId, sid))
        return store.session(sid)

    @api.post('/sessions/{sid}/photos', status_code=201)
    async def upload(sid: str, image: UploadFile = File(...), slot: Slot | None = Form(None)):
        # File names are display-only; paths are generated from opaque server IDs.
        data = await image.read(config.max_bytes + 1)
        original = decode(data, config)
        pid = identifier()
        relative = f'sessions/{sid}/photos/{pid}/original.png'
        written = False
        try:
            with store.transaction() as c:
                session = require_session(c, sid, editable=True)
                n = c.execute('SELECT COUNT(*) FROM photos WHERE session_id=?', (sid,)).fetchone()[0]
                if n >= session['budget']:
                    raise HTTPException(409, 'Photo budget reached.')
                if slot and c.execute('SELECT 1 FROM photos WHERE session_id=? AND slot=?', (sid, slot)).fetchone():
                    raise HTTPException(409, 'This viewpoint is occupied. Choose another or change the existing assignment.')
                store.atomic_bytes(relative, png_bytes(original))
                written = True
                name = (image.filename or 'photo')[:200].replace('\\', '/').rsplit('/', 1)[-1]
                c.execute('INSERT INTO photos(id,session_id,name,slot,original,status,created) VALUES(?,?,?,?,?,?,?)',
                          (pid, sid, name, slot, relative, 'queued', now()))
                jid = store.enqueue(c, sid, 'preprocess', {}, pid)
        except BaseException:
            if written:
                store.path(relative).unlink(missing_ok=True)
            raise
        return {'photo_id': pid, 'job_id': jid, 'session': store.session(sid)}

    @api.patch('/sessions/{sid}/photos/{pid}')
    def assign(sid: str, pid: str, body: PhotoEdit):
        with store.transaction() as c:
            require_session(c, sid, editable=True)
            photo = require_photo(c, sid, pid)
            occupied = c.execute('SELECT id FROM photos WHERE session_id=? AND slot=? AND id<>?', (sid, body.slot, pid)).fetchone()
            c.execute('UPDATE photos SET slot=NULL,confirmed=0 WHERE id=?', (pid,))
            if occupied:
                c.execute('UPDATE photos SET slot=?,confirmed=0 WHERE id=?', (photo['slot'], occupied['id']))
            c.execute('UPDATE photos SET slot=?,confirmed=0 WHERE id=?', (body.slot, pid))
        return store.session(sid)

    @api.post('/sessions/{sid}/photos/{pid}/confirm')
    def confirm(sid: str, pid: str, body: Confirmation):
        with store.transaction() as c:
            require_session(c, sid, editable=True)
            photo = require_photo(c, sid, pid)
            if not photo['slot'] or photo['status'] != 'ready' or not photo['cutout']:
                raise HTTPException(409, 'A valid processed cutout and manual viewpoint are required before confirmation.')
            if not json.loads(photo['validation'])['valid']:
                raise HTTPException(409, 'This cutout failed backend validation.')
            path=store.path(photo['cutout'])
            with Image.open(path) as cutout:
                if not validate_cutout(cutout)['valid']:
                    raise HTTPException(409,'The cutout changed or failed validation. Process and review it again.')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            c.execute('UPDATE photos SET confirmed=1,confirmed_sha256=? WHERE id=?', (digest,pid))
        return store.session(sid)

    @api.delete('/sessions/{sid}/photos/{pid}')
    def remove_photo(sid: str, pid: str):
        with store.transaction() as c:
            require_session(c, sid, editable=True)
            photo = require_photo(c, sid, pid)
            if c.execute("SELECT 1 FROM jobs WHERE photo_id=? AND status IN ('queued','running')", (pid,)).fetchone():
                raise HTTPException(409, 'Wait for preprocessing before removing this photo.')
            c.execute('UPDATE jobs SET photo_id=NULL WHERE photo_id=?', (pid,))
            c.execute('DELETE FROM photos WHERE id=?', (pid,))
        for relative in (photo['original'], photo['cutout']):
            if relative:
                store.path(relative).unlink(missing_ok=True)
        return store.session(sid)

    @api.get('/sessions/{sid}/photos/{pid}/{kind}')
    def image_file(sid: str, pid: str, kind: Literal['original', 'cutout']):
        with store.transaction() as c:
            photo = require_photo(c, sid, pid)
        relative = photo[kind]
        if not relative or not store.path(relative).is_file():
            raise HTTPException(404, 'Image is not available yet.')
        return FileResponse(store.path(relative), media_type='image/png')

    @api.post('/sessions/{sid}/jobs', status_code=202)
    def mock_job(sid: str, body: MockRequest):
        if body.fixture not in config.fixtures:
            raise HTTPException(409, 'Requested cached GLB fixture is unavailable.')
        with store.transaction() as c:
            session = require_session(c, sid, editable=True)
            photo = require_photo(c, sid, body.photo_id)
            if photo['slot'] != 'front' or not photo['confirmed'] or photo['status'] != 'ready':
                raise HTTPException(409, 'Confirm a valid processed front photograph first.')
            snapshot = {'photos': [{'id': photo['id'], 'name': photo['name'], 'slot': 'front', 'hasCutout': True}],
                        'settings': json.loads(session['settings']), 'budget': session['budget'], 'fixture': body.fixture,
                        'notice': 'Cached viewer fixture, not a reconstruction of this input.'}
            jid = store.enqueue(c, sid, 'mock_reconstruct', {'fixture': body.fixture, 'snapshot': snapshot})
        return {'job_id': jid, 'session': store.session(sid)}

    @api.get('/sessions/{sid}/jobs/{jid}')
    def job_status(sid: str, jid: str):
        valid_id(jid)
        session = get_session(sid)
        job = next((j for j in session['jobs'] if j['id'] == jid), None)
        if not job:
            raise HTTPException(404, 'Job not found.')
        return job

    @api.post('/sessions/{sid}/reconstructions',status_code=202)
    def reconstruct(sid: str,body: ReconstructionRequest):
        if not config.enable_gpu_jobs:
            raise HTTPException(403,'Real reconstruction is disabled pending explicit approval. Cached-fixture jobs remain available.')
        with store.transaction() as c:
            session=require_session(c,sid)
            images={}
            photos=[]
            for role,pid in body.selected():
                photo=require_photo(c,sid,pid)
                if photo['slot']!=role or not photo['confirmed'] or photo['status']!='ready' or not photo['cutout']:
                    raise HTTPException(409,f'Confirm a valid processed photo assigned to the selected {role} role first.')
                try:
                    data=store.path(photo['cutout']).read_bytes()
                    if not photo['confirmed_sha256'] or hashlib.sha256(data).hexdigest()!=photo['confirmed_sha256']:
                        raise HTTPException(409,f'{role} input changed since confirmation. Review and confirm it again.')
                    with Image.open(io.BytesIO(data)) as cutout:
                        if not validate_cutout(cutout)['valid']:raise ValueError('Invalid cutout')
                except (OSError,ValueError):
                    raise HTTPException(409,f'{role} cutout is missing, unreadable or invalid. Process and review it again.')
                images[role]=data
                photos.append({'id':photo['id'],'name':photo['name'],'slot':role,'role':role,'modelViewIndex':VIEW_INDICES[role],
                               'hasCutout':True,'sha256':photo['confirmed_sha256']})
            settings=json.loads(session['settings'])
            key,identity=selection_identity(images,settings,runner_manifest(),body.mode)
            active=c.execute("SELECT * FROM jobs WHERE session_id=? AND kind IN ('reconstruct','mock_reconstruct') AND status IN ('queued','running')",(sid,)).fetchone()
            if active:
                if active['kind']!='reconstruct' or active['fingerprint']!=key:
                    raise HTTPException(409,'Another model job is already active in this session.')
                jid=active['id']
            else:
                try:
                    inputs=write_snapshots(store,key,images)
                except OSError:
                    raise HTTPException(503,'Could not save the full immutable input set. No reconstruction job was queued.')
                snapshot={'photos':photos,'mode':body.mode,'views':list(images),'mappingRevision':MAPPING_REVISION,
                          'settings':{**settings,'seed':identity['config']['seed']},'budget':session['budget'],
                          'fingerprint':key,'notice':'Hunyuan3D-2mv from explicitly selected and confirmed '+', '.join(images)+' cutout(s). Physical directions are user-reviewed, not inferred.'}
                payload={'identity':identity,'input':inputs['front'],'inputs':inputs,'snapshot':snapshot}
                jid=store.enqueue(c,sid,'reconstruct',payload,photos[0]['id'],key)
                cached=cached_result(store,c,key) or legacy_cached_result(store,c,identity)
                if cached:
                    from .reconstruction import publish
                    job=dict(id=jid,session_id=sid,fingerprint=key)
                    if cached.get('compatibilityReuse'):
                        payload['snapshot']['cacheOriginFingerprint']=cached['fingerprint']
                        payload['snapshot']['cacheCompatibility']=cached['compatibilityName']
                    publish(store,c,job,payload,store.path(cached['model']),cached['sha256'],cache_hit=True)
        return {'job_id':jid,'session':store.session(sid)}

    @api.post('/sessions/{sid}/jobs/{jid}/retry')
    def retry(sid: str, jid: str):
        valid_id(jid)
        with store.transaction() as c:
            require_session(c, sid, editable=True)
            job = c.execute('SELECT * FROM jobs WHERE id=? AND session_id=?', (jid, sid)).fetchone()
            if not job:
                raise HTTPException(404, 'Job not found.')
            if job['status'] != 'failed' or job['attempts'] >= 3:
                raise HTTPException(409, 'Only failed jobs with fewer than three attempts can be retried.')
            if job['kind']=='reconstruct' and not config.enable_gpu_jobs:
                raise HTTPException(403,'Live reconstruction retries are disabled pending explicit approval.')
            if job['kind'] == 'preprocess':
                if not job['photo_id']:
                    raise HTTPException(409, 'The photo was removed; upload a new photo instead.')
                require_photo(c, sid, job['photo_id'])
                c.execute("UPDATE photos SET status='queued',error=NULL,confirmed=0 WHERE id=?", (job['photo_id'],))
            c.execute("UPDATE jobs SET status='queued',stage='queued',progress=0,error=NULL,updated=? WHERE id=?", (now(), jid))
        return store.session(sid)

    @api.get('/sessions/{sid}/versions/{vid}/model.glb')
    def model_file(sid: str, vid: str):
        valid_id(vid)
        with store.transaction() as c:
            require_session(c, sid)
            row = c.execute('SELECT * FROM versions WHERE id=? AND session_id=?', (vid, sid)).fetchone()
        if not row or not store.path(row['model']).is_file():
            raise HTTPException(404, 'Model not found.')
        return FileResponse(store.path(row['model']), media_type='model/gltf-binary', filename=f'orbit-{row["kind"]}-{vid}.glb')

    @api.get('/sessions/{sid}/versions/{vid}/guidance')
    def view_guidance(sid: str, vid: str):
        from .guidance import cached_coverage
        with store.transaction() as c:
            require_session(c, sid)
            row = c.execute('SELECT * FROM versions WHERE id=? AND session_id=?',(vid,sid)).fetchone()
            if not row or row['kind'] != 'hunyuan-reconstruction':
                raise HTTPException(404,'Reconstructed geometry required')
            slots = tuple(r[0] for r in c.execute('SELECT DISTINCT slot FROM photos WHERE session_id=? AND confirmed=1 AND slot IS NOT NULL ORDER BY slot',(sid,)))
        return cached_coverage(store.path(row['model']),json.loads(row['snapshot'])['modelSha256'],slots)

    @api.post('/calibration/orthographic')
    def calibration_fit(body: CalibrationFit):
        from .calibration import fit_camera
        try:
            return fit_camera(body.landmarks)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    from .texture_jobs import routes as texture_routes
    texture_routes(api,store)
    return api


# Factory mode avoids writing runtime data simply by importing the module in tests.
def app_factory():
    return create_app()
