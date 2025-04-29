import os
import random
from pathlib import Path

import modal
from dotenv import load_dotenv

# seed
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

# paths
PARENT_PATH = Path(__file__).parent.parent
DB_SRC_PATH = PARENT_PATH / "db"
SRC_PATH = PARENT_PATH / "src"

# Modal
APP_NAME = "bronco-buddies"
IN_PROD = os.getenv("MODAL_ENVIRONMENT", "dev") == "main"
load_dotenv(".env.local")
SECRETS = [
    modal.Secret.from_dotenv(
        path=PARENT_PATH,
        filename=".env" if IN_PROD else ".env.dev",
    )
]

MINUTES = 60  # seconds
PYTHON_VERSION = "3.12"
