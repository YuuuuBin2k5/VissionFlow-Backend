"""Auto Production Scene Library and Source Intelligence Foundation schema.

Revision ID: 0019_auto_production_scene_library
Revises: 0018_voice_system
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0019_scene_library'
down_revision = '0018_voice_system'
branch_labels = None
depends_on = None



def timestamps():
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    ]


def upgrade():
    # 1. source_assets
    op.create_table(
        'source_assets',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('source_type', sa.String(32), nullable=False, server_default='video'),
        sa.Column('original_uri', sa.Text(), nullable=True),
        sa.Column('storage_ref', sa.Text(), nullable=True),
        sa.Column('fingerprint', sa.String(128), nullable=False),
        sa.Column('duration', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('width', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('height', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fps', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('codec', sa.String(32), nullable=False, server_default='unknown'),
        sa.Column('language', sa.String(16), nullable=True),
        sa.Column('transcript_state', sa.String(32), nullable=False, server_default='PENDING'),
        sa.Column('rights_state', sa.String(32), nullable=False, server_default='UNKNOWN'),
        sa.Column('watermark_state', sa.String(32), nullable=False, server_default='none'),
        sa.Column('ingest_status', sa.String(32), nullable=False, server_default='INGESTED'),
        sa.Column('analysis_version', sa.String(32), nullable=False, server_default='v1'),
        sa.Column('metadata_json', pg.JSONB(), nullable=False, server_default='{}'),
        *timestamps()
    )
    op.create_index('ix_source_assets_fingerprint', 'source_assets', ['fingerprint'])

    # 2. source_scenes
    op.create_table(
        'source_scenes',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('source_id', sa.String(64), sa.ForeignKey('source_assets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('start_sec', sa.Float(), nullable=False),
        sa.Column('end_sec', sa.Float(), nullable=False),
        sa.Column('duration_sec', sa.Float(), nullable=False),
        sa.Column('fingerprint', sa.String(128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('transcript', sa.Text(), nullable=True),
        sa.Column('entities', pg.JSONB(), nullable=False, server_default='[]'),
        sa.Column('actions', pg.JSONB(), nullable=False, server_default='[]'),
        sa.Column('location_context', sa.Text(), nullable=True),
        sa.Column('shot_type', sa.String(64), nullable=True),
        sa.Column('motion_score', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('technical_quality_score', sa.Float(), nullable=False, server_default='0.8'),
        sa.Column('embedding_ref', sa.String(128), nullable=True),
        sa.Column('analysis_version', sa.String(32), nullable=False, server_default='v1'),
        sa.Column('keyframes', pg.JSONB(), nullable=False, server_default='[]'),
        *timestamps()
    )
    op.create_index('ix_source_scenes_source_id', 'source_scenes', ['source_id'])
    op.create_index('ix_source_scenes_fingerprint', 'source_scenes', ['fingerprint'])

    # 3. scene_embeddings
    op.create_table(
        'scene_embeddings',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('scene_id', sa.String(64), sa.ForeignKey('source_scenes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('vector_data', pg.JSONB(), nullable=False, server_default='[]'),
        sa.Column('text_representation', sa.Text(), nullable=False),
        sa.Column('model_name', sa.String(64), nullable=False),
        sa.Column('dimensions', sa.Integer(), nullable=False),
        *timestamps()
    )
    op.create_index('ix_scene_embeddings_scene_id', 'scene_embeddings', ['scene_id'])


def downgrade():
    op.drop_table('scene_embeddings')
    op.drop_table('source_scenes')
    op.drop_table('source_assets')
