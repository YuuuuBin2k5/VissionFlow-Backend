"""Auto Production Retrieval & Source Intelligence Hardening schema.

Revision ID: 0020_retrieval_hardening
Revises: 0019_scene_library
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0020_retrieval_hardening'
down_revision = '0019_scene_library'
branch_labels = None
depends_on = None


def upgrade():
    # 1. source_assets: Add fast_fingerprint for two-tier deduplication
    op.add_column('source_assets', sa.Column('fast_fingerprint', sa.String(128), nullable=True))
    op.create_index('ix_source_assets_fast_fingerprint', 'source_assets', ['fast_fingerprint'])

    # 2. source_scenes: Add visual_fingerprint for perceptual dHash near-duplicate detection
    op.add_column('source_scenes', sa.Column('visual_fingerprint', sa.String(128), nullable=True))
    op.create_index('ix_source_scenes_visual_fingerprint', 'source_scenes', ['visual_fingerprint'])

    # 3. scene_embeddings: Add provider, model, embedding_version & composite isolation index
    op.add_column('scene_embeddings', sa.Column('provider', sa.String(32), nullable=False, server_default='local'))
    op.add_column('scene_embeddings', sa.Column('model', sa.String(64), nullable=False, server_default='hashed-lexical-v1'))
    op.add_column('scene_embeddings', sa.Column('embedding_version', sa.String(32), nullable=False, server_default='v1'))
    op.create_index(
        'ix_scene_embeddings_version_lookup',
        'scene_embeddings',
        ['provider', 'model', 'dimensions', 'embedding_version']
    )

    # 4. Native pgvector column if vector extension is enabled
    conn = op.get_bind()
    try:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.execute(sa.text("ALTER TABLE scene_embeddings ADD COLUMN IF NOT EXISTS embedding_vec vector;"))
    except Exception:
        pass


def downgrade():
    conn = op.get_bind()
    try:
        conn.execute(sa.text("ALTER TABLE scene_embeddings DROP COLUMN IF EXISTS embedding_vec;"))
    except Exception:
        pass

    op.drop_index('ix_scene_embeddings_version_lookup', table_name='scene_embeddings')
    op.drop_column('scene_embeddings', 'embedding_version')
    op.drop_column('scene_embeddings', 'model')
    op.drop_column('scene_embeddings', 'provider')

    op.drop_index('ix_source_scenes_visual_fingerprint', table_name='source_scenes')
    op.drop_column('source_scenes', 'visual_fingerprint')

    op.drop_index('ix_source_assets_fast_fingerprint', table_name='source_assets')
    op.drop_column('source_assets', 'fast_fingerprint')
