"""Read-only environment audit. Never print credentials or signed URLs."""
import importlib.util
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
names = ('DATABASE_URL', 'TEST_DATABASE_URL', 'VISIONFLOW_OBJECT_STORE_ENDPOINT',
         'VISIONFLOW_OBJECT_STORE_BUCKET', 'VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID',
         'VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY', 'GROQ_API_KEY', 'GEMINI_API_KEYS',
         'GEMINI_API_KEY', 'VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64',
         'ENABLE_DUBBING_URL_IMPORT', 'ENABLE_WEB_DUBBING')
for path in (root.parent / '.env', root / '.env', root / 'services/control-plane/.env', root / 'worker/.env'):
    if path.exists():
        values = dotenv_values(path)
        print(json.dumps({'file': str(path.relative_to(root.parent)), 'configured': {
            name: bool(values.get(name)) for name in names
        }}))
        for name, value in values.items():
            if value:
                os.environ.setdefault(name, value)
for name in ('DATABASE_URL', 'TEST_DATABASE_URL', 'VISIONFLOW_OBJECT_STORE_ENDPOINT'):
    print(json.dumps({'setting': name, 'host': urlsplit(os.getenv(name, '')).hostname}))
for name in ('ffmpeg', 'ffprobe'):
    print(json.dumps({'binary': name, 'path': shutil.which(name)}))
for name in ('boto3', 'edge_tts', 'faster_whisper', 'whisper', 'playwright', 'psycopg'):
    print(json.dumps({'module': name, 'installed': importlib.util.find_spec(name) is not None}))

import boto3
from botocore.config import Config
try:
    s3 = boto3.client('s3', endpoint_url=os.environ['VISIONFLOW_OBJECT_STORE_ENDPOINT'],
                     aws_access_key_id=os.environ['VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID'],
                     aws_secret_access_key=os.environ['VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY'],
                     region_name='auto', config=Config(connect_timeout=8, read_timeout=8, retries={'max_attempts': 0}))
    bucket = os.environ['VISIONFLOW_OBJECT_STORE_BUCKET']
    s3.head_bucket(Bucket=bucket)
    print(json.dumps({'storage': 'AVAILABLE', 'bucket': bucket}))
    try:
        print(json.dumps({'cors': s3.get_bucket_cors(Bucket=bucket).get('CORSRules')}))
    except Exception as exc:
        print(json.dumps({'cors_error': type(exc).__name__, 'code': getattr(exc, 'response', {}).get('Error', {}).get('Code')}))
except Exception as exc:
    print(json.dumps({'storage': 'MISCONFIGURED', 'error_type': type(exc).__name__, 'code': getattr(exc, 'response', {}).get('Error', {}).get('Code')}))

from sqlalchemy import create_engine, text
try:
    db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+psycopg://', 1)
    engine = create_engine(db_url, connect_args={'connect_timeout': 8})
    with engine.connect() as connection:
        print(json.dumps({'configured_database': 'AVAILABLE', 'select_one': connection.scalar(text('SELECT 1'))}))
    engine.dispose()
except Exception as exc:
    print(json.dumps({'configured_database': 'MISCONFIGURED', 'error_type': type(exc).__name__}))
