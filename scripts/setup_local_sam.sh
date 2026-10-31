#!/usr/bin/env bash
# Install SAM 3D Body for the editor's "Use this PC's GPU" toggle. Run inside the WSL distro:
#   wsl.exe --install Ubuntu-24.04 --name homunculus-sam --location D:\wsl\homunculus-sam --no-launch
#   wsl.exe -d homunculus-sam -u root -- bash scripts/setup_local_sam.sh
# Safe to run again. The checkpoint is gated: request access at
# https://huggingface.co/facebook/sam-3d-body-dinov3 and log in with `hf auth login` first.
set -euo pipefail
SAM_ROOT=/opt/sam

apt-get update -qq
apt-get install -y -qq ffmpeg git build-essential libgl1 libglib2.0-0 curl
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

mkdir -p "$SAM_ROOT/checkpoints/vitdet"
cd "$SAM_ROOT"
[ -d sam-3d-body ] || git clone https://github.com/facebookresearch/sam-3d-body
[ -d .venv ] || uv venv --python 3.11 .venv
# shellcheck disable=SC1091
. .venv/bin/activate
uv pip install torch==2.14.1 torchvision --index-url https://download.pytorch.org/whl/cu130
uv pip install pytorch-lightning pyrender opencv-python-headless yacs scikit-image einops timm dill \
  pandas rich hydra-core hydra-submitit-launcher hydra-colorlog pyrootutils webdataset chump \
  networkx==3.2.1 roma joblib seaborn appdirs cython jsonlines xtcocotools loguru optree fvcore \
  pycocotools huggingface_hub setuptools wheel pip
python -m pip install "git+https://github.com/facebookresearch/detectron2.git@a1ce2f9" --no-build-isolation --no-deps

detector=checkpoints/vitdet/model_final_f05665.pkl
[ -f "$detector" ] || curl -fsSL -o "$detector" \
  https://dl.fbaipublicfiles.com/detectron2/ViTDet/COCO/cascade_mask_rcnn_vitdet_h/f328730692/model_final_f05665.pkl

hf download facebook/sam-3d-body-dinov3 --local-dir checkpoints/sam-3d-body-dinov3
echo "Local SAM 3D Body is installed in $SAM_ROOT"
