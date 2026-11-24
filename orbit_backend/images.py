import io
import hashlib
import os
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from scripts.input_rgb_quality import has_photographic_variation


def decode(data, config):
    if not data or len(data) > config.max_bytes:
        raise ValueError('Choose an image between 1 byte and 20 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValueError('Only JPEG, PNG and WEBP images are supported.')
                if source.width * source.height > config.max_pixels or min(source.size) < 128:
                    raise ValueError('Image dimensions must be at least 128 px and at most 40 megapixels.')
                if getattr(source, 'n_frames', 1) != 1:
                    raise ValueError('Animated images are not supported.')
                source.load()
                return ImageOps.exif_transpose(source).convert('RGBA')
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('Image exceeds the pixel limit.') from exc
    except (OSError, SyntaxError) as exc:
        raise ValueError('Image data is invalid or incomplete.') from exc


def png_bytes(image):
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def validate_cutout(image):
    rgba = np.asarray(image.convert('RGBA'))
    mask = rgba[..., 3] >= 128
    fraction = float(mask.mean())
    errors = []
    if fraction < .01 or fraction > .98:
        errors.append('Empty or extreme foreground mask; retake the photo or review segmentation.')
    if mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any():
        errors.append('The foreground touches an image edge; the object may be clipped.')
    if not has_photographic_variation(image):
        errors.append('Missing foreground RGB detail; a uniform silhouette is not a usable photo cutout.')
    return {'valid': not errors, 'errors': errors, 'foregroundFraction': fraction, 'size': list(image.size),
            'limitations': 'Framing and RGB screening only; this does not establish segmentation quality or viewpoint correctness.'}


def verify_cached_model(model):
    if not model.is_file():
        raise RuntimeError('Cached u2net.onnx is missing. Set U2NET_HOME to its existing folder; automatic downloads are disabled.')
    digest=hashlib.md5()
    with model.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    # Same checksum used by rembg 2.0.65; reject before its download helper runs.
    if digest.hexdigest()!='60024c5c889badc19c04ad937298a77b':
        raise RuntimeError('Cached u2net.onnx failed its checksum; automatic replacement/download is disabled.')


class CPURemover:
    """Reuse the project's remover call path with a CPU-only ONNX session."""
    def __init__(self):
        self.remover = None

    def __call__(self, image):
        if self.remover is None:
            model = Path(os.environ.get('U2NET_HOME', Path.home() / '.u2net')) / 'u2net.onnx'
            verify_cached_model(model)
            from rembg import new_session
            from hy3dgen.rembg import BackgroundRemover
            remover = object.__new__(BackgroundRemover)
            remover.session = new_session('u2net', providers=['CPUExecutionProvider'])
            if remover.session.inner_session.get_providers() != ['CPUExecutionProvider']:
                raise RuntimeError('Refusing preprocessing: the ONNX session is not CPU-only.')
            self.remover = remover
        return self.remover(image)


def preprocess(original, remover):
    # Already-cut-out images retain alpha; opaque uploads go through the real CPU remover.
    original = original.convert('RGBA')
    if original.getchannel('A').getextrema()[0] < 255:
        alpha = original.getchannel('A')
    else:
        result = remover(original.copy()).convert('RGBA')
        if result.size != original.size:
            raise ValueError('Background removal changed image dimensions.')
        alpha = result.getchannel('A')
    output = original.copy()
    output.putalpha(alpha)
    # All RGB pixels, including thin/transparent edges, are preserved exactly.
    if not np.array_equal(np.asarray(output)[..., :3], np.asarray(original)[..., :3]):
        raise ValueError('RGB preservation check failed.')
    return output, validate_cutout(output)
