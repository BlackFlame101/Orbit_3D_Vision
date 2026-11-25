"""Approximate object-frame photo alignment using silhouettes, without invented landmarks."""
import numpy as np
from PIL import Image
from scipy.ndimage import binary_closing
from scipy.spatial.transform import Rotation

from .guidance import DIRECTIONS
from .photo_texture import Camera

TEXTURE_DIRECTIONS = {**DIRECTIONS, 'top': (0, 1, 0)}


def surface_samples(vertices, faces):
    triangles = vertices[faces].astype(float)
    areas = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                   triangles[:, 2] - triangles[:, 0]), axis=1)
    if not np.isfinite(areas).all() or areas.sum() <= 0:
        raise ValueError('Mesh has no usable surface')
    rng = np.random.default_rng(12345)
    samples = triangles[rng.choice(len(faces), 40000, p=areas / areas.sum())]
    weights = rng.random((len(samples), 2))
    weights = np.where(weights.sum(1, keepdims=True) > 1, 1 - weights, weights)
    return samples[:, 0] + weights[:, :1] * (samples[:, 1] - samples[:, 0]) + weights[:, 1:] * (samples[:, 2] - samples[:, 0])


def align_photo(points, rgba, role):
    """Fit a bounded nominal camera. Silhouette overlap is not a color-accuracy metric."""
    y, x = np.nonzero(rgba[:, :, 3] >= 128)
    if not len(x):
        raise ValueError('Photo has no visible object')
    lo = np.array([x.min(), y.min()], float)
    hi = np.array([x.max(), y.max()], float)
    extent = hi - lo + 1
    if min(extent) < 8:
        raise ValueError('Object cutout is too small for automatic alignment')
    factor = 104 / max(extent)
    center = (lo + hi) / 2
    origin = 63.5 - factor * center
    target = np.asarray(Image.fromarray(rgba[:, :, 3]).transform(
        (128, 128), Image.Transform.AFFINE,
        (1 / factor, 0, -origin[0] / factor, 0, 1 / factor, -origin[1] / factor),
        resample=Image.Resampling.BILINEAR)) >= 128
    depth = -np.asarray(TEXTURE_DIRECTIONS[role], float)
    # Overhead photos are taken with the object's front toward the top of the frame.
    down = np.array([0., 0., -1.]) if role == 'top' else np.array([0., -1., 0.])
    nominal = np.stack((np.cross(down, depth), down, depth))

    def evaluate(params):
        yaw, pitch, roll, zoom, dx, dy = params
        axes = Rotation.from_euler('yxz', [yaw, pitch, roll], degrees=True).as_matrix() @ nominal
        xy = points @ axes[:2].T
        low, high = xy.min(0), xy.max(0)
        scale = 104 * zoom / max(high - low)
        offset = 63.5 - (low + high) * scale / 2 + [dx, dy]
        pixels = np.rint(xy * scale + offset).astype(int)
        pixels = pixels[((pixels >= 0) & (pixels < 128)).all(1)]
        mask = np.zeros((128, 128), bool)
        mask[pixels[:, 1], pixels[:, 0]] = True
        mask = binary_closing(mask, structure=np.ones((3, 3), bool))
        score = np.count_nonzero(mask & target) / max(1, np.count_nonzero(mask | target))
        return score, axes, scale, offset

    # Prefer the assigned direction; small pose corrections compensate for handheld captures.
    best = [0., 0., 0., 1., 0., 0.]
    score, *_ = evaluate(best)
    for steps in ((15, 12, 8, .08, 4, 4), (7, 5, 4, .04, 2, 2)):
        for index, step in enumerate(steps):
            for sign in (-1, 1):
                candidate = best.copy()
                candidate[index] += sign * step
                value, *_ = evaluate(candidate)
                if value > score + .002:
                    best, score = candidate, value
    score, axes, scale, offset = evaluate(best)
    if score < .65:
        raise ValueError(f'Automatic alignment too weak for {role} ({score:.0%} silhouette overlap). Use manual landmarks or another photo.')
    camera = Camera(rgba, axes, scale / factor, (offset - origin) / factor, None,
                    silhouette_iou=float(score))
    camera.check()
    return camera
