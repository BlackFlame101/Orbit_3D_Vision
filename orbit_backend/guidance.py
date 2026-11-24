"""Nominal object-frame coverage estimate for Orbit's supported geometry views."""
from functools import lru_cache
import hashlib
import numpy as np
from .texture_validator import read_mesh

# Hunyuan GLB display frame: Y up. Assumed front at +Z; calibrated poses take precedence.
DIRECTIONS = {'front':(0,0,1), 'left':(-1,0,0), 'right':(1,0,0), 'back':(0,0,-1)}


def coverage(vertices, faces, captured):
    triangles = vertices[faces].astype(float)
    normals = np.cross(triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0])
    areas = np.linalg.norm(normals, axis=1)
    total = float(areas.sum())
    if total <= 0: raise ValueError('Mesh has no measurable surface')
    normals /= np.maximum(areas[:,None], 1e-30)
    centers = triangles.mean(axis=1)
    visible = {}
    for role, vector in DIRECTIONS.items():
        direction = np.array(vector)
        facing = np.maximum(normals @ direction, 0)
        depth = centers @ direction
        plane = centers[:, [0 if direction[2] else 2, 1]]
        extent = np.ptp(plane, axis=0)
        cells = np.floor((plane-plane.min(axis=0))/np.maximum(extent,1e-12)*127).astype(int)
        index = cells[:,0]*128 + cells[:,1]
        nearest = np.full(128*128,-np.inf)
        np.maximum.at(nearest,index,depth)
        visible[role] = facing * (depth >= nearest[index]-np.ptp(depth)*.012)
    observed = np.zeros(len(faces))
    for role in captured:
        if role in visible: observed=np.maximum(observed,visible[role])
    scores = [{'slot':slot,'gain':float(areas@np.maximum(visible[slot]-observed,0)/total)}
              for slot in ('front','left','right') if slot not in captured]
    return dict(observed=float(areas@observed/total),candidates=sorted(scores,key=lambda row:-row['gain']))


@lru_cache(maxsize=32)
def cached_coverage(path, sha, captured):
    with open(path,'rb') as stream:
        if hashlib.sha256(stream.read()).hexdigest()!=sha: raise ValueError('Geometry checksum changed')
    vertices,faces,*_=read_mesh(path)
    return coverage(vertices,faces,captured)
