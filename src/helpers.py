import argparse
import os
import random
from pathlib import Path, PurePosixPath

import modal
import torch
from huggingface_hub import snapshot_download
from rerankers import Reranker
from sentence_transformers import SentenceTransformer
from vllm import LLM, SamplingParams

from db.models import (
    UserCreate,
)
from utils import (
    APP_NAME,
    GRADUATION_YEARS,
    INTERESTS,
    LOGIN_TYPES,
    MAJORS,
    MINORS,
    MINUTES,
    PERSONALITY_TRAITS,
    PYTHON_VERSION,
    SECRETS,
)

os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"

small_llm_name = "Qwen/Qwen3-0.6B"
small_llm_enforce_eager = False
small_llm_max_num_seqs = 512
small_llm_trust_remote_code = True
small_llm_max_model_len = 32768
small_llm_enable_chunked_prefill = True
small_llm_max_num_batched_tokens = small_llm_max_model_len

embed_model_name = "Linq-AI-Research/Linq-Embed-Mistral"

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
    for model in [small_llm_name, embed_model_name, reranker_name]:
        snapshot_download(
            repo_id=model,
            local_dir=PRETRAINED_VOL_PATH,
            ignore_patterns=["*.pt", "*.bin"],  # using safetensors
        )


if modal.is_local():
    download_models()


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


@app.function(
    image=GPU_IMAGE,
    cpu=1,  # cores
    memory=1024,  # MB
    gpu="l40s:1",  # GPU type and number
    volumes=VOLUME_CONFIG,
    secrets=SECRETS,
    timeout=2 * MINUTES,
)
@modal.concurrent(max_inputs=small_llm_max_num_seqs)
def create_users(user_idxs: list[int]) -> list[UserCreate]:
    # random sample for user
    LOGIN_TYPES = [random.choice(LOGIN_TYPES) for _ in user_idxs]
    MAJORS = [random.choice(MAJORS) for _ in user_idxs]
    MINORS = [
        random.choice(MINORS) if random.random() > 0.2 else None for _ in user_idxs
    ]
    GRADUATION_YEARS = [random.choice(GRADUATION_YEARS) for _ in user_idxs]
    INTERESTS = [
        random.sample(INTERESTS, k=random.randint(1, len(INTERESTS) // 2))
        for _ in user_idxs
    ]
    PERSONALITY_TRAITS = [
        random.sample(
            PERSONALITY_TRAITS, k=random.randint(1, len(PERSONALITY_TRAITS) // 2)
        )
        for _ in user_idxs
    ]

    # set up model
    small_llm = LLM(
        download_dir=PRETRAINED_VOL_PATH,
        model=small_llm_name,
        tokenizer=small_llm_name,
        enforce_eager=small_llm_enforce_eager,
        max_num_seqs=small_llm_max_num_seqs,
        tensor_parallel_size=torch.cuda.device_count(),
        trust_remote_code=small_llm_trust_remote_code,
        max_model_len=small_llm_max_model_len,
        enable_chunked_prefill=small_llm_enable_chunked_prefill,
        max_num_batched_tokens=small_llm_max_num_batched_tokens,
    )

    temperature = 0.6
    top_p = 0.95
    top_k = 20
    min_p = 0
    repetition_penalty = 1.05
    stop_token_ids = []
    max_tokens = 8192

    sampling_params = SamplingParams(
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        min_p=min_p,
        repetition_penalty=repetition_penalty,
        stop_token_ids=stop_token_ids,
        max_tokens=max_tokens,
    )

    # generate bios
    bio_system_prompt = """
        You are a student signing up for Bronco Buddies, a platform for finding
        study partners at Santa Clara University.
    """
    conversations = [
        [
            {"role": "system", "content": bio_system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"""
        Here is some information about you:

        Login Type: {LOGIN_TYPES[user_idx]}
        Major: {MAJORS[user_idx]}
        Minor: {MINORS[user_idx]}
        Graduation Year: {GRADUATION_YEARS[user_idx]}
        INTERESTS: {', '.join(INTERESTS[user_idx])}
        Personality Traits: {', '.join(PERSONALITY_TRAITS[user_idx])}

        Write a short bio for yourself.
        """,
                    },
                ],
            },
        ]
        for user_idx in user_idxs
    ]
    outputs = small_llm.chat(conversations, sampling_params, use_tqdm=True)
    bios = [
        output.outputs[0].text.strip().split("</think>")[-1].strip()
        for output in outputs
    ]

    # generate schedules
    schedule_system_prompt = """
        You are a student signing up for Bronco Buddies, a platform for finding
        study partners at Santa Clara University.
    """
    conversations = [
        [
            {"role": "system", "content": schedule_system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"""
        Here is some information about you:

        Login Type: {LOGIN_TYPES[user_idx]}
        Major: {MAJORS[user_idx]}
        Minor: {MINORS[user_idx]}
        Graduation Year: {GRADUATION_YEARS[user_idx]}
        INTERESTS: {', '.join(INTERESTS[user_idx])}
        Personality Traits: {', '.join(PERSONALITY_TRAITS[user_idx])}

        Write a paragraph or two describing your schedule.
        Be as detailed as possible, including times and days of the week.
        """,
                    },
                ],
            },
        ]
        for user_idx in user_idxs
    ]
    outputs = small_llm.chat(conversations, sampling_params, use_tqdm=True)
    schedules = [
        output.outputs[0].text.strip().split("</think>")[-1].strip()
        for output in outputs
    ]

    return [
        UserCreate(
            login_type=LOGIN_TYPES[user_idx],
            major=MAJORS[user_idx],
            minor=MINORS[user_idx],
            graduation_year=GRADUATION_YEARS[user_idx],
            INTERESTS=INTERESTS[user_idx],
            PERSONALITY_TRAITS=PERSONALITY_TRAITS[user_idx],
            schedule=schedules[user_idx],
            bio=bios[user_idx],
        )
        for user_idx in user_idxs
    ]


