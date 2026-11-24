# Orbit 3D Vision

Orbit turns object photographs into reviewable cutouts and interactive 3D models. The Studio supports multiview reconstruction with an optional local Hunyuan3D GPU worker, GLB export, and CPU-based photo texture baking.

## Local development

1. Install Python 3.11 and Node.js 22. Create a virtual environment named .venv and install orbit_backend/requirements.txt.
2. Run npm ci inside orbit.
3. Place the verified u2net.onnx in the directory configured by U2NET_HOME, or use the default .u2net directory in your home folder.
4. Run python -m orbit_backend.launch from the repository root. On Windows, start-orbit.ps1 is a shortcut. Open http://127.0.0.1:3000.

GPU reconstruction additionally requires CUDA-enabled PyTorch, compatible upstream Hunyuan3D-2 source at hy3dgen/ in the checkout, its Python dependencies, and the cached Hunyuan3D-2mv model. The source baseline is upstream commit f8db63096c8282cb27354314d896feba5ba6ff8a. Follow the upstream installation and applicable license terms in LICENSE and NOTICE. Start with python -m orbit_backend.launch --enable-gpu after provisioning those dependencies.

## Deployment

The Docker image runs the Next.js frontend, FastAPI and the CPU worker. Persist /data and mount verified u2net.onnx under /models, or set U2NET_HOME to its directory. Publish container port 3000 to host loopback only. The API listens on container loopback.

The Fly template uses one private machine and the orbit_data volume. Set the app name, create the volume in the chosen region, provision /data/models/u2net.onnx privately, and use fly proxy 3000:3000 to access Studio. The image supports cutout preparation and CPU texture jobs for eligible geometry already available to Orbit. New Hunyuan reconstructions require a separately provisioned GPU environment.

Studio currently assumes a trusted single-user environment. Public hosting requires access control and a session/data isolation design.
