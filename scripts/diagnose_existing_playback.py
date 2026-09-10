"""Read-only existing-artifact R2 browser diagnostic. Never creates production runs."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    backend = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend))
    import dotenv
    values = {**dotenv.dotenv_values(backend / '.env'),
              **dotenv.dotenv_values(backend / 'services/control-plane/.env'), **os.environ}
    import psycopg
    url = values.get('DATABASE_URL', '').replace('postgresql+psycopg://', 'postgresql://')
    with psycopg.connect(url, connect_timeout=15) as db:
        db.read_only = True
        with db.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '10000'")
            cursor.execute("SELECT run_id, output_artifact_ref FROM render_jobs WHERE status = 'COMPLETED' AND output_artifact_ref IS NOT NULL ORDER BY completed_at DESC LIMIT 5")
            existing_rows = cursor.fetchall()
    if not existing_rows:
        print(json.dumps({'existing_completed_artifact': False, 'browser_test': 'BLOCKED_NO_ARTIFACT'}))
        return
    for name, value in values.items():
        if name.startswith('VISIONFLOW_OBJECT_STORE_') and value:
            os.environ[name] = value
    from production.artifact_storage import get_artifact_storage
    storage = get_artifact_storage()
    existing = metadata = None
    for row in existing_rows:
        try:
            metadata = storage.metadata(row[1])
            existing = row
            break
        except Exception as exc:
            code = getattr(exc, 'response', {}).get('Error', {}).get('Code')
            print(json.dumps({'existing_run_id': row[0], 'storage_error_code': code}), flush=True)
            if code not in ('404', 'NoSuchKey', 'NotFound'):
                raise
    if not existing:
        print(json.dumps({'browser_test': 'BLOCKED_NO_AVAILABLE_ARTIFACT', 'checked': len(existing_rows)}))
        return
    print(json.dumps({'existing_run_id': existing[0], 'object_bytes': metadata.get('ContentLength'),
        'object_mime': metadata.get('ContentType'), 'production_run_created': False}), flush=True)
    env = {**os.environ, 'VISIONFLOW_DIAGNOSTIC_SIGNED_URL': storage.presigned_download(existing[1])}
    # Do not forward storage/database credentials to the browser diagnostic subprocess.
    for name in list(env):
        if any(part in name for part in ('SECRET', 'API_KEY', 'ACCESS_KEY', 'DATABASE_URL', 'WORKER_TOKEN')):
            env.pop(name, None)
    subprocess.run(['node', str(backend.parent / 'VisionFlow_Client/tests/existing-r2-playback-diagnostic.mjs')],
        env=env, check=True, timeout=90)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'diagnostic_error_type': type(exc).__name__,
            'storage_error_code': getattr(exc, 'response', {}).get('Error', {}).get('Code')}), flush=True)
        raise SystemExit(1)