@app.function(
    image=GPU_IMAGE,
    cpu=1,  # cores
    memory=1024,  # MB
    gpu="l40s:1",
    volumes=VOLUME_CONFIG,
    secrets=SECRETS,
    timeout=2 * MINUTES,
)
def rank_users_embed(
    target_user: UserCreate, users: list[UserCreate], user_idxs: list[int]
) -> dict[int, UserCreate]:
    # embed users
    embed_model = SentenceTransformer(
        embed_model_name,
        cache_folder=PRETRAINED_VOL_PATH,
        model_kwargs={
            "torch_dtype": "bfloat16",
            "attn_implementation": "flash_attention_2",
        },
    )
    prompt = "Given a user, retrieve users that would be good study partners\n"
    target_user_embedding = embed_model.encode(
        [str(target_user)],
        prompt=prompt,
        convert_to_tensor=True,
        show_progress_bar=True,
    )
    user_embeddings = embed_model.encode(
        [str(user) for user in users],
        prompt=prompt,
        convert_to_tensor=True,
        show_progress_bar=True,
    )

    # normalize
    user_embeddings = user_embeddings / user_embeddings.norm(dim=1, keepdim=True)
    target_user_embedding = target_user_embedding / target_user_embedding.norm(
        dim=1, keepdim=True
    )

    # cosine similarity
    scores = (target_user_embedding @ user_embeddings.t()).squeeze(0).tolist()

    # get ranked users
    ranked_users = sorted(
        zip(user_idxs, users, scores), key=lambda x: x[2], reverse=True
    )
    return {user_idx: user for user_idx, user, _ in ranked_users}


@app.function(
    image=GPU_IMAGE,
    cpu=1,
    memory=1024,
    gpu="l40s:1",
    volumes=VOLUME_CONFIG,
    secrets=SECRETS,
    timeout=2 * MINUTES,
)
def rank_users_cross_enc(
    target_user: UserCreate, users: list[UserCreate], user_idxs: list[int]
) -> dict[int, UserCreate]:
    ranker = Reranker(
        reranker_name,
        model_type="colbert",
        verbose=0,
        dtype=torch.bfloat16,
        device="cuda",
        batch_size=batch_size,
        model_kwargs={"cache_dir": PRETRAINED_VOL_PATH},
    )
    results = ranker.rank(query=str(target_user), docs=[str(user) for user in users])
    top_k_idxs = [doc.doc_id for doc in results.top_k(len(users))]
    return {user_idxs[i]: users[i] for i in top_k_idxs}


# -----------------------------------------------------------------------------


@app.function(
    image=GPU_IMAGE,
    cpu=0.125,
    memory=128,
    volumes=VOLUME_CONFIG,
    secrets=SECRETS,
    timeout=60 * MINUTES,
)
def main(num_users: int):
    print(f"Creating {num_users} users...")
    batched_user_idxs = [
        list(range(i, min(i + small_llm_max_num_seqs, num_users)))
        for i in range(0, num_users, small_llm_max_num_seqs)
    ]
    batched_users = (
        [create_users.local(batch) for batch in batched_user_idxs]
        if modal.is_local()
        else list(create_users.map(batched_user_idxs))
    )
    users = [user for batch in batched_users for user in batch]
    user_idxs = list(range(num_users))

    target_user = users[0]
    print(f"Target user: {target_user}")

    print("Recommending users using embeddings...")
    embed_out = (
        rank_users_embed.local(target_user, users, user_idxs)
        if modal.is_local()
        else rank_users_embed.remote(target_user, users, user_idxs)
    )

    print("Recommending users using cross-encoding...")
    cross_enc_out = (
        rank_users_cross_enc.local(target_user, users, user_idxs)
        if modal.is_local()
        else rank_users_cross_enc.remote(target_user, users, user_idxs)
    )

    print("Comparing results...")
    print("Embedding:")
    print(list(embed_out.keys()))
    print("Cross-encoding:")
    print(list(cross_enc_out.keys()))


@app.local_entrypoint()
def main_modal(num_users: int = 10):
    main.remote(num_users)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--num_users", type=int, default=10)
    args = parser.parse_args()
    main.local(args.num_users)
