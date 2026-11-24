"""Best-effort observation only. No Torch import until an authorized child runs."""
import json
import sys
import time
from pathlib import Path


class CudaDiagnostics:
    def __init__(self, outdir, cuda=None):
        self.path=Path(outdir)/'diagnostics.jsonl'
        self.cuda=cuda
        self.stage='starting'
        self.previous=None

    def emit(self, **values):
        record={'time':time.time(),'stage':self.stage,**values}
        # Diagnostics must never turn a successful reconstruction into a failure.
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.path.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(record,sort_keys=True)+'\n')
            print('ORBIT_DIAGNOSTIC:'+json.dumps(record,sort_keys=True),flush=True)
        except Exception:
            pass
        return record

    def checkpoint(self, name):
        self.stage=name
        try:
            if self.cuda is None:
                import torch
                self.cuda=torch.cuda
            cuda=self.cuda
            if not cuda.is_available():return self.emit(event='memory',cudaAvailable=False)
            free,total=cuda.mem_get_info(0)
            return self.emit(event='memory',cudaAvailable=True,gpuName=cuda.get_device_name(0),
                             freeBytes=free,totalBytes=total,allocatedBytes=cuda.memory_allocated(0),
                             reservedBytes=cuda.memory_reserved(0),peakAllocatedBytes=cuda.max_memory_allocated(0),
                             peakReservedBytes=cuda.max_memory_reserved(0))
        except Exception as error:
            return self.emit(event='memory_unavailable',errorType=type(error).__name__)

    def profile(self, frame, event, result):
        # Observe only these existing Python boundaries, without changing model
        # methods, tensors, offload hooks, allocators or inference parameters.
        if frame.f_globals.get('__name__')!='hy3dgen.shapegen.pipelines':return
        name=frame.f_code.co_name
        if name=='encode_cond':
            if event=='call':self.checkpoint('before_conditioning')
            elif event=='return' and result is not None:self.checkpoint('after_conditioning')
        elif name=='_export' and event=='call':self.checkpoint('before_mesh_extraction')

    def __enter__(self):
        self.previous=sys.getprofile()
        # Do not displace an existing profiler. Stage checkpoints still work.
        if self.previous is None:sys.setprofile(self.profile)
        else:self.emit(event='boundary_observer_unavailable',reason='existing profiler')
        self.checkpoint('before_model_loading')
        return self

    def __exit__(self, kind, error, traceback):
        sys.setprofile(self.previous)
        if error is not None:
            stage=self.stage
            # Torch's CUDA OOM is a RuntimeError subclass; messages cover older builds.
            message=str(error).lower()
            oom='outofmemoryerror' in type(error).__name__.lower() or ('cuda' in message and 'out of memory' in message)
            self.checkpoint(stage)
            self.emit(event='failure',classification='cuda_oom' if oom else 'inference_error',
                      failureStage=stage,errorType=type(error).__name__)
        else:self.checkpoint('child_completed')
        return False
