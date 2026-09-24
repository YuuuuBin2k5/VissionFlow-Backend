"""Prevent reintroducing embedded provider credentials into runtime config."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name', [
    'modal_worker.py', 'start_render_worker.py', 'worker/config.py', 'worker/config/__init__.py',
    'worker/services/visionflow_object_storage.py',
    'services/control-plane/app/infrastructure/overlay_uploads.py',
    'services/control-plane/app/core/youtube_publisher.py',
])
def test_no_literal_credential_defaults(name):
    tree = ast.parse((ROOT / name).read_text(encoding='utf-8-sig'))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ('get', 'getenv', 'setdefault') and len(node.args) > 1):
            continue
        key, default = node.args[:2]
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            continue
        if not key.value.endswith(('API_KEY', 'ACCESS_KEY_ID', 'SECRET', 'SECRET_ACCESS_KEY', 'PASSWORD', 'REFRESH_TOKEN')):
            continue
        assert not (isinstance(default, ast.Constant) and isinstance(default.value, str) and default.value), name
