import copy
import hashlib
import io
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from scripts import repair_r2_legacy_output_keys as migration
from worker.services.visionflow_object_storage import VisionFlowObjectStorageSettings, validate_object_store_endpoint


@pytest.mark.parametrize('suffix', ['/vision-flow', '/vision-flow/', '/?bucket=vision-flow', '/#fragment', '?', '#'])
def test_reject_bucket_endpoint(suffix):
    with pytest.raises(ValueError, match='OBJECT_STORE_ENDPOINT_INVALID'):
        validate_object_store_endpoint(migration.ENDPOINT + suffix)


def test_missing_credentials_fail():
    with pytest.raises(ValueError, match='OBJECT_STORE_CREDENTIALS_MISSING'):
        VisionFlowObjectStorageSettings(migration.ENDPOINT, migration.BUCKET, '', '', 'auto')


class FakeS3:
    def __init__(self, item, body):
        self.objects = {migration.BUCKET + '/' + migration.key_for(item): dict(
            ContentLength=len(body), ContentType='video/mp4', Metadata={'sha256': item[2]}, ETag='etag', body=body)}
        self.copies = 0
        self.guard = None
        self.meta = SimpleNamespace(events=SimpleNamespace(register=self.register))

    def register(self, event, callback):
        assert event == 'before-call.s3.CopyObject'
        self.guard = callback

    def head_object(self, Bucket, Key):
        assert Bucket == migration.BUCKET
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': '404'}}, 'HeadObject')
        return self.objects[Key]

    def get_object(self, Bucket, Key):
        return {'Body': io.BytesIO(self.head_object(Bucket, Key)['body'])}

    def copy_object(self, **kwargs):
        assert kwargs['Bucket'] == migration.BUCKET
        assert kwargs['Key'].startswith('visionflow/production/outputs/')
        assert kwargs['CopySource']['Bucket'] == migration.BUCKET
        assert kwargs['CopySourceIfMatch'] == 'etag'
        params = {'headers': {}}
        self.guard(params)
        assert params['headers']['cf-copy-destination-if-none-match'] == '*'
        assert kwargs['Key'] not in self.objects
        self.objects[kwargs['Key']] = copy.deepcopy(self.objects[kwargs['CopySource']['Key']])
        self.copies += 1


@pytest.fixture
def store(monkeypatch):
    body = b'test mp4 bytes'
    item = ('run_test', 'job-test', hashlib.sha256(body).hexdigest(), len(body))
    monkeypatch.setattr(migration, 'EVIDENCE', (item,))
    return FakeS3(item, body), item


def test_dry_run_no_write(store):
    client, _ = store
    assert migration.repair(client)[0]['destination_status'] == 'COPY_REQUIRED'
    assert client.copies == 0


def test_copy_idempotent_and_retains_source(store):
    client, _ = store
    assert migration.repair(client, execute=True)[0]['destination_status'] == 'COPIED'
    assert migration.repair(client, execute=True)[0]['destination_status'] == 'ALREADY_REPAIRED'
    assert client.copies == 1
    assert len(client.objects) == 2


def test_conflict_never_overwrites(store):
    client, item = store
    client.objects[migration.key_for(item)] = {'ContentLength': 0}
    with pytest.raises(RuntimeError, match='CANONICAL_DESTINATION_CONFLICT'):
        migration.repair(client, execute=True)
    assert client.copies == 0


def test_source_mismatch_never_copies(store):
    client, item = store
    client.objects[migration.BUCKET + '/' + migration.key_for(item)]['ContentType'] = 'text/plain'
    with pytest.raises(RuntimeError, match='SOURCE_NOT_VERIFIED'):
        migration.repair(client, execute=True)
    assert client.copies == 0


def test_full_byte_checksum_not_just_metadata(store):
    client, item = store
    client.objects[migration.key_for(item)] = copy.deepcopy(next(iter(client.objects.values())))
    client.objects[migration.key_for(item)]['body'] = b'bad'
    with pytest.raises(RuntimeError, match='DESTINATION_CHECKSUM_MISMATCH'):
        migration.repair(client, execute=True)


@pytest.mark.parametrize('identical', [True, False])
def test_destination_created_during_copy_is_never_overwritten(store, identical):
    client, item = store
    def racing_copy(**kwargs):
        client.objects[kwargs['Key']] = copy.deepcopy(next(iter(client.objects.values()))) if identical else {'ContentLength': 0}
        raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'CopyObject')
    client.copy_object = racing_copy
    if identical:
        assert migration.repair(client, execute=True)[0]['destination_status'] == 'ALREADY_REPAIRED'
    else:
        with pytest.raises(RuntimeError, match='CANONICAL_DESTINATION_CONFLICT'):
            migration.repair(client, execute=True)
    assert client.copies == 0


@pytest.mark.parametrize('namespace', ['inputs', 'outputs', 'attempts', 'graphics', 'review'])
def test_all_adapter_paths_keep_bucket_separate(tmp_path, namespace):
    from production.artifact_storage import ArtifactStorage
    from worker.services.visionflow_object_storage import S3CompatibleObjectStorage
    calls = []
    class Recorder:
        def upload_file(self, filename, bucket, key, **kwargs): calls.append((bucket, key))
        def download_file(self, bucket, key, filename): calls.append((bucket, key))
        def head_object(self, **kwargs): calls.append((kwargs['Bucket'], kwargs['Key'])); return {}
        def generate_presigned_url(self, operation, Params, **kwargs):
            calls.append((Params['Bucket'], Params['Key']))
            return 'https://example.invalid/test'
    adapter = object.__new__(S3CompatibleObjectStorage)
    adapter._settings = VisionFlowObjectStorageSettings(migration.ENDPOINT, migration.BUCKET, 'test', 'test', 'auto')
    adapter._client = Recorder()
    storage = ArtifactStorage(adapter)
    key = f'visionflow/production/{namespace}/test.mp4'
    source = tmp_path / 'test.mp4'
    source.write_bytes(b'test')
    storage.put_file(key, source, 'video/mp4')
    storage.download_to(key, tmp_path / 'download.mp4')
    storage.metadata(key)
    storage.presigned_download(key)
    storage.presigned_upload(key, '0' * 64)
    assert calls == [(migration.BUCKET, key)] * 5
    with pytest.raises(ValueError):
        storage.metadata(migration.BUCKET + '/' + key)
    with pytest.raises(ValueError):
        storage.metadata('https://example.invalid/' + key)


def test_environment_credentials_have_no_fallback(monkeypatch):
    monkeypatch.setenv('VISIONFLOW_OBJECT_STORE_ENDPOINT', migration.ENDPOINT)
    monkeypatch.setenv('VISIONFLOW_OBJECT_STORE_BUCKET', migration.BUCKET)
    monkeypatch.delenv('VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID', raising=False)
    monkeypatch.delenv('VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY', raising=False)
    with pytest.raises(ValueError, match='Missing VisionFlow object storage settings'):
        VisionFlowObjectStorageSettings.from_env()
