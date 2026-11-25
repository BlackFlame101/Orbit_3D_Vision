import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier():
    return uuid.uuid4().hex


def valid_id(value):
    if not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('Invalid identifier.')
    return value


class Store:
    def __init__(self, config):
        self.config = config
        self.root = config.root
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'orbit.sqlite3'
        with self.transaction() as conn:
            conn.executescript('''BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY, created TEXT NOT NULL, budget INTEGER NOT NULL DEFAULT 3,
              settings TEXT NOT NULL, selected_id TEXT);
            CREATE TABLE IF NOT EXISTS photos (
              id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), name TEXT NOT NULL,
              slot TEXT, original TEXT NOT NULL, cutout TEXT, status TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0,
              validation TEXT, error TEXT, created TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS photo_slots ON photos(session_id, slot) WHERE slot IS NOT NULL;
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), photo_id TEXT REFERENCES photos(id),
              kind TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
              error TEXT, attempts INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS active_preprocess ON jobs(photo_id) WHERE kind='preprocess' AND status IN ('queued','running');
            CREATE UNIQUE INDEX IF NOT EXISTS active_mock ON jobs(session_id) WHERE kind='mock_reconstruct' AND status IN ('queued','running');
            CREATE TABLE IF NOT EXISTS versions (
              id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), job_id TEXT UNIQUE NOT NULL REFERENCES jobs(id),
              kind TEXT NOT NULL, model TEXT NOT NULL, source TEXT NOT NULL, snapshot TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_status (id INTEGER PRIMARY KEY CHECK(id=1), heartbeat TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reconstruction_cache (
              fingerprint TEXT PRIMARY KEY, model TEXT NOT NULL, sha256 TEXT NOT NULL,
              manifest TEXT NOT NULL, created TEXT NOT NULL);
            ''')
            conn.execute('''CREATE TABLE IF NOT EXISTS texture_artifacts (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id),session_id TEXT NOT NULL REFERENCES sessions(id),
                parent_id TEXT NOT NULL REFERENCES versions(id),fingerprint TEXT NOT NULL UNIQUE,model TEXT NOT NULL,
                sha256 TEXT NOT NULL,manifest TEXT NOT NULL,metrics TEXT NOT NULL,created TEXT NOT NULL)''')
            # Additive migration: existing B1-B3 sessions and jobs remain readable.
            columns={r['name'] for r in conn.execute('PRAGMA table_info(jobs)')}
            conn.execute('CREATE TABLE IF NOT EXISTS worker_roles(role TEXT PRIMARY KEY,owner TEXT NOT NULL,heartbeat TEXT NOT NULL)')
            if 'owner' not in columns:
                conn.execute('ALTER TABLE jobs ADD COLUMN owner TEXT')
            if 'stage' not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN stage TEXT NOT NULL DEFAULT 'queued'")
                conn.execute("UPDATE jobs SET stage=status WHERE status IN ('completed','failed')")
            if 'fingerprint' not in columns:
                conn.execute('ALTER TABLE jobs ADD COLUMN fingerprint TEXT')
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS texture_identity ON jobs(fingerprint) WHERE kind='texture'")
            columns={r['name'] for r in conn.execute('PRAGMA table_info(photos)')}
            if 'confirmed_sha256' not in columns:
                conn.execute('ALTER TABLE photos ADD COLUMN confirmed_sha256 TEXT')
                conn.execute('UPDATE photos SET confirmed=0')
            columns={r['name'] for r in conn.execute('PRAGMA table_info(worker_status)')}
            if 'gpu_enabled' not in columns:
                conn.execute('ALTER TABLE worker_status ADD COLUMN gpu_enabled INTEGER NOT NULL DEFAULT 0')
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS active_reconstruction ON jobs(session_id) WHERE kind='reconstruct' AND status IN ('queued','running')")

    @contextmanager
    def transaction(self):
        conn = sqlite3.connect(self.db, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=15000')
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def path(self, relative):
        path = (self.root / relative).resolve()
        if path == self.root or not path.is_relative_to(self.root):
            raise ValueError('Invalid storage path.')
        return path

    def atomic_bytes(self, relative, data):
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.' + identifier() + '.tmp')
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def enqueue(self, conn, sid, kind, payload, photo_id=None, fingerprint=None):
        jid = identifier()
        conn.execute('INSERT INTO jobs(id,session_id,photo_id,kind,status,payload,created,updated,fingerprint) VALUES(?,?,?,?,?,?,?,?,?)',
                     (jid, sid, photo_id, kind, 'queued', json.dumps(payload), now(), now(), fingerprint))
        return jid

    def session(self, sid):
        valid_id(sid)
        with self.transaction() as conn:
            session = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
            if not session:
                return None
            photos = [dict(p) for p in conn.execute('SELECT * FROM photos WHERE session_id=? ORDER BY created,id', (sid,))]
            versions = [dict(v) for v in conn.execute('SELECT * FROM versions WHERE session_id=? ORDER BY created,id', (sid,))]
            jobs = [dict(j) for j in conn.execute('SELECT * FROM jobs WHERE session_id=? ORDER BY created,id', (sid,))]
            texture_metrics = {r['job_id']:json.loads(r['metrics']) for r in conn.execute(
                'SELECT job_id,metrics FROM texture_artifacts WHERE session_id=?', (sid,))}
        for p in photos:
            p['url'] = f'/api/orbit/sessions/{sid}/photos/{p["id"]}/original'
            p['cutoutUrl'] = f'/api/orbit/sessions/{sid}/photos/{p["id"]}/cutout' if p['cutout'] else None
            p['confirmed'] = bool(p['confirmed'])
            p['validation'] = json.loads(p['validation']) if p['validation'] else None
            for key in ('original', 'cutout', 'session_id'):
                p.pop(key)
        for index, v in enumerate(versions, 1):
            snap = json.loads(v.pop('snapshot'))
            v.update(snap)
            v['number'] = index
            v['modelUrl'] = f'/api/orbit/sessions/{sid}/versions/{v["id"]}/model.glb'
            v.pop('model')
            v.pop('session_id')
        for job in jobs:
            payload = job.pop('payload')
            if job['kind'] == 'texture':
                manifest = json.loads(payload)
                job.update(parentVersionId=manifest['parent'], resolution=manifest['resolution'],
                           sources=[v['name'] for v in manifest['views']])
                if job['id'] in texture_metrics:
                    job['textureMetrics'] = texture_metrics[job['id']]
            job.pop('session_id')
        active = [j for j in jobs if j['status'] in ('queued', 'running')]
        settings=json.loads(session['settings'])
        settings.setdefault('seed',12345)
        return dict(id=sid, budget=session['budget'], settings=settings, selectedId=session['selected_id'],
                    photos=photos, versions=versions, jobs=jobs, busy=any(j['kind'] in ('mock_reconstruct','reconstruct') for j in active),
                    pending=bool(active), progress=max([j['progress'] for j in active] or [0]))
