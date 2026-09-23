from functools import lru_cache
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from .config import get_settings


@lru_cache
def s3():
    settings = get_settings()
    return boto3.client("s3", endpoint_url=settings.s3_endpoint, aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key, region_name="us-east-1", config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=15, retries={"max_attempts": 2}, s3={"addressing_style": "path"}))


def ensure_bucket():
    bucket = get_settings().s3_bucket
    try:
        s3().head_bucket(Bucket=bucket)
    except ClientError as exc:
        if str(exc.response["Error"]["Code"]) not in {"404", "NoSuchBucket"}:
            raise
        s3().create_bucket(Bucket=bucket)
