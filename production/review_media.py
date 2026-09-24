"""Browser-safe review media backed by the exact raster used by the renderer."""
import hashlib
import logging
import tempfile
import textwrap
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


def http_media(value):
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    return value if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password else None


def materialize_graphic(candidate, intent, storage=None):
    from PIL import Image, ImageDraw, ImageFont
    from production.artifact_storage import get_artifact_storage
    spec = {'version': 1, 'width': 720, 'height': 1280, 'background': '#10223e',
            'foreground': '#ffffff', 'title': intent.description[:240], 'label': 'VISUAL EXPLANATION'}
    candidate.asset_type = 'GRAPHIC'
    candidate.graphic_spec = spec
    candidate.score_source = None
    candidate.semantic_score = candidate.composite_score = 0
    candidate.media_url = candidate.thumbnail_url = candidate.preview_url = None
    candidate.renderable = False
    try:
        if not spec['title'].strip():
            raise ValueError('GRAPHIC_REQUIRES_SCENE_DESCRIPTION')
        storage = storage or get_artifact_storage()
        image = Image.new('RGB', (spec['width'], spec['height']), spec['background'])
        draw = ImageDraw.Draw(image)
        font_path = next((p for p in (
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            'C:/Windows/Fonts/arial.ttf',
        ) if Path(p).is_file()), None)
        if not font_path:
            raise RuntimeError('UNICODE_GRAPHIC_FONT_UNAVAILABLE')
        font = ImageFont.truetype(font_path, size=32)
        draw.rectangle((40, 160, 680, 168), fill='#38bdf8')
        draw.text((40, 110), spec['label'], font=ImageFont.truetype(font_path, size=20), fill='#38bdf8')
        draw.multiline_text((40, 240), '\n'.join(textwrap.wrap(spec['title'], width=30)), font=font, fill=spec['foreground'], spacing=18)
        with tempfile.TemporaryDirectory(prefix='vf-graphic-') as directory:
            path = Path(directory) / 'preview.png'
            image.save(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            ref = f'visionflow/production/graphics/{digest}.png'
            storage.put_file(ref, path, 'image/png')
            candidate.storage_ref = ref
            candidate.preview_url = candidate.thumbnail_url = candidate.media_url = storage.presigned_download(ref)
            candidate.renderable = True
            candidate.preview_error = None
    except Exception as exc:
        candidate.preview_error = 'GRAPHIC_PREVIEW_UNAVAILABLE'
        logger.warning('Graphic preview failed: %s', type(exc).__name__)
    return candidate


def review_candidate(candidate, storage=None):
    """Never return local file paths, logical IDs or expired saved signatures."""
    result = candidate.model_copy(deep=True)
    if result.provider == 'graphic_fallback':
        result.score_source = None
        result.composite_score = result.semantic_score = 0
    if result.storage_ref:
        try:
            from production.artifact_storage import get_artifact_storage
            storage = storage or get_artifact_storage()
            result.media_url = storage.presigned_download(result.storage_ref)
            if result.asset_type == 'GRAPHIC':
                result.preview_url = result.thumbnail_url = result.media_url
        except Exception as exc:
            result.preview_url = result.thumbnail_url = result.media_url = None
            result.preview_error = 'MEDIA_SIGNING_UNAVAILABLE'
            logger.warning('Review signing failed: %s', type(exc).__name__)
    if result.preview_storage_ref:
        try:
            from production.artifact_storage import get_artifact_storage
            storage = storage or get_artifact_storage()
            result.preview_url = result.thumbnail_url = storage.presigned_download(result.preview_storage_ref)
        except Exception:
            result.preview_url = result.thumbnail_url = None
            result.preview_error = 'PREVIEW_SIGNING_UNAVAILABLE'
    result.media_url = http_media(result.media_url)
    result.thumbnail_url = http_media(result.thumbnail_url)
    result.preview_url = http_media(result.preview_url) or result.thumbnail_url
    result.renderable = bool(result.media_url and result.preview_url and (result.provider != 'graphic_fallback' or result.graphic_spec))
    if not result.preview_url:
        result.preview_error = result.preview_error or 'NO_PREVIEW_RESOURCE'
    return result


def ingest_review_media(candidate, storage=None):
    """Materialize trusted scene-library files once, keeping object references durable."""
    import mimetypes
    from production.artifact_storage import get_artifact_storage
    from production.remote_manifest import sha256_file, validate_storage_ref
    try:
        def resolve(value):
            nonlocal storage
            if not value or http_media(value):
                return value, None
            storage = storage or get_artifact_storage()
            path = Path(value)
            if path.is_file():
                if path.suffix.lower() not in {'.mp4', '.webm', '.mov', '.png', '.jpg', '.jpeg'}:
                    raise ValueError('UNSUPPORTED_REVIEW_MEDIA')
                ref = f'visionflow/production/review/{sha256_file(path)}{path.suffix.lower()}'
                storage.put_file(ref, path, mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            else:
                ref = validate_storage_ref(value)
                storage.metadata(ref)
            return storage.presigned_download(ref), ref
        candidate.media_url, candidate.storage_ref = resolve(candidate.media_url)
        candidate.thumbnail_url, candidate.preview_storage_ref = resolve(candidate.thumbnail_url)
    except Exception as exc:
        candidate.preview_error = 'SOURCE_MEDIA_UNAVAILABLE'
        logger.warning('Scene media unavailable: %s', type(exc).__name__)
    return review_candidate(candidate, storage)


def review_resolution(resolution):
    result = resolution.model_copy(deep=True)
    for shot in result.resolutions:
        if shot.selected_candidate:
            shot.selected_candidate = review_candidate(shot.selected_candidate)
        shot.alternate_candidates = [review_candidate(c) for c in shot.alternate_candidates]
    selected = [s.selected_candidate for s in result.resolutions if s.selected_candidate]
    result.visual_coverage_ratio = sum(c.renderable for c in selected) / max(1, len(result.resolutions))
    scored = [c.composite_score for c in selected if c.score_source]
    result.average_match_score = sum(scored) / len(scored) if scored else 0
    return result
