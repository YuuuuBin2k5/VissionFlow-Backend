"""Read-only R2 bucket/key audit. Never uploads, deletes, changes config or prints credentials."""
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

EXPECTED_BUCKET = 'vision-flow'
EXPECTED_ENDPOINT = 'https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com'
RUNS = ['run_c15be13f88eb', 'run_2023ea9d0492', 'run_733981ba83d5', 'run_830138b65c01', 'run_c6bede20d1b4']


def emit(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)


def code(exc):
    return getattr(exc, 'response', {}).get('Error', {}).get('Code') or type(exc).__name__


def main():
    backend = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend))
    import dotenv
    layers = [('backend_env', dotenv.dotenv_values(backend / '.env')),
              ('control_plane_env', dotenv.dotenv_values(backend / 'services/control-plane/.env')),
              ('process_env', dict(os.environ))]
    values = {}
    for name, layer in layers:
        values.update(layer)
        emit({'config_layer': name, 'bucket': layer.get('VISIONFLOW_OBJECT_STORE_BUCKET'),
              'endpoint': layer.get('VISIONFLOW_OBJECT_STORE_ENDPOINT')})
    bucket = values.get('VISIONFLOW_OBJECT_STORE_BUCKET', '').strip()
    endpoint = values.get('VISIONFLOW_OBJECT_STORE_ENDPOINT', '').strip()
    emit({'effective_local_bucket': bucket, 'effective_local_endpoint': endpoint,
          'bucket_matches_render': bucket == EXPECTED_BUCKET, 'endpoint_matches_render': endpoint.rstrip('/') == EXPECTED_ENDPOINT})

    from worker.services.visionflow_object_storage import VisionFlowObjectStorageSettings, S3CompatibleObjectStorage
    settings = VisionFlowObjectStorageSettings(endpoint=endpoint, bucket=bucket,
        access_key_id=values['VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID'],
        secret_access_key=values['VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY'], region=values.get('VISIONFLOW_OBJECT_STORE_REGION') or 'auto')
    local = S3CompatibleObjectStorage(settings)
    # Compare with the operator-specified target, retaining the exact same credentials.
    from dataclasses import replace
    target = S3CompatibleObjectStorage(replace(settings, endpoint=EXPECTED_ENDPOINT, bucket=EXPECTED_BUCKET))

    # Capture SDK arguments for mutating operations WITHOUT sending a request.
    class Recorder:
        def upload_file(self, filename, Bucket, Key, **kwargs): emit({'sdk_path': 'upload', 'Bucket': Bucket, 'Key': Key})
        def download_file(self, Bucket, Key, filename): emit({'sdk_path': 'download', 'Bucket': Bucket, 'Key': Key})
        def head_object(self, **kwargs): emit({'sdk_path': 'existing_lookup', **kwargs}); return {}
        def generate_presigned_url(self, operation, Params, **kwargs):
            emit({'sdk_path': operation, 'Bucket': Params['Bucket'], 'Key': Params['Key']})
            return 'https://diagnostic.invalid/not-requested'
    spy = object.__new__(S3CompatibleObjectStorage)
    spy._settings = replace(settings, endpoint=EXPECTED_ENDPOINT, bucket=EXPECTED_BUCKET)
    spy._client = Recorder()
    from production.artifact_storage import ArtifactStorage
    bridge = ArtifactStorage(spy)
    probe = 'visionflow/production/outputs/audit-not-uploaded/probe.mp4'
    bridge.put_file(probe, Path(__file__), 'video/mp4')
    with tempfile.TemporaryDirectory(prefix='vf-key-audit-') as temporary:
        bridge.download_to(probe, Path(temporary) / 'not-downloaded.mp4')
    bridge.metadata(probe)
    bridge.presigned_download(probe)
    bridge.presigned_upload(probe, '0' * 64)
    try:
        bridge.metadata(EXPECTED_BUCKET + '/' + probe)
    except ValueError:
        emit({'bucket_prefixed_storage_ref': 'REJECTED_BY_CANONICAL_VALIDATOR'})
    for label, adapter in [('local', local), ('render_target', target)]:
        for operation in ('GET', 'PUT'):
            signed = adapter.generate_presigned_download_url(probe) if operation == 'GET' else adapter.issue_upload_url(probe, content_type='video/mp4', checksum_sha256='0'*64)
            parsed = urlsplit(signed)
            emit({'signed_path_target': label, 'operation': operation, 'host': parsed.hostname, 'path': parsed.path})
    try:
        replace(settings, endpoint=EXPECTED_ENDPOINT + '/' + EXPECTED_BUCKET)
    except ValueError:
        emit({'historical_bucket_endpoint': 'REJECTED_BEFORE_SDK'})
    else:
        raise RuntimeError('INVALID_ENDPOINT_ACCEPTED')

    import psycopg
    with psycopg.connect(values['DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://'), connect_timeout=15) as db:
        db.read_only = True
        with db.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '10000'")
            cursor.execute('SELECT id, run_id, output_artifact_ref, render_spec_json FROM render_jobs WHERE run_id = ANY(%s) ORDER BY created_at DESC', (RUNS,))
            rows = cursor.fetchall()
    for job_id, run_id, stored, data in rows:
        canonical = stored.removeprefix(EXPECTED_BUCKET + '/')
        snapshot = data.get('run_snapshot') or {}
        artifact = snapshot.get('render_artifact') or {}
        emit({'run_id': run_id, 'job_id': str(job_id), 'stored_ref': stored,
              'snapshot_ref': artifact.get('storage_ref'), 'stored_ref_is_canonical': stored.startswith('visionflow/production/'),
              'run_environment': snapshot.get('run_environment')})
        for variant, key in [('stored', stored), ('canonical', canonical), ('bucket_prefixed', EXPECTED_BUCKET + '/' + canonical)]:
            if variant == 'canonical' and key == stored:
                continue
            try:
                metadata = target.head_object(key)
                emit({'run_id': run_id, 'variant': variant, 'head_status': 200, 'bytes': metadata.get('ContentLength'),
                    'mime_type': metadata.get('ContentType'),
                    'metadata_checksum_matches_snapshot': bool(artifact.get('checksum_sha256')) and metadata.get('Metadata', {}).get('sha256') == artifact.get('checksum_sha256'),
                    'size_matches_snapshot': metadata.get('ContentLength') == artifact.get('file_size_bytes')})
            except Exception as exc:
                emit({'run_id': run_id, 'variant': variant, 'head_error': code(exc)})
        for prefix in [f'visionflow/production/outputs/{job_id}/', f'{EXPECTED_BUCKET}/visionflow/production/outputs/{job_id}/', f'visionflow/production/attempts/{job_id}/']:
            try:
                result = target._client.list_objects_v2(Bucket=EXPECTED_BUCKET, Prefix=prefix, MaxKeys=10)
                emit({'run_id': run_id, 'list_prefix': prefix, 'keys': [item['Key'] for item in result.get('Contents', [])], 'truncated': result.get('IsTruncated', False)})
            except Exception as exc:
                emit({'run_id': run_id, 'list_prefix': prefix, 'list_error': code(exc)})


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        emit({'audit_error': code(exc)})
        raise SystemExit(1)
