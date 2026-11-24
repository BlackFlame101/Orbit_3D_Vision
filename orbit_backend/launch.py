"""Local Windows supervisor. Ctrl+C drains workers before terminating web services."""
import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from .config import Config,PROJECT
from .images import verify_cached_model
from .process_tree import contain_children
from .storage import Store
from .worker import worker_lock


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable-gpu',action='store_true')
    args=parser.parse_args()
    config=Config()
    store=Store(config)
    node=shutil.which('node')
    frontend=PROJECT/'orbit'
    next_cli=frontend/'node_modules/next/dist/bin/next'
    if not node or not next_cli.is_file():raise SystemExit('Install Orbit frontend dependencies before startup.')
    verify_cached_model(Path(os.environ.get('U2NET_HOME',Path.home()/'.u2net'))/'u2net.onnx')
    if args.enable_gpu:
        from .inference import runner_manifest
        runner_manifest()
    for port in (8000,3000):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',port))
    with ExitStack() as check:
        for name in (['worker.lock','gpu-worker.lock'] if args.enable_gpu else ['worker.lock']):
            check.enter_context(worker_lock(store,name))
    contain_children()
    stop=threading.Event()
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    logs=store.root/'logs'/('startup-'+uuid.uuid4().hex[:12])
    logs.mkdir(parents=True)
    drain=logs/'stop'
    env={**os.environ,'ORBIT_ENABLE_GPU_JOBS':str(int(args.enable_gpu)),'ORBIT_DATA_DIR':str(store.root),
         'OMP_NUM_THREADS':os.environ.get('OMP_NUM_THREADS','2'),'PYTHONUNBUFFERED':'1'}
    python=sys.executable
    services={'api':([python,'-m','uvicorn','orbit_backend.api:app_factory','--factory','--host','127.0.0.1','--port','8000'],PROJECT),
              'frontend':([node,str(next_cli),'dev','--webpack','--hostname','127.0.0.1','--port','3000'],frontend)}
    for role in (['cpu','gpu'] if args.enable_gpu else ['cpu']):
        cmd=[python,'-m','orbit_backend.worker','--role',role,'--stop-file',str(drain)]
        if role=='gpu':cmd.append('--allow-gpu')
        services[role]=(cmd,PROJECT)
    children={}
    print(f'Orbit startup logs: {logs}',flush=True)
    try:
        for name,(cmd,cwd) in services.items():
            with (logs/(name+'.log')).open('w') as stream:
                children[name]=subprocess.Popen(cmd,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
            print(f'Started {name} (PID {children[name].pid})',flush=True)
        print('Open http://127.0.0.1:3000 when ready. Press Ctrl+C here to drain and stop Orbit.',flush=True)
        while not stop.wait(.5) and not drain.exists():
            for name,proc in children.items():
                if proc.poll() is not None:raise SystemExit(f'{name} exited ({proc.returncode}). See {logs}')
    finally:
        drain.touch()
        print('Draining active jobs before shutdown.',flush=True)
        for name in ('cpu','gpu'):
            if name in children:children[name].wait()
        for name in ('frontend','api'):
            proc=children.get(name)
            if proc and proc.poll() is None:proc.terminate()
            if proc:proc.wait()


if __name__=='__main__':main()
