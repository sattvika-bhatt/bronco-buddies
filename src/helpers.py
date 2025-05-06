from pathlib import Path, PurePosixPath

import modal

from db.models import (
    User,
)
from utils import (
    APP_NAME,
    MINUTES,
    PYTHON_VERSION,
    SECRETS,
)

reranker_name = "answerdotai/answerai-colbert-small-v1"
batch_size = 16

# -----------------------------------------------------------------------------

# Modal
CUDA_VERSION = "12.8.0"
FLAVOR = "devel"
OS = "ubuntu22.04"
TAG = f"nvidia/cuda:{CUDA_VERSION}-{FLAVOR}-{OS}"

PRETRAINED_VOLUME = f"{APP_NAME}-pretrained"
VOLUME_CONFIG: dict[str | PurePosixPath, modal.Volume] = {
    f"/{PRETRAINED_VOLUME}": modal.Volume.from_name(
        PRETRAINED_VOLUME, create_if_missing=True
    ),
}
if modal.is_local():
    PRETRAINED_VOL_PATH = None
else:
    PRETRAINED_VOL_PATH = Path(f"/{PRETRAINED_VOLUME}")


def download_models():
    snapshot_download(
        repo_id=reranker_name,
        local_dir=PRETRAINED_VOL_PATH,
        ignore_patterns=["*.pt", "*.bin"],  # using safetensors
    )


GPU_IMAGE = (
    modal.Image.from_registry(TAG, add_python=PYTHON_VERSION)
    .apt_install("git")
    .pip_install(
        "flashinfer-python>=0.2.5",
        "huggingface-hub[hf-transfer]>=0.30.2",
        "rerankers>=0.9.1.post1",
        "sentence-transformers>=4.1.0",
        "sqlmodel>=0.0.24",
        "ninja>=1.11.1.4",  # required to build flash-attn
        "packaging>=24.2",  # required to build flash-attn
        "wheel>=0.45.1",  # required to build flash-attn
        "vllm>=0.8.5",
    )
    .run_commands("pip install flash-attn==2.7.4.post1 --no-build-isolation")
    .env(
        {
            "TOKENIZERS_PARALLELISM": "false",
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
        }
    )
    .run_function(
        download_models,
        secrets=SECRETS,
        volumes=VOLUME_CONFIG,
    )
    .add_local_python_source("_remote_module_non_scriptable", "db", "utils")
)

app = modal.App(f"{APP_NAME}-helpers")

# -----------------------------------------------------------------------------

with GPU_IMAGE.imports():
    import torch
    from huggingface_hub import snapshot_download
    from rerankers import Reranker

    if modal.is_local():
        download_models()


@app.function(
    image=GPU_IMAGE,
    cpu=1,
    memory=1024,
    gpu="l40s:1",
    volumes=VOLUME_CONFIG,
    secrets=SECRETS,
    timeout=2 * MINUTES,
)
def rank_users_cross_enc(target_user: User, users: list[User]) -> list[User]:
    ranker = Reranker(
        reranker_name,
        model_type="colbert",
        verbose=0,
        dtype=torch.bfloat16,
        device="cuda"
        if torch.cuda.is_available()
        else "mps"
        if torch.backends.mps.is_available()
        else "cpu",
        batch_size=batch_size,
        model_kwargs={"cache_dir": PRETRAINED_VOL_PATH},
    )
    results = ranker.rank(query=str(target_user), docs=[str(user) for user in users])
    top_k_idxs = [doc.doc_id for doc in results.top_k(len(users))]
    return [users[top_k_idx] for top_k_idx in top_k_idxs]
