# R2 bucket/key audit — 2026-09-09

## Confirmed conclusion

All five previously reported 404 artifacts exist in bucket `vision-flow`, but under the noncanonical key `vision-flow/visionflow/production/outputs/...`. Their database output references and snapshot references are canonical `visionflow/production/outputs/...`.

This is an object-location/key mismatch, not five missing MP4s. No object was uploaded, copied, deleted or migrated during this audit. No database/configuration/credential values were changed.

## Configuration comparison

Both backend `.env` and control-plane `.env` match the operator-provided production target:

```ini
VISIONFLOW_OBJECT_STORE_BUCKET=vision-flow
VISIONFLOW_OBJECT_STORE_ENDPOINT=https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com
```

No process-level override of these two settings was present in the audit process. This confirms current local configuration matches the supplied Render values, not historical deployment environment values.

## Live read-only evidence

| Run | HEAD canonical key | HEAD bucket-prefixed key | Bytes | MIME | Metadata SHA256 / size vs snapshot |
|---|---:|---:|---:|---|---|
| run_c15be13f88eb | 404 | 200 | 921256 | video/mp4 | both match |
| run_2023ea9d0492 | 404 | 200 | 916047 | video/mp4 | both match |
| run_733981ba83d5 | 404 | 200 | 879599 | video/mp4 | both match |
| run_830138b65c01 | 404 | 200 | 880868 | video/mp4 | both match |
| run_c6bede20d1b4 | 404 | 200 | 917791 | video/mp4 | both match |

LIST on each exact canonical output-job prefix returned zero objects; LIST on each bucket-prefixed output-job prefix returned the corresponding object, without truncation. This audit compared stored checksum metadata, not a fresh full-byte hash of each video.

## Path-by-path audit

| Path | Construction / call | Result |
|---|---|---|
| input upload | remote_render builds `visionflow/production/inputs/{sha}.{ext}`; ArtifactStorage -> upload_file(filename, bucket, key) | bucket and key separate |
| accepted output upload | remote_render builds `visionflow/production/outputs/{job}/{sha}.mp4` | canonical key, no bucket prepend |
| worker upload / presigned PUT | render_workers builds `visionflow/production/attempts/{job}/{attempt}/{sha}.mp4`; signer Params contains separate Bucket and Key; worker sends PUT to authorized URL unchanged | canonical construction |
| download | ArtifactStorage validates ref; S3 adapter download_file(bucket, key, destination) | raw canonical key unchanged; legacy URL input extracts the `visionflow/` portion |
| presigned GET | generate_presigned_download_url uses Params Bucket and Key separately | no prepend |
| Auto Production playback | metadata(ref), then presigned_download(ref) | canonical lookup; old misplaced objects fail lookup |
| Auto Production preview | graphic/review object generators use `visionflow/production/graphics/` and `visionflow/production/review/`; signing uses stored ref unchanged | canonical construction |
| existing artifact diagnostic | DB output_artifact_ref -> ArtifactStorage.metadata -> head_object(Bucket, Key) | correct lookup, object is physically under a different key |
| Composition Studio legacy preview | PrivateObjectPreviewIssuer.resolve_r2_key tries canonical then `vision-flow/{candidate}` | explicit legacy bucket-prefix fallback exists; separate from Auto Production |

Upload/download/PUT argument assertions used an in-process recording client, not live writes. GET/PUT URL generation used the real SDK without issuing PUT. Canonical validator already rejects a ref beginning `vision-flow/`, although its generic allowed namespace is broader than `visionflow/production/`.

## URL path is not the S3 Key

With path-style addressing, this URL path is correct:

```text
/vision-flow/visionflow/production/outputs/...
 ^ bucket   ^ key
```

The S3 Key remains `visionflow/production/outputs/...`.

An endpoint incorrectly including `/vision-flow`, combined with Bucket `vision-flow`, was reproduced OFFLINE to generate:

```text
/vision-flow/vision-flow/visionflow/production/outputs/...
```

R2 then stores `vision-flow/visionflow/production/...` as the key. This exactly explains the observed layout. The shared S3 adapter currently checks only HTTPS and does not reject an endpoint path; thus that misconfiguration remains possible. Current local endpoint has no such suffix.

Repository history independently documents this known legacy issue: `31aa52d` sanitized Composition Studio endpoints, and `d9f2d1d` added legacy-prefix probing. The exact historical environment/writer for these five objects was not independently recovered; the current correct configuration alone does not prove when the bad prefix was introduced.

## Recommended repair, not executed

1. Fail fast on bucket/path/query/fragment embedded in the production R2 API endpoint; retain separate Bucket and canonical Key.
2. Keep DB storage_ref canonical. Do not change it to the bucket-prefixed legacy key.
3. With explicit approval, copy the five verified legacy objects to their canonical keys in the same bucket; verify destination size, MIME and checksum, retaining originals for rollback. Do not overwrite an existing destination.
4. Recheck canonical HEAD, authenticated playback signing, actual browser Range/playback; do not claim human production UX acceptance from this storage repair.
5. Review/remove the separate Composition Studio legacy fallback only after a compatibility/migration decision; do not silently extend it into new production paths.

## Security finding

The legacy Composition Studio issuer contains hardcoded access/secret fallback literals. They were inadvertently included in a raw source-read tool output; they are not repeated in this report. No credentials were changed. Removing those literals and rotating any still-active exposed credentials requires a separate authorized remediation. Generic token-pattern scans from the earlier task did not cover this category of hex-formatted credentials.

Reproduction: `scripts/audit_r2_keys.py` (read-only R2 HEAD/LIST, read-only DB transaction, offline mutating-operation recorder). No deployment or production mutation was performed.
