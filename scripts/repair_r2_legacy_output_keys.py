"""Exact five-object, read-only-by-default repair. Never delete or overwrite."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BUCKET = 'vision-flow'
ENDPOINT = 'https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com'
EVIDENCE = (
    ('run_c15be13f88eb', '1071ef3a-8110-48a8-a34d-686f93c95497', 'c7fd666a069322a5b88021cc375beff6ccc74e8dce4fa45b3f56c75cbe570726', 921256),
    ('run_2023ea9d0492', '1e1cc433-d280-40a7-9ce4-9a60e3983376', '0e75a989084684f82a4a8393127a428e87a94d25b9eea29cd2f8b06eff9c1698', 916047),
    ('run_733981ba83d5', 'df26152b-ffad-41b8-88d2-6db74c650d79', '0a0acb3e651dfafbb2cf900d3afcdaf8600c3e1d660d77cf0f35d50043930e13', 879599),
    ('run_830138b65c01', '390a0128-b2a7-4633-ae5d-eb22b8099666', '8c7dc299deed4240ae4ef780188bc24bcfe11656a7550addd72437ee0cc021cb', 880868),
    ('run_c6bede20d1b4', '2c5e8a7a-c4ca-44b6-bb51-d4b3ef57d24b', 'a70fcbbb821bc8e05c0337c77dc44e00ea7bbe263be247545e7bcd39d3b6dfbd', 917791),
)


def key_for(item):
    return f'visionflow/production/outputs/{item[1]}/{item[2]}.mp4'


def matches(head, item):
    return bool(head and head.get('ContentLength') == item[3]
                and head.get('ContentType') == 'video/mp4'
                and head.get('Metadata', {}).get('sha256') == item[2])


def head_or_missing(client, key):
    try:
        return client.head_object(Bucket=BUCKET, Key=key)
    except Exception as exc:
        if str(getattr(exc, 'response', {}).get('Error', {}).get('Code')) in ('404', 'NoSuchKey', 'NotFound'):
            return None
        raise RuntimeError('OBJECT_HEAD_FAILED') from None


def destination_guard(params, **kwargs):
    # R2 atomic destination condition, not just a racy pre-copy HEAD.
    params['headers']['cf-copy-destination-if-none-match'] = '*'


def verify_bytes(client, key, item):
    response = client.get_object(Bucket=BUCKET, Key=key)
    stream = response['Body']
    digest = hashlib.sha256()
    count = 0
    try:
        for chunk in iter(lambda: stream.read(65536), b''):
            count += len(chunk)
            if count > item[3]:
                raise RuntimeError('DESTINATION_SIZE_MISMATCH')
            digest.update(chunk)
    finally:
        stream.close()
    if count != item[3] or digest.hexdigest() != item[2]:
        raise RuntimeError('DESTINATION_CHECKSUM_MISMATCH')


def repair(client, *, execute=False):
    plans = []
    for item in EVIDENCE:
        key = key_for(item)
        source = head_or_missing(client, BUCKET + '/' + key)
        if not matches(source, item) or not source.get('ETag'):
            raise RuntimeError('SOURCE_NOT_VERIFIED')
        destination = head_or_missing(client, key)
        if destination is not None and not matches(destination, item):
            raise RuntimeError('CANONICAL_DESTINATION_CONFLICT')
        plans.append((item, source, destination))
    # All five preflight before any write. Dedicated client never falls back to unconditional copy.
    if execute:
        client.meta.events.register('before-call.s3.CopyObject', destination_guard)
    results = []
    for item, source, destination in plans:
        key = key_for(item)
        status = 'ALREADY_REPAIRED' if destination is not None else 'COPY_REQUIRED'
        if execute and destination is None:
            try:
                client.copy_object(Bucket=BUCKET, Key=key,
                                   CopySource={'Bucket': BUCKET, 'Key': BUCKET + '/' + key},
                                   CopySourceIfMatch=source['ETag'], MetadataDirective='COPY')
                status = 'COPIED'
            except Exception as exc:
                if str(getattr(exc, 'response', {}).get('Error', {}).get('Code')) not in ('412', 'PreconditionFailed'):
                    raise RuntimeError('CONDITIONAL_COPY_FAILED') from None
                if not matches(head_or_missing(client, key), item):
                    raise RuntimeError('CANONICAL_DESTINATION_CONFLICT') from None
                status = 'ALREADY_REPAIRED'
        if execute or destination is not None:
            if not matches(head_or_missing(client, key), item):
                raise RuntimeError('DESTINATION_VERIFICATION_FAILED')
            verify_bytes(client, key, item)
        if not matches(head_or_missing(client, BUCKET + '/' + key), item):
            raise RuntimeError('LEGACY_SOURCE_VERIFICATION_FAILED')
        results.append(dict(run_id=item[0], source_verified=True, destination_status=status,
                            size=item[3], mime='video/mp4', checksum_verified=execute or destination is not None,
                            legacy_retained=True))
    return results


def verified_db_rows(values):
    import psycopg
    with psycopg.connect(values['DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://'), connect_timeout=15) as db:
        db.read_only = True
        with db.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '10000'")
            cursor.execute('SELECT id, run_id, output_artifact_ref, render_spec_json FROM render_jobs WHERE run_id = ANY(%s)', ([x[0] for x in EVIDENCE],))
            rows = cursor.fetchall()
    if len(rows) != len(EVIDENCE):
        raise RuntimeError('DB_REPAIR_SCOPE_MISMATCH')
    expected = {item[0]: item for item in EVIDENCE}
    for job, run, ref, spec in rows:
        item = expected.pop(run, None)
        if item is None:
            raise RuntimeError('DB_REPAIR_SCOPE_MISMATCH')
        artifact = (spec.get('run_snapshot') or {}).get('render_artifact') or {}
        if (str(job) != item[1] or ref != key_for(item) or artifact.get('storage_ref') != ref
                or artifact.get('checksum_sha256') != item[2] or artifact.get('file_size_bytes') != item[3]):
            raise RuntimeError('DB_SNAPSHOT_MISMATCH')
    return sorted((str(job), run, ref, json.dumps(spec, sort_keys=True)) for job, run, ref, spec in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    from dotenv import dotenv_values
    from worker.services.visionflow_object_storage import VisionFlowObjectStorageSettings, S3CompatibleObjectStorage
    values = {**dotenv_values(ROOT / '.env'), **dotenv_values(ROOT / 'services/control-plane/.env'), **os.environ}
    settings = VisionFlowObjectStorageSettings(
        endpoint=values.get('VISIONFLOW_OBJECT_STORE_ENDPOINT', ''), bucket=values.get('VISIONFLOW_OBJECT_STORE_BUCKET', ''),
        access_key_id=values.get('VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID', ''),
        secret_access_key=values.get('VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY', ''), region=values.get('VISIONFLOW_OBJECT_STORE_REGION') or 'auto')
    if settings.bucket != BUCKET or settings.endpoint != ENDPOINT:
        raise RuntimeError('REPAIR_TARGET_MISMATCH')
    before = verified_db_rows(values)
    results = repair(S3CompatibleObjectStorage(settings)._client, execute=args.execute)
    if before != verified_db_rows(values):
        raise RuntimeError('DB_CHANGED_DURING_REPAIR')
    print(json.dumps(dict(mode='execute' if args.execute else 'dry-run', db_unchanged=True, objects=results)), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never serialize an SDK exception, signed URL, config value or credential.
        safe = str(exc) if type(exc) is RuntimeError and str(exc).replace('_', '').isupper() else type(exc).__name__
        print(json.dumps({'repair_error': safe}), flush=True)
        raise SystemExit(1)
