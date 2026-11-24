"""One isolated CPU bake attempt. Only the parent worker may publish the result."""
import json
import sys
import traceback
from pathlib import Path
from .texture_jobs import camera,digest,implementation
from .photo_texture import bake


def main(run,inputs):
    stage='input'
    def progress(value):
        nonlocal stage
        stage=value
        print(json.dumps({'stage':value}),flush=True)
    try:
        progress('input')
        manifest=json.loads((run/'manifest.json').read_bytes())
        def checked(sha):
            p=inputs/sha
            if digest(p.read_bytes())!=sha: raise ValueError('Snapshot checksum mismatch')
            return p
        parent=checked(manifest['parentSha256'])
        if implementation()!=manifest['implementation']: raise ValueError('Baker changed')
        cameras=[]
        for spec in manifest['views']:
            checked(spec['originalSha256'])
            data=checked(spec['cutoutSha256']).read_bytes()
            progress('calibration')
            cameras.append(camera(data,spec))
            progress('input')
        metrics=bake(parent,run/'candidate.glb',cameras,manifest['resolution'],progress=progress,uv_cache=inputs.parent/'uv_layouts')
        (run/'metrics.json').write_text(json.dumps(metrics))
        return 0
    except Exception as exc:
        category='memory' if isinstance(exc,MemoryError) else stage
        (run/'failure.json').write_text(json.dumps({'category':category,'detail':str(exc)}))
        traceback.print_exc()
        return 1


if __name__=='__main__': sys.exit(main(*(Path(p) for p in sys.argv[1:])))
