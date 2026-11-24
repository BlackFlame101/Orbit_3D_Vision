"""Fit Orbit's orthographic camera in native mesh coordinates and cutout pixels."""
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def fit_camera(landmarks):
    points = np.asarray(landmarks, dtype=float)
    if points.ndim != 2 or points.shape[1] != 5 or not 4 <= len(points) <= 256 or not np.isfinite(points).all():
        raise ValueError('Supply 4 to 256 finite XYZ/u/v correspondences')
    xyz, pixels = points[:, :3], points[:, 3:]
    center, origin = xyz.mean(axis=0), pixels.mean(axis=0)
    local = xyz - center
    target = pixels - origin
    singular = np.linalg.svd(local, compute_uv=False)
    if singular[-1] <= singular[0] * 1e-4 or np.linalg.matrix_rank(target) < 2:
        raise ValueError('Include landmarks at distinct depths and image locations')
    affine = np.linalg.lstsq(local, target, rcond=None)[0].T
    left, scales, right = np.linalg.svd(affine, full_matrices=False)
    rows = left @ right
    axes = np.vstack([rows, np.cross(*rows)])
    def residual(params):
        rotation = Rotation.from_rotvec(params[:3]).as_matrix()
        return (np.exp(params[3]) * local @ rotation[:2].T - target).ravel()
    initial = [*Rotation.from_matrix(axes).as_rotvec(), np.log(scales.mean())]
    fit = least_squares(residual, initial)
    errors = np.linalg.norm(fit.fun.reshape(-1, 2), axis=1)
    if not fit.success or errors.max() > 1.5:
        raise ValueError(f'Landmark reprojection error exceeds tolerance (maximum {errors.max():.2f} pixels)')
    axes = Rotation.from_rotvec(fit.x[:3]).as_matrix()
    scale = np.exp(fit.x[3])
    return dict(axes=axes.tolist(), scale=float(scale), offset=(origin-scale*axes[:2]@center).tolist(),
                landmarks=points.tolist(), rmsPixels=float(np.sqrt(np.mean(errors**2))), maxPixels=float(errors.max()))
