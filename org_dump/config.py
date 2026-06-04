import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_schema: str
    org_id: str
    output_dir: str


def load_config() -> Config:
    missing = []
    required = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "ORG_ID", "OUTPUT_DIR"]
    for key in required:
        if not os.getenv(key):
            missing.append(key)
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return Config(
        db_host=os.environ["DB_HOST"],
        db_port=int(os.getenv("DB_PORT", "5432")),
        db_name=os.environ["DB_NAME"],
        db_user=os.environ["DB_USER"],
        db_password=os.environ["DB_PASSWORD"],
        db_schema=os.getenv("DB_SCHEMA", "public"),
        org_id=os.environ["ORG_ID"],
        output_dir=os.environ["OUTPUT_DIR"],
    )
