"""Content-addressed xatlas layouts shared by CPU texture jobs."""
import hashlib
import json
import os
import tempfile
from importlib.metadata import version
from pathlib import Path
from zipfile import BadZipFile

import numpy as np
import xatlas


def layout(source, vertices, faces, size, directory):
    def generate():
        atlas = xatlas.Atlas()
        atlas.add_mesh(vertices, faces.astype(np.uint32))
        pack = xatlas.PackOptions()
        pack.resolution, pack.padding = size, 4
        atlas.generate(pack_options=pack)
        return atlas[0]

    if directory is None:
        return generate(), False
    spec = dict(mesh=hashlib.sha256(Path(source).read_bytes()).hexdigest(), resolution=size,
                padding=4, xatlas=version('xatlas'), settings='default-chart-and-pack-v1')
    key = hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (key+'.npz')
    try:
        with np.load(path,allow_pickle=False) as stored:
            if stored['key'].item()!=key: raise ValueError('Wrong UV layout identity')
            remap, indices, uv = (stored[n] for n in ('remap','indices','uv'))
            if (remap.ndim!=1 or remap.dtype!=np.uint32 or indices.dtype!=np.uint32 or
                uv.dtype!=np.float32 or indices.shape!=faces.shape or uv.shape!=(len(remap),2) or
                not len(remap) or remap.max()>=len(vertices) or indices.max()>=len(remap) or
                not np.all((uv>=0)&(uv<=1)) or not np.array_equal(vertices[remap][indices],vertices[faces])):
                raise ValueError('Invalid UV layout')
            return (remap,indices,uv), True
    except (FileNotFoundError,ValueError,KeyError,BadZipFile,EOFError):
        pass
    remap, indices, uv = generate()
    if not np.array_equal(vertices[remap][indices],vertices[faces]) or not np.all((uv>=0)&(uv<=1)):
        raise ValueError('Invalid generated UV layout')
    with tempfile.NamedTemporaryFile(dir=directory,suffix='.tmp',delete=False) as f:
        tmp=Path(f.name)
    try:
        with tmp.open('wb') as f:
            np.savez(f,key=key,remap=remap,indices=indices,uv=uv)
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)
    return (remap,indices,uv), False
