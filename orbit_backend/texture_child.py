"""One isolated CPU bake attempt. Only the parent worker may publish the result."""
import json
import sys
import traceback
import io
from pathlib import Path
import numpy as np
from PIL import Image
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
        alignments=[]
        points=None
        for spec in manifest['views']:
            checked(spec['originalSha256'])
            data=checked(spec['cutoutSha256']).read_bytes()
            progress('calibration')
            if spec.get('mode')=='automatic':
                from .texture_alignment import align_photo, surface_samples
                from .texture_validator import read_mesh
                if points is None:
                    vertices,faces,*_=read_mesh(parent)
                    points=surface_samples(vertices,faces)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format!='PNG' or image.mode!='RGBA':
                        raise ValueError('Expected confirmed RGBA PNG cutout')
                    fitted=align_photo(points,np.array(image),spec['role'])
                cameras.append(fitted)
                alignments.append({'photoId':spec['photo_id'],'role':spec['role'],'mode':'automatic',
                                   'silhouetteIoU':fitted.silhouette_iou,'axes':fitted.axes.tolist(),
                                   'scale':fitted.scale,'offset':fitted.offset.tolist()})
            else:
                cameras.append(camera(data,spec))
                alignments.append({'photoId':spec['photo_id'],'role':spec['role'],'mode':'manual'})
            progress('input')
        metrics=bake(parent,run/'candidate.glb',cameras,manifest['resolution'],progress=progress,uv_cache=inputs.parent/'uv_layouts')
        metrics['alignments']=alignments
        (run/'metrics.json').write_text(json.dumps(metrics))
        return 0
    except Exception as exc:
        category='memory' if isinstance(exc,MemoryError) else stage
        (run/'failure.json').write_text(json.dumps({'category':category,'detail':str(exc)}))
        traceback.print_exc()
        return 1


if __name__=='__main__': sys.exit(main(*(Path(p) for p in sys.argv[1:])))
