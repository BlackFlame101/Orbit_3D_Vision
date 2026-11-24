"""Sequential worker. CPU/mock by default; GPU jobs need two explicit switches."""
import argparse
import hashlib
import json
import logging
import os
import struct
import time
from contextlib import contextmanager, ExitStack
from pathlib import Path
import signal
import threading
from .dispatch import LocalQueue

from PIL import Image
from .config import Config
from .images import CPURemover, png_bytes, preprocess
from .storage import Store, identifier, now
from .inference import HunyuanRunner

log = logging.getLogger('orbit.worker')


@contextmanager
def worker_lock(store,lock_name='worker.lock'):
    # OS releases the lock on crash; one worker owns recovery and processing.
    if lock_name not in ('worker.lock','gpu.lock','gpu-worker.lock'):
        raise ValueError('Unsupported worker lock name.')
    with (store.root / lock_name).open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            if lock_name in ('worker.lock','gpu-worker.lock'):store.worker_lock_owned=True
            yield
        finally:
            if lock_name in ('worker.lock','gpu-worker.lock'):store.worker_lock_owned=False
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def check_glb(data):
    if len(data) < 20 or data[:4] != b'glTF' or struct.unpack_from('<I', data, 4)[0] != 2 or struct.unpack_from('<I', data, 8)[0] != len(data):
        raise ValueError('The cached fixture is not a valid GLB v2 file.')


