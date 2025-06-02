import argparse
import os
import random
from contextlib import contextmanager

import modal

from src.helpers import GPU_IMAGE, PRETRAINED_VOL_PATH, VOLUME_CONFIG
from src.models import (
    Schedule,
    User,
)
from src.utils import (
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

llm_name = "Qwen/Qwen3-0.6B"
llm_enforce_eager = True
llm_max_num_seqs = 8
llm_trust_remote_code = True
llm_max_model_len = 32768
llm_enable_chunked_prefill = True
llm_max_num_batched_tokens = llm_max_model_len

os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"

# -----------------------------------------------------------------------------

# Modal
DB_IMAGE = (
    modal.Image.debian_slim(PYTHON_VERSION)
    .apt_install("git", "libpq-dev")  # add system dependencies
    .pip_install(
        "alembic>=1.15.2",
        "psycopg2>=2.9.10",
        "python-dotenv>=1.1.0",
        "sqlmodel>=0.0.24",
    )  # add Python dependencies
)

app = modal.App(f"{APP_NAME}-user-gen")

# -----------------------------------------------------------------------------

with GPU_IMAGE.imports():
    import torch
    from pydantic import BaseModel
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import GuidedDecodingParams


with DB_IMAGE.imports():
    from sqlmodel import Session as DBSession
    from sqlmodel import create_engine

    engine = create_engine(url=os.getenv("DATABASE_URL"), echo=False)

    @contextmanager
    def get_db_session():
        with DBSession(engine) as session:
            yield session


@app.function(
    image=GPU_IMAGE,
    cpu=1,
    memory=1024,
    gpu="l40s:1",
    volumes=VOLUME_CONFIG,
    secrets=SECRETS,
    timeout=5 * MINUTES,
)
@modal.concurrent(max_inputs=llm_max_num_seqs)
def gen_fake_users(user_idxs: list[int]) -> list[dict]:
    # set up model
    llm = LLM(
        download_dir=PRETRAINED_VOL_PATH,
        model=llm_name,
        tokenizer=llm_name,
        enforce_eager=llm_enforce_eager,
        max_num_seqs=llm_max_num_seqs,
        tensor_parallel_size=torch.cuda.device_count(),
        trust_remote_code=llm_trust_remote_code,
        max_model_len=llm_max_model_len,
        enable_chunked_prefill=llm_enable_chunked_prefill,
        max_num_batched_tokens=llm_max_num_batched_tokens,
    )

    temperature = 0.6
    top_p = 0.95
    repetition_penalty = 1.05
    stop_token_ids = []
    max_tokens = llm_max_model_len // 4

    class _ScheduleGen(BaseModel):
        text: str

    class GenUser(BaseModel):
        login_type: str  # 1 of LOGIN_TYPES
        email: str
        username: str  # email or generated username
        major: str  # 1 of MAJORS
        minor: str | None  # 1 of MINORS or None
        graduation_year: int  # 1 of GRADUATION_YEARS
        interests: list[str]  # 1+ of INTERESTS
        personality_traits: list[str]  # 1+ of PERSONALITY_TRAITS
        schedule: _ScheduleGen
        bio: str  # short bio

    sampling_params = SamplingParams(
        temperature=temperature,
        top_p=top_p,
        repetition_penalty=repetition_penalty,
        stop_token_ids=stop_token_ids,
        max_tokens=max_tokens,
        guided_decoding=GuidedDecodingParams(json=GenUser.model_json_schema()),
    )
    system_prompt = """
        You are an undergraduate student looking for study partners.
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
                            Generate a json object containing the following fields:
                            - login_type: {random.choice(LOGIN_TYPES)}
                            - major: {random.choice(MAJORS)}
                            - minor: {random.choice([None] * len(MINORS) + MINORS)}
                            - graduation_year: {random.choice(GRADUATION_YEARS)}
                            - interests: {random.sample(INTERESTS, random.randint(1, min(3, len(INTERESTS))))}
                            - personality_traits: {random.sample(PERSONALITY_TRAITS, random.randint(1, min(2, len(PERSONALITY_TRAITS))))}
                            - schedule: {{
                                text: realistic weekly schedule broken down by time periods (morning, early afternoon, late afternoon, evening), including specific days and times for classes, study sessions, and free time
                              }}
                            - bio: short bio (anywhere from 10 - 500 words)
                        """,
                    },
                ],
            },
        ]
        for _ in range(len(user_idxs))
    ]
    outputs = llm.chat(conversation, sampling_params, use_tqdm=True)
    user_texts = [
        outputs[i].outputs[0].text.split("</think>")[-1].strip()
        for i in range(len(user_idxs))
    ]
    return [
        GenUser.model_validate_json(user_text).model_dump() for user_text in user_texts
    ]


@app.function(
    image=DB_IMAGE,
    cpu=0.25,
    memory=128,
    secrets=SECRETS,
    timeout=1 * MINUTES,
)
@modal.concurrent(max_inputs=llm_max_num_seqs)
def insert_users(gen_users_data: list[dict]):
    with get_db_session() as session:
        users_to_persist = []
        for user_data_dict in gen_users_data:
            schedule_attributes = user_data_dict.pop("schedule")
            db_schedule = Schedule(**schedule_attributes)
            db_user = User(**user_data_dict, schedule=db_schedule)
            users_to_persist.append(db_user)
        session.add_all(users_to_persist)
        session.commit()


# -----------------------------------------------------------------------------

default_num_users = llm_max_num_seqs


@app.function(
    image=DB_IMAGE,
    cpu=0.125,
    memory=128,
    volumes=VOLUME_CONFIG,
    secrets=SECRETS,
    timeout=10 * MINUTES,
)
def main(num_users: int):
    print(f"Creating {num_users} users...")
    batched_user_idxs = [
        list(range(i, min(i + llm_max_num_seqs, num_users)))
        for i in range(0, num_users, llm_max_num_seqs)
    ]
    batched_gen_users_data = (
        [gen_fake_users.local(batch) for batch in batched_user_idxs]
        if modal.is_local()
        else list(gen_fake_users.map(batched_user_idxs))
    )
    if modal.is_local():
        _ = [insert_users.local(batch_data) for batch_data in batched_gen_users_data]
    else:
        _ = list(insert_users.map(batched_gen_users_data))
    print("Done!")


@app.local_entrypoint()
def main_modal(num_users: int = default_num_users):
    main.remote(num_users)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--num_users", type=int, default=default_num_users)
    args = parser.parse_args()
    main.local(args.num_users)
