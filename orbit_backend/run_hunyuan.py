"""Explicitly gated child entry point, reusing phase0_mv_test.run_reconstruction."""
import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

from .inference import file_digest, runner_manifest, MODEL
from .multiview import verified_paths, compatible_runner
from .worker import worker_lock
from .diagnostics import CudaDiagnostics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--front',required=True,type=Path)
    parser.add_argument('--left',type=Path)
    parser.add_argument('--back',type=Path)
    parser.add_argument('--right',type=Path)
    parser.add_argument('--outdir',required=True,type=Path)
    parser.add_argument('--identity',required=True,type=Path)
    parser.add_argument('--input-sha256',required=True)
    parser.add_argument('--gpu-lock',required=True,type=Path)
    for name,default in [('seed',12345),('steps',30),('octree',256),('chunks',20000)]:
        parser.add_argument('--'+name,type=int,default=default)
    args=parser.parse_args()
    if not args.execute or os.environ.get('ORBIT_ENABLE_GPU_JOBS')!='1':
        raise SystemExit('Real inference is disabled. Explicit approval and worker/API enablement are required.')
    identity=json.loads(args.identity.read_text(encoding='utf-8'))
    if identity['inputSha256']!=args.input_sha256:
        raise SystemExit('Immutable input checksum mismatch.')
    paths=verified_paths(identity,{r:p for r,p in [('front',args.front),('left',args.left),('back',args.back),('right',args.right)] if p is not None})
    c=identity['config']
    current_runner=runner_manifest()
    if c!={**MODEL,'seed':c['seed']} or (args.seed,args.steps,args.octree,args.chunks)!=(c['seed'],30,256,20000) or not compatible_runner(identity['runner'],current_runner,legacy='schema' not in identity):
        raise SystemExit('Runner/configuration changed after enqueue; resubmit the job.')
    # The child owns this separate lock while CUDA is alive. If its parent dies,
    # a replacement worker cannot run another child concurrently.
    with worker_lock(SimpleNamespace(root=args.gpu_lock.parent),lock_name=args.gpu_lock.name), CudaDiagnostics(args.outdir) as diagnostics:
        from phase0_mv_test import run_reconstruction
        def stage(value):
            if not value.startswith("sampling:"):
                diagnostics.checkpoint(value)
            print('\nORBIT_STAGE:'+value,flush=True)
        mesh=run_reconstruction({role:str(path) for role,path in paths.items()},args.outdir,args.seed,args.steps,args.octree,args.chunks,False,stage)
        receipt={'identity':identity,'meshSha256':file_digest(mesh),'executedRunner':current_runner}
        temporary=args.outdir/'success.tmp'
        temporary.write_text(json.dumps(receipt,sort_keys=True),encoding='utf-8')
        temporary.replace(args.outdir/'success.json')


if __name__=='__main__':
    main()
