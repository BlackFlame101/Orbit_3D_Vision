import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def cached_fixtures():
    # Optional local demo assets are provisioned outside the repository.
    fixtures = {}
    for key in ('perfume', 'mug'):
        value = os.environ.get(f'ORBIT_FIXTURE_{key.upper()}')
        if value and Path(value).is_file():
            fixtures[key] = Path(value).resolve()
    return fixtures


@dataclass
class Config:
    root: Path = field(default_factory=lambda: Path(os.environ.get('ORBIT_DATA_DIR', PROJECT / 'orbit_runtime')).resolve())
    fixtures: dict = field(default_factory=cached_fixtures)
    max_bytes: int = 20 * 1024 * 1024
    max_pixels: int = 40_000_000
    enable_gpu_jobs: bool = field(default_factory=lambda: os.environ.get('ORBIT_ENABLE_GPU_JOBS') == '1')
    allowed_origins: tuple = ('http://127.0.0.1:3000', 'http://localhost:3000', 'http://127.0.0.1:8000', 'http://localhost:8000')

    def __post_init__(self):
        self.root = self.root.resolve()
        protected = [PROJECT / p for p in ('data', 'phase0_outputs', 'phase2_outputs', 'phase3_outputs', 'phase4_outputs', 'web')]
        if self.root == PROJECT or any(self.root == p or self.root.is_relative_to(p) for p in protected):
            raise ValueError('ORBIT_DATA_DIR must be separate from source datasets and research outputs.')
