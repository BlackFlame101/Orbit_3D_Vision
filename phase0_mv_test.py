import argparse
import json
import time
from pathlib import Path

from PIL import Image

def load_image(path, remove_bg=False):
    img = Image.open(path)
    if remove_bg:
        # For your own JPG photos later
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        from hy3dgen.rembg import BackgroundRemover
        remover = BackgroundRemover()
        img = remover(img)
    else:
        # For official example images or already-cutout PNGs
        img = img.convert("RGBA")
    return img


def run_reconstruction(input_paths, outdir, seed=12345, steps=30, octree=256,
                       chunks=20000, remove_bg=False, on_stage=None):
    """The proven Phase 0 engine; called only in an inference child process by Orbit."""
    import torch
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
    emit = on_stage or (lambda stage: None)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Save config
    config = {
        "input_paths": input_paths,
        "seed": seed,
        "steps": steps,
        "octree": octree,
        "chunks": chunks,
        "remove_bg": remove_bg,
    }
    (outdir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    # Load images
    images = {}
    for key, path in input_paths.items():
        img = load_image(path, remove_bg=remove_bg)
        images[key] = img
        img.save(outdir / f"{key}_input.png")

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    emit("loading_model")
    # Load model
    t0 = time.time()
    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        "tencent/Hunyuan3D-2mv",
        subfolder="hunyuan3d-dit-v2-mv",
        variant="fp16",
        device="cpu",
    )

    # Compatibility workaround for Hunyuan's missing
    # Diffusers-style components attribute.
    pipeline.components = {
        "conditioner": pipeline.conditioner,
        "model": pipeline.model,
        "vae": pipeline.vae,
    }

    # Configure component-level CPU offloading.
    pipeline.enable_model_cpu_offload()

    # Keep inference tensors on CUDA.
    # Do NOT call pipeline.to("cuda"), as that would
    # move all model components onto the GPU.
    pipeline.device = torch.device("cuda:0")

    print("CPU offloading configured")
    print("Execution device:", pipeline.device)
    print("Offload hooks:", len(pipeline._all_hooks))
    load_seconds = time.time() - t0

    emit("generating")
    # Run inference
    t1 = time.time()
    mesh = pipeline(
        image=images,
        num_inference_steps=steps,
        octree_resolution=octree,
        num_chunks=chunks,
        generator=torch.manual_seed(seed),
        output_type="trimesh"
    )[0]
    infer_seconds = time.time() - t1

    emit("saving_glb")
    mesh_path = outdir / "mesh.glb"
    mesh.export(mesh_path)

    metrics = {
        "load_seconds": load_seconds,
        "infer_seconds": infer_seconds,
        "peak_torch_allocated_gb": (
            torch.cuda.max_memory_allocated() / 1e9 if torch.cuda.is_available() else None
        ),
        "peak_torch_reserved_gb": (
            torch.cuda.max_memory_reserved() / 1e9 if torch.cuda.is_available() else None
        ),
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "mesh_vertices": int(len(mesh.vertices)) if hasattr(mesh, "vertices") else None,
        "mesh_faces": int(len(mesh.faces)) if hasattr(mesh, "faces") else None,
        "output_mesh": str(mesh_path),
    }

    (outdir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print("=== DONE ===")
    print(json.dumps(metrics, indent=2))

    emit("runner_completed")
    return mesh_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--front", type=str, default=None)
    ap.add_argument("--left", type=str, default=None)
    ap.add_argument("--back", type=str, default=None)
    ap.add_argument("--right", type=str, default=None)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--octree", type=int, default=256)
    ap.add_argument("--chunks", type=int, default=20000)
    ap.add_argument("--remove-bg", action="store_true")
    ap.add_argument("--outdir", type=str, required=True)
    ap.add_argument("--stage-events", action="store_true")
    args = ap.parse_args()

    input_paths = {
        k: v for k, v in {
            "front": args.front,
            "left": args.left,
            "back": args.back,
            "right": args.right
        }.items() if v is not None
    }

    if not input_paths:
        raise SystemExit("You must provide at least one input view.")

    def stage_event(stage):
        if args.stage_events:
            print("ORBIT_STAGE:" + stage, flush=True)
    return run_reconstruction(input_paths, args.outdir, args.seed, args.steps,
                              args.octree, args.chunks, args.remove_bg, stage_event)


if __name__ == "__main__":
    main()
