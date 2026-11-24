"""Local dispatch transport. All ownership changes use Store's BEGIN IMMEDIATE."""
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone

import psutil
from .storage import now

CPU = ('preprocess', 'mock_reconstruct', 'texture')
GPU = ('reconstruct',)
HEAVY = ('reconstruct', 'preprocess', 'texture')
STALE_SECONDS = 20


def online_workers(connection):
    current = datetime.now(timezone.utc)
    return {r['role']: (current-datetime.fromisoformat(r['heartbeat'])).total_seconds()<STALE_SECONDS
            for r in connection.execute('SELECT role,heartbeat FROM worker_roles')}


class LocalQueue:
    def __init__(self, store, roles):
        self.store = store
        self.roles = roles
        self.identity = uuid.uuid4().hex
        self.kinds = tuple(k for role in roles for k in (GPU if role=='gpu' else CPU))
        self.ram = int(os.environ.get('ORBIT_MIN_RAM_MB','2048'))
        self.vram = int(os.environ.get('ORBIT_MIN_VRAM_MB','3072'))
        if min(self.ram,self.vram)<0: raise ValueError('Memory thresholds must be nonnegative')
        self.gpu_sample = (0,None)

    def heartbeat(self):
        with self.store.transaction() as c:
            for role in self.roles:
                c.execute('INSERT OR REPLACE INTO worker_roles VALUES(?,?,?)',(role,self.identity,now()))

    def close(self):
        with self.store.transaction() as c:
            c.execute('DELETE FROM worker_roles WHERE owner=?',(self.identity,))

    def resource_reason(self,kind):
        if kind not in HEAVY:return None
        if psutil.virtual_memory().available < self.ram*1024**2:return 'waiting_ram'
        if kind!='reconstruct' or self.vram==0:return None
        if time.monotonic()>=self.gpu_sample[0]:
            try:
                value=subprocess.check_output(['nvidia-smi','-i','0','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True,timeout=3)
                free=int(value.strip())
            except (OSError,ValueError,subprocess.SubprocessError):
                free=None
            self.gpu_sample=(time.monotonic()+5,free)
        free=self.gpu_sample[1]
        if free is None:return 'waiting_gpu_probe'
        return 'waiting_vram' if free<self.vram else None

    def claim(self,job_id=None):
        # Probe hardware outside the SQLite write lock, and only when work exists.
        marks=','.join('?' for _ in self.kinds)
        query=f"SELECT * FROM jobs WHERE status='queued' AND kind IN ({marks}) AND (? IS NULL OR id=?) ORDER BY created,id"
        args=(*self.kinds,job_id,job_id)
        with self.store.transaction() as c:
            kinds={r['kind'] for r in c.execute(query,args)}
        if not kinds:return None
        reasons={kind:self.resource_reason(kind) for kind in kinds}
        with self.store.transaction() as c:
            heavy=c.execute("SELECT 1 FROM jobs WHERE status='running' AND kind IN ('preprocess','texture','reconstruct') LIMIT 1").fetchone()
            available=online_workers(c)
            waiting=c.execute("""SELECT kind,created,id FROM jobs WHERE status='queued'
                              AND stage='waiting_heavy_job' ORDER BY created,id""").fetchall()
            for r in c.execute(query,args).fetchall():
                if r['kind'] not in reasons:continue
                reason=reasons[r['kind']]
                if not reason and r['kind'] in HEAVY:
                    older=any((w['created'],w['id'])<(r['created'],r['id']) and
                              available.get('gpu' if w['kind']=='reconstruct' else 'cpu')
                              for w in waiting)
                    if heavy or older:reason='waiting_heavy_job'
                if reason:
                    if reason!=r['stage']:c.execute('UPDATE jobs SET stage=? WHERE id=?',(reason,r['id']))
                    continue
                c.execute("UPDATE jobs SET status='running',stage='running',owner=?,attempts=attempts+1,progress=10,error=NULL,updated=? WHERE id=?",(self.identity,now(),r['id']))
                return dict(r)
        return None
