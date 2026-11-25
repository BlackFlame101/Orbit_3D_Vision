"""Immutable inputs, validated cache publication, and per-job model provenance."""
import json
import subprocess
from .inference import cached_result, file_digest, runner_manifest, validate_mesh
from .storage import now
from .multiview import snapshot_paths, compatible_runner, legacy_cached_result, MAPPING_REVISION


def publish(store,conn,job,payload,source,sha,cache_hit=False):
    data=source.read_bytes()
    from .inference import sha256
    if sha256(data)!=sha:
        raise ValueError('Model changed before publication.')
    relative=f"sessions/{job['session_id']}/versions/{job['id']}/model.glb"
    store.atomic_bytes(relative,data)
    snapshot={**payload['snapshot'],'cacheHit':cache_hit,'modelSha256':sha}
    snapshot.setdefault('mode','front_only')
    snapshot.setdefault('views',['front'])
    snapshot.setdefault('mappingRevision',MAPPING_REVISION)
    conn.execute('INSERT OR IGNORE INTO versions(id,session_id,job_id,kind,model,source,snapshot,created) VALUES(?,?,?,?,?,?,?,?)',
                 (job['id'],job['session_id'],job['id'],'hunyuan-reconstruction',relative,'Hunyuan3D-2mv from confirmed '+', '.join(snapshot['views'])+' cutout(s)',json.dumps(snapshot),now()))
    conn.execute('UPDATE sessions SET selected_id=? WHERE id=?',(job['id'],job['session_id']))
    conn.execute("UPDATE jobs SET status='completed',stage='completed',progress=100,error=NULL,updated=? WHERE id=?",(now(),job['id']))


def execute(worker,job):
    store=worker.store
    payload=json.loads(job['payload'])
    identity=payload['identity']
    sources=snapshot_paths(store,payload)
    source=sources if len(sources)>1 else sources['front']
    current_runner=runner_manifest()
    if not compatible_runner(identity['runner'],current_runner,legacy='schema' not in identity):
        raise ValueError('Engine/model version changed after enqueue. Submit a new job.')
    if identity['runner']!=current_runner:
        payload['snapshot']['runnerCompatibility']='audited-b4-front-only' if 'schema' not in identity else 'audited-c2-c5-diagnostics'
    with store.transaction() as c:
        cached=cached_result(store,c,job['fingerprint']) or legacy_cached_result(store,c,identity)
        if cached:
            if cached.get('compatibilityReuse'):
                payload['snapshot']['cacheOriginFingerprint']=cached['fingerprint']
                payload['snapshot']['cacheCompatibility']=cached['compatibilityName']
            publish(store,c,job,payload,store.path(cached['model']),cached['sha256'],True)
            return
    def stage(value):
        milestones={'loading_model':15,'generating':25,'extracting_mesh':85,'saving_glb':90,'validating_glb':95}
        if value.startswith('sampling:'):
            step=value.removeprefix('sampling:')
            total=identity['config']['steps']
            if not step.isascii() or not step.isdecimal() or not 1<=int(step)<=total:
                return
            progress=25+int(55*int(step)/total)
            value='generating'
        elif value in milestones:
            progress=milestones[value]
        else:
            return
        with store.transaction() as c:
            c.execute("UPDATE jobs SET stage=?,progress=?,updated=? WHERE id=? AND status='running' AND progress<=?",(value,progress,now(),job['id'],progress))
            c.execute('UPDATE worker_status SET heartbeat=? WHERE id=1',(now(),))
    # Recover already-completed child outputs without repeating expensive inference.
    recovered=None
    validation=None
    for receipt in sorted(store.root.glob(f"runs/{job['id']}/attempt-*/success.json"),reverse=True):
        try:
            checkpoint=json.loads(receipt.read_text(encoding='utf-8'))
            mesh=receipt.parent/'mesh.glb'
            if checkpoint['identity']==identity and file_digest(mesh)==checkpoint['meshSha256']:
                validation=validate_mesh(mesh)
                recovered=mesh
                break
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):
            continue
    if recovered is None:
        outdir=store.path(f"runs/{job['id']}/attempt-{job['attempts']+1}")
        outdir.mkdir(parents=True,exist_ok=True)
        recovered=worker.runner.run(source,outdir,identity,store.root,stage)
    stage('validating_glb')
    validation=validation or validate_mesh(recovered)
    cache_path=f"cache/{job['fingerprint']}/mesh.glb"
    store.atomic_bytes(cache_path,recovered.read_bytes())
    with store.transaction() as c:
        c.execute('INSERT OR REPLACE INTO reconstruction_cache(fingerprint,model,sha256,manifest,created) VALUES(?,?,?,?,?)',
                  (job['fingerprint'],cache_path,validation['sha256'],json.dumps(identity),now()))
        publish(store,c,job,payload,store.path(cache_path),validation['sha256'])
