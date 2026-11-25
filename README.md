# Orbit 3D Vision

Orbit turns object photographs into reviewable cutouts and interactive 3D models. The Studio supports multiview reconstruction with an optional local Hunyuan3D GPU worker, GLB export, and CPU-based photo texture baking.

## Local setup on Windows

Install Git, Python 3.11 (64-bit), and Node.js 22. Full reconstruction also requires a compatible NVIDIA GPU and current CUDA-capable display driver. Run the following in PowerShell.

### 1. Clone and install the application

```powershell
git clone https://github.com/BlackFlame101/Orbit_3D_Vision.git
cd Orbit_3D_Vision
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r orbit_backend\requirements.txt
npm.cmd --prefix orbit ci
```

### 2. Download the CPU background-removal model

```powershell
$env:U2NET_HOME = Join-Path $env:USERPROFILE '.u2net'
New-Item -ItemType Directory -Force $env:U2NET_HOME | Out-Null
Invoke-WebRequest -Uri 'https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx' -OutFile (Join-Path $env:U2NET_HOME 'u2net.onnx')
```

Start the CPU-only application to verify photo processing:

```powershell
.\.venv\Scripts\python.exe -m orbit_backend.launch
```

Open http://127.0.0.1:3000, upload a photo, and confirm its cutout. Press Ctrl+C in the launcher to stop the application before continuing.

### 3. Install GPU reconstruction dependencies

The following CUDA 12.8 PyTorch build requires a compatible NVIDIA driver. Check that CUDA is available before proceeding.

```powershell
nvidia-smi
.\.venv\Scripts\python.exe -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"
```

The last command should print `True`. Fetch the pinned upstream Hunyuan3D-2 source beside Orbit and copy the model implementation into this repository. Follow the applicable upstream license terms in LICENSE and NOTICE.

```powershell
git clone https://github.com/Tencent/Hunyuan3D-2.git ..\Hunyuan3D-2-upstream
git -C ..\Hunyuan3D-2-upstream checkout f8db63096c8282cb27354314d896feba5ba6ff8a
Copy-Item -Recurse ..\Hunyuan3D-2-upstream\hy3dgen .\hy3dgen
.\.venv\Scripts\python.exe -m pip install diffusers==0.39.0 transformers==4.57.6 accelerate==1.15.0 safetensors==0.8.0 huggingface_hub==0.36.2 einops==0.8.2 omegaconf opencv-python scikit-image pymeshlab pygltflib
.\.venv\Scripts\python.exe -m pip check
```

### 4. Download the multiview model weights

```powershell
$env:HY3DGEN_MODELS = Join-Path $env:USERPROFILE '.cache\hy3dgen'
$hunyuanModelDir = Join-Path $env:HY3DGEN_MODELS 'tencent\Hunyuan3D-2mv'
.\.venv\Scripts\hf.exe download tencent/Hunyuan3D-2mv hunyuan3d-dit-v2-mv/config.yaml hunyuan3d-dit-v2-mv/model.fp16.safetensors --local-dir "$hunyuanModelDir"
```

These weights are downloaded once. Orbit checks existing model files before startup and runs reconstruction offline.

### 5. Start Orbit with both workers

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe -m orbit_backend.launch --enable-gpu
```

Open http://127.0.0.1:3000. Start with one front photo in Front only mode, confirm its cutout, then generate a model. The launcher starts the API, frontend, CPU worker and GPU worker together. Press Ctrl+C to drain active jobs and stop the application. Subsequent launches only need this command; the downloads remain cached in the default directories.

Use **Open GLB** to preview a compatible existing model directly in the browser. Geometry generation uses one seed, 30 diffusion steps and octree resolution 256. The seed selects a reproducible variation. Higher step and octree settings are currently restricted by the reconstruction backend.

Model weights, upstream source, personal photographs, generated assets and local runtime data are excluded from the repository.

Geometry generation supports front only or front with any combination of left, opposite (back), and right views. Set the capture budget to four and confirm all four cutouts to generate from four photos. A budget of five adds an optional overhead photo for texture projection. Photograph the object from above with its front toward the top of the image, then confirm that cutout. You can add it to an existing reconstruction session and rebake without generating geometry again.

## Photo textures

After generating a model, open Texture model, choose an atlas resolution and select the confirmed photographs to project. Automatic photo projection fits a bounded orthographic camera for each assigned direction against the cutout silhouette. The CPU worker unwraps the original mesh, projects visible photo colors into an embedded PNG atlas and publishes a separate textured GLB. The first unwrap may take several minutes; subsequent bakes at the same resolution reuse the UV layout. The original geometry remains available.

Automatic alignment is approximate. Weak silhouette matches are rejected, small sampling gaps are repaired within individual UV charts, and unseen areas remain neutral gray. The texture job reports silhouette overlap for each automatic view, the fraction of occupied atlas texels with direct photo samples, and the number of repaired texels separately. Neither alignment nor coverage measures independent color accuracy. Manual calibration is also available for independently identified mesh/image landmark pairs; it retains the strict reprojection tolerance. Use View texture and Download textured GLB when the job completes.

## Deployment

The Docker image runs the Next.js frontend, FastAPI and the CPU worker. Persist /data and mount verified u2net.onnx under /models, or set U2NET_HOME to its directory. Publish container port 3000 to host loopback only. The API listens on container loopback.

The Fly template uses one private machine and the orbit_data volume. Set the app name, create the volume in the chosen region, provision /data/models/u2net.onnx privately, and use fly proxy 3000:3000 to access Studio. The image supports cutout preparation and CPU texture jobs for eligible geometry already available to Orbit. New Hunyuan reconstructions require a separately provisioned GPU environment.

Studio currently assumes a trusted single-user environment. Public hosting requires access control and a session/data isolation design.
