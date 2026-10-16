import json
import uuid
import os
from io import BytesIO
from minio import Minio
from minio.error import S3Error
from config import Config

_minio_client = None

def get_minio_client():
    global _minio_client
    if _minio_client is None:
        _minio_client = Minio(
            Config.MINIO_ENDPOINT,
            access_key=Config.MINIO_ACCESS_KEY,
            secret_key=Config.MINIO_SECRET_KEY,
            secure=Config.MINIO_SECURE
        )
    return _minio_client

def init_minio_bucket():
    client = get_minio_client()
    bucket = Config.MINIO_BUCKET
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        
        # Security hardening: Allow public download of media objects (avatars/chat),
        # but STRICTLY FORBID s3:ListBucket so anonymous users cannot enumerate or scrape user files.
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [
                        f"arn:aws:s3:::{bucket}/avatars/*",
                        f"arn:aws:s3:::{bucket}/chat/*"
                    ]
                }
            ]
        }
        client.set_bucket_policy(bucket, json.dumps(policy))
        print(f"MinIO bucket '{bucket}' secured with strict object-only read policy.")
    except Exception as e:
        print(f"MinIO initialization warning: {e}")

def upload_file_to_minio(file_data, file_name, content_type, folder="chat"):
    """
    Uploads file to MinIO and returns:
    (object_name, public_url, file_size)
    """
    client = get_minio_client()
    bucket = Config.MINIO_BUCKET
    
    file_ext = os.path.splitext(file_name)[1].lower()
    unique_name = f"{folder}/{uuid.uuid4().hex}{file_ext}"
    
    file_size = len(file_data)
    data_stream = BytesIO(file_data)
    
    client.put_object(
        bucket_name=bucket,
        object_name=unique_name,
        data=data_stream,
        length=file_size,
        content_type=content_type or "application/octet-stream"
    )
    
    url = f"{Config.MINIO_PUBLIC_URL}/{bucket}/{unique_name}"
    return unique_name, url, file_size

def get_file_from_minio(object_name):
    client = get_minio_client()
    bucket = Config.MINIO_BUCKET
    return client.get_object(bucket, object_name)
