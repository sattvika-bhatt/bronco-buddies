import os
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

vlm_name = "Qwen/Qwen2.5-VL-3B-Instruct-AWQ"
vlm_enforce_eager = True
vlm_max_num_seqs = 512
vlm_trust_remote_code = True
vlm_max_model_len = 32768
vlm_enable_chunked_prefill = True
vlm_max_num_batched_tokens = vlm_max_model_len


reranker_name = "answerdotai/answerai-colbert-small-v1"
batch_size = 16

os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"

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
    for repo_id in [vlm_name, reranker_name]:
        snapshot_download(
            repo_id=repo_id,
            local_dir=PRETRAINED_VOL_PATH,
            ignore_patterns=["*.pt", "*.bin"],  # using safetensors
        )


GPU_IMAGE = (
    modal.Image.from_registry(TAG, add_python=PYTHON_VERSION)
    .apt_install("git")
    .pip_install(
        "flashinfer-python>=0.2.5",
        "huggingface-hub[hf-transfer]>=0.30.2",
        "python-dotenv>=1.1.0",
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
)

app = modal.App(f"{APP_NAME}-helpers")

# -----------------------------------------------------------------------------

with GPU_IMAGE.imports():
    import torch
    from huggingface_hub import snapshot_download
    from rerankers import Reranker
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import GuidedDecodingParams
    from pydantic import BaseModel

    if modal.is_local():
        download_models()


@app.function(
    image=GPU_IMAGE,
    cpu=1,
    memory=1024,
    gpu="l40s:1",
    volumes=VOLUME_CONFIG,
    secrets=SECRETS,
    timeout=5 * MINUTES,
)
def get_schedule_text(schedule_img: str) -> tuple[bool, str]:
    # set up model
    vlm = LLM(
        download_dir=PRETRAINED_VOL_PATH,
        model=vlm_name,
        tokenizer=vlm_name,
        enforce_eager=vlm_enforce_eager,
        max_num_seqs=vlm_max_num_seqs,
        tensor_parallel_size=torch.cuda.device_count(),
        trust_remote_code=vlm_trust_remote_code,
        max_model_len=vlm_max_model_len,
        enable_chunked_prefill=vlm_enable_chunked_prefill,
        max_num_batched_tokens=vlm_max_num_batched_tokens,
    )

    temperature = 0.1
    top_p = 0.001
    repetition_penalty = 1.05
    stop_token_ids = []
    max_tokens = 2048

    class Response(BaseModel):
        is_valid_schedule: bool
        schedule_text: str

    sampling_params = SamplingParams(
        temperature=temperature,
        top_p=top_p,
        repetition_penalty=repetition_penalty,
        stop_token_ids=stop_token_ids,
        max_tokens=max_tokens,
        guided_decoding=GuidedDecodingParams(json=Response.model_json_schema()),
    )

    system_prompt = """
        You are an expert at discerning whether images contain valid weekly schedules (e.g., Google Calendar, Workday, etc.).
        When given a valid weekly schedule, you are extremely capable of describing
        the schedule broken down by time periods (morning, early afternoon, late afternoon, evening) and 
        including specific days and times for classes, study sessions, and free time.
    """
    conversation = [
        [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"""
                        Given the image, determine whether it contains a valid weekly schedule.
                        If not, respond with {{
                            "is_valid_schedule": False,
                            "schedule_text": ""
                        }}
                        If it does, respond with {{
                            "is_valid_schedule": True,
                            "schedule_text": <schedule text with format described above>
                        }}
                        """,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": schedule_img
                        },
                    },
                ],
            },
        ]
    ]
    outputs = vlm.chat(conversation, sampling_params, use_tqdm=True)
    result_text = outputs[0].outputs[0].text.strip()
    result = Response.model_validate_json(result_text)
    return result.is_valid_schedule, result.schedule_text


@app.function(
    image=GPU_IMAGE,
    cpu=1,
    memory=1024,
    gpu="l40s:1",
    volumes=VOLUME_CONFIG,
    secrets=SECRETS,
    timeout=2 * MINUTES,
)
def rank_users(target_user_str: str, users_strs: list[str]) -> list[str]:
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
    results = ranker.rank(query=target_user_str, docs=users_strs)
    top_k_idxs = [doc.doc_id for doc in results.top_k(len(users_strs))]
    return [users_strs[top_k_idx] for top_k_idx in top_k_idxs]