class Worker:
    def __init__(self, store, remover=None, allow_gpu=False, runner=None, queue=None):
        self.store = store
        self.queue = queue
        self.remover = remover if remover is not None else CPURemover()
        self.allow_gpu=bool(allow_gpu and store.config.enable_gpu_jobs)
        self.runner=runner if runner is not None else HunyuanRunner(enabled=self.allow_gpu)

    def recover(self):
        # Call only after acquiring worker_lock; never reset a live worker's jobs.
        with self.store.transaction() as c:
            kinds=self.queue.kinds if self.queue else ('preprocess','mock_reconstruct','texture','reconstruct')
            marks=','.join('?' for _ in kinds)
            if 'reconstruct' in kinds:
                for job in c.execute("SELECT id,attempts FROM jobs WHERE kind='reconstruct' AND status='running'").fetchall():
                    path=self.store.path(f"runs/{job['id']}/attempt-{job['attempts']}/runner.log")
                    if path.is_file():
                        with path.open('rb') as stream:
                            stream.seek(max(0,path.stat().st_size-8192))
                            oom=b'cuda_oom' in stream.read().lower()
                        if oom:
                            c.execute("UPDATE jobs SET status='failed',stage='failed',error='CUDA out of memory; explicit retry required.',updated=? WHERE id=?",(now(),job['id']))
            c.execute(f"""UPDATE jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,
                      owner=NULL,error='Worker interrupted.',updated=? WHERE status='running' AND kind IN ({marks})""",(now(),*kinds))
            c.execute(f"UPDATE jobs SET stage=status WHERE status IN ('queued','failed') AND kind IN ({marks})",kinds)
            c.execute("UPDATE photos SET status='failed',confirmed=0,error='Worker interrupted after three attempts. Remove and re-upload this photo.' WHERE id IN (SELECT photo_id FROM jobs WHERE kind='preprocess' AND status='failed' AND attempts>=3)")

    def tick(self,job_id=None):
        if self.allow_gpu and not getattr(self.store,'worker_lock_owned',False):
            raise RuntimeError('A GPU-enabled worker must own the worker lock before processing jobs.')
        if self.queue:
            job=self.queue.claim(job_id)
            if job is None:return False
        else:
            with self.store.transaction() as c:
                c.execute('INSERT OR REPLACE INTO worker_status(id,heartbeat,gpu_enabled) VALUES(1,?,?)', (now(),int(self.allow_gpu)))
                job = c.execute("SELECT * FROM jobs WHERE status='queued' AND (kind<>'reconstruct' OR ?) AND (? IS NULL OR id=?) ORDER BY created,id LIMIT 1",(self.allow_gpu,job_id,job_id)).fetchone()
                if not job:
                    return False
                job = dict(job)
                c.execute("UPDATE jobs SET status='running',attempts=attempts+1,progress=10,error=NULL,updated=? WHERE id=?", (now(), job['id']))
        log.info('Claimed job %s kind=%s attempt=%d',job['id'],job['kind'],job['attempts']+1)
        try:
            if job['kind'] == 'preprocess':
                self.process_photo(job)
            elif job['kind'] == 'mock_reconstruct':
                self.mock_model(job)
            elif job['kind']=='texture':
                from .texture_jobs import execute as execute_texture
                execute_texture(self.store,job)
            elif job['kind']=='reconstruct':
                from .reconstruction import execute
                execute(self,job)
            else:
                raise ValueError('Unsupported job kind.')
        except Exception as exc:
            log.exception('Job failed: %s', job['id'])
            # Paths and exception traces stay local; UI gets a safe actionable message.
            with self.store.transaction() as c:
                error = 'Preprocessing failed. Check the worker log and cached U2NET_HOME model; no GPU ran.' if job['kind'] == 'preprocess' else 'Reconstruction failed. Inspect the worker/per-attempt logs; no new model was published.' if job['kind']=='reconstruct' else 'Cached GLB fixture could not be loaded. Check the worker log; no reconstruction ran.'
                if job['kind']=='reconstruct' and 'cuda_oom' in str(exc).lower():
                    error='CUDA out of memory. Attempt logs are available; retry requires an explicit request.'
                if job['kind']=='texture':
                    from .texture_jobs import TextureFailure
                    error=str(exc) if isinstance(exc,TextureFailure) else 'input: texture attempt failed; inspect worker log'
                c.execute("UPDATE jobs SET status='failed',stage='failed',error=?,progress=0,updated=? WHERE id=?", (error, now(), job['id']))
                if job['photo_id'] and job['kind']=='preprocess':
                    c.execute("UPDATE photos SET status='failed',confirmed=0,error=? WHERE id=?", (error, job['photo_id']))
        return True

    def process_photo(self, job):
        with self.store.transaction() as c:
            photo = c.execute('SELECT * FROM photos WHERE id=? AND session_id=?', (job['photo_id'], job['session_id'])).fetchone()
            if not photo:
                raise ValueError('Photo no longer exists.')
        with Image.open(self.store.path(photo['original'])) as original:
            output, validation = preprocess(original, self.remover)
        relative = f"sessions/{job['session_id']}/photos/{photo['id']}/cutout.png"
        self.store.atomic_bytes(relative, png_bytes(output))
        with self.store.transaction() as c:
            c.execute('UPDATE photos SET cutout=?,validation=?,status=?,confirmed=0,error=? WHERE id=?',
                      (relative, json.dumps(validation), 'ready' if validation['valid'] else 'invalid', '; '.join(validation['errors']) or None, photo['id']))
            c.execute("UPDATE jobs SET status='completed',stage='completed',progress=100,error=NULL,updated=? WHERE id=?", (now(), job['id']))

    def mock_model(self, job):
        payload = json.loads(job['payload'])
        key = payload['fixture']
        source = self.store.config.fixtures.get(key)
        if source is None or not source.is_file():
            raise ValueError('Allowlisted GLB fixture is unavailable.')
        data = source.read_bytes()
        check_glb(data)
        vid = job['id']  # deterministic: crash replay never publishes duplicate versions
        relative = f"sessions/{job['session_id']}/versions/{vid}/model.glb"
        self.store.atomic_bytes(relative, data)
        payload['snapshot']['fixtureSha256'] = hashlib.sha256(data).hexdigest()
        with self.store.transaction() as c:
            c.execute('INSERT OR IGNORE INTO versions(id,session_id,job_id,kind,model,source,snapshot,created) VALUES(?,?,?,?,?,?,?,?)',
                      (vid, job['session_id'], job['id'], 'cached-fixture', relative, f'Existing Hunyuan {key} GLB; unrelated to uploaded photo', json.dumps(payload['snapshot']), now()))
            c.execute('UPDATE sessions SET selected_id=? WHERE id=?', (vid, job['session_id']))
            c.execute("UPDATE jobs SET status='completed',stage='completed',progress=100,error=NULL,updated=? WHERE id=?", (now(), job['id']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--allow-gpu',action='store_true',help='Explicitly permit real jobs; also requires ORBIT_ENABLE_GPU_JOBS=1.')
    parser.add_argument('--job',help='Process only this job ID; requires --once.')
    parser.add_argument('--role',choices=('cpu','gpu'),help='Claim only jobs for this worker role.')
    parser.add_argument('--stop-file',type=Path,help='Drain and exit when this file exists.')
    args = parser.parse_args()
    if args.job and not args.once:parser.error('--job requires --once')
    logging.basicConfig(level=logging.INFO)
    store = Store(Config())
    if args.role=='gpu' and not (args.allow_gpu and store.config.enable_gpu_jobs):
        parser.error('GPU role requires --allow-gpu and ORBIT_ENABLE_GPU_JOBS=1')
    roles=(args.role,) if args.role else (('cpu','gpu') if args.allow_gpu and store.config.enable_gpu_jobs else ('cpu',))
    from .process_tree import contain_children
    contain_children()
    stop=threading.Event()
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    with ExitStack() as locks:
        for role in roles:
            locks.enter_context(worker_lock(store,'worker.lock' if role=='cpu' else 'gpu-worker.lock'))
        if 'gpu' in roles:
            # An older orphaned Hunyuan child may still hold the device.
            while not stop.is_set() and not (args.stop_file and args.stop_file.exists()):
                try:
                    with worker_lock(store,'gpu.lock'):pass
                    break
                except OSError:stop.wait(1)
            else:return
        transport=LocalQueue(store,roles)
        worker=Worker(store,allow_gpu='gpu' in roles,queue=transport)
        worker.recover()
        transport.heartbeat()
        done=threading.Event()
        def pulse():
            while not done.wait(3):transport.heartbeat()
        thread=threading.Thread(target=pulse,daemon=True)
        thread.start()
        delay=.2
        try:
            while not stop.is_set() and not (args.stop_file and args.stop_file.exists()):
                ran=worker.tick(job_id=args.job)
                if args.once:break
                delay=.2 if ran else min(2,delay*1.5)
                if not ran:stop.wait(delay)
        finally:
            done.set()
            thread.join()
            transport.close()


if __name__ == '__main__':
    main()
