"""Offline orthographic RGB bake. Pixel coordinates refer to pixel centers, Y down.
Camera rows map object XYZ to image x, image y, and depth increasing away.
Each camera requires independently measured object XYZ / image XY landmarks.
"""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
import trimesh
from .uv_layout import layout
from .texture_validator import read_mesh, require, validate


@dataclass
class Camera:
    rgba: np.ndarray
    axes: np.ndarray
    scale: float
    offset: np.ndarray
    landmarks: np.ndarray  # N x 5: XYZ, pixel XY

    def project(self, points):
        q = points @ self.axes.T
        return q[:,:2]*self.scale+self.offset, q[:,2]

    def check(self):
        require(self.rgba.dtype==np.uint8 and self.rgba.ndim==3 and self.rgba.shape[2]==4, 'Expected uint8 RGBA')
        require(self.axes.shape==(3,3) and np.allclose(self.axes@self.axes.T,np.eye(3),atol=1e-6) and np.isclose(np.linalg.det(self.axes),1), 'Invalid camera axes')
        require(np.isfinite(self.scale) and self.scale>0 and np.shape(self.offset)==(2,), 'Invalid camera scale/offset')
        pts = self.landmarks
        require(pts.ndim==2 and pts.shape[1]==5 and len(pts)>=3 and np.isfinite(pts).all() and np.linalg.matrix_rank(pts[:,3:]-pts[0,3:])==2, 'Need noncollinear landmarks')
        error = np.linalg.norm(self.project(pts[:,:3])[0]-pts[:,3:],axis=1)
        require(error.max()<=1.5,'Camera landmark mismatch')


def raster(triangle, width, height):
    """Return covered integer pixel centers and their barycentric weights."""
    lo = np.maximum(np.ceil(triangle.min(0)).astype(int),0)
    hi = np.minimum(np.floor(triangle.max(0)).astype(int),[width-1,height-1])
    if np.any(lo>hi): return None
    a,b,c = triangle
    basis = np.column_stack((a-c,b-c))
    if abs(np.linalg.det(basis))<1e-10: return None
    yy,xx = np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
    ab = (np.stack((xx,yy),axis=-1)-c) @ np.linalg.inv(basis).T
    weights = np.dstack((ab,1-ab.sum(-1)))
    inside = weights.min(-1)>=-1e-8
    return yy[inside],xx[inside],weights[inside]


def raster_candidates(points, faces, width, height):
    """Skip triangles whose clipped bounding box contains no integer pixel centers."""
    limits = [width-1,height-1]
    for start in range(0,len(faces),8192):
        triangles = points[faces[start:start+8192]]
        lo = np.maximum(np.ceil(triangles.min(axis=1)), 0)
        hi = np.minimum(np.floor(triangles.max(axis=1)), limits)
        yield from start + np.flatnonzero((lo<=hi).all(axis=1))


def bake(source, output, cameras, size=512, *, progress=lambda stage: None, uv_cache=None):
    """Write a new validated GLB; existing output paths are never overwritten."""
    output = Path(output)
    require(not output.exists() and cameras and 64<=size<=2048, 'Need fresh output, calibrated cameras and supported atlas size')
    vertices,faces,*_ = read_mesh(source)
    progress('calibration')
    views = []
    for camera in cameras:
        camera.check()
        xy,z = camera.project(vertices)
        h,w = camera.rgba.shape[:2]
        depth = np.full((h,w),np.inf)
        for index in raster_candidates(xy,faces,w,h):
            face = faces[index]
            hit = raster(xy[face],w,h)
            if hit is not None:
                y,x,b = hit
                depth[y,x] = np.minimum(depth[y,x],b@z[face])
        views.append((camera,depth))

    progress('uv')
    (remap,indices,uv), cache_hit = layout(source,vertices,faces,size,uv_cache)
    require(np.array_equal(vertices[remap][indices],vertices[faces]),'Unwrap changed geometry')
    # UVs below are glTF coordinates (v=0 at the top). Trimesh expects bottom-origin UVs.
    progress('projection')
    pixels = np.full((size,size,3),128,np.uint8)
    occupied = np.zeros((size,size),bool)
    covered = 0
    atlas_xy = uv*size-.5
    for index in raster_candidates(atlas_xy,indices,size,size):
        face,chart = faces[index],indices[index]
        hit = raster(atlas_xy[chart],size,size)
        if hit is None: continue
        y,x,b = hit
        occupied[y,x] = True
        tri = vertices[face].astype(float)
        normal = np.cross(tri[1]-tri[0],tri[2]-tri[0])
        normal /= max(np.linalg.norm(normal),1e-20)
        points = b@tri
        colors = np.zeros((len(y),3))
        weights = np.zeros(len(y))
        for camera,depth in views:
            angle = -normal@camera.axes[2]
            if angle<0.15: continue
            xy,z = camera.project(points)
            ix,iy = np.rint(xy).astype(int).T
            h,w = depth.shape
            valid = np.flatnonzero((ix>=0)&(ix<w)&(iy>=0)&(iy<h))
            # Compare at the pixel center on this triangle's plane.
            slope = -(normal@camera.axes[:2].T)/(normal@camera.axes[2]*camera.scale)
            at_pixel = z + (np.column_stack((ix,iy))-xy)@slope
            sample = camera.rgba[iy[valid],ix[valid]]
            ok = (sample[:,3]==255)&(np.abs(at_pixel[valid]-depth[iy[valid],ix[valid]])<1e-5*max(1,np.ptp(tri)))
            k = valid[ok]
            colors[k] += sample[ok,:3]*angle**4
            weights[k] += angle**4
        seen = weights>0
        pixels[y[seen],x[seen]] = np.rint(colors[seen]/weights[seen,None]).astype(np.uint8)
        covered += seen.sum()
    require(covered>0,'No visible calibrated texture samples')
    dist,nearest = distance_transform_edt(~occupied,return_indices=True)
    gutter = (~occupied)&(dist<=2)
    pixels[gutter] = pixels[nearest[0][gutter],nearest[1][gutter]]
    progress('glb_validation')
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(pixels),metallicFactor=0,roughnessFactor=1)
    mesh = trimesh.Trimesh(vertices=vertices[remap],faces=indices,process=False,
        visual=trimesh.visual.TextureVisuals(uv=uv*[1,-1]+[0,1],material=mat))
    blob = mesh.export(file_type='glb')
    with output.open('xb') as stream:
        try: stream.write(blob)
        except BaseException:
            stream.close();output.unlink();raise
    try: validate(source,output)
    except Exception:
        output.unlink();raise
    return {'uvCacheHit':cache_hit,'triangles':len(faces),'atlas_texels':int(occupied.sum()),'observed_texels':int(covered)}

if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Bake calibrated orthographic RGBA views into a new GLB.')
    parser.add_argument('source', type=Path)
    parser.add_argument('cameras', type=Path, help='JSON list: image (relative PNG), axes, scale, offset, landmarks')
    parser.add_argument('output', type=Path)
    parser.add_argument('--size', type=int, default=512)
    args = parser.parse_args()
    cameras = []
    for spec in json.loads(args.cameras.read_text(encoding='utf8')):
        with Image.open(args.cameras.parent/spec['image']) as im:
            require(im.mode=='RGBA', 'Use an RGBA cutout with an explicit alpha mask')
            cameras.append(Camera(np.array(im),np.array(spec['axes'],float),float(spec['scale']),
                                  np.array(spec['offset'],float),np.array(spec['landmarks'],float)))
    print(bake(args.source,args.output,cameras,args.size))
