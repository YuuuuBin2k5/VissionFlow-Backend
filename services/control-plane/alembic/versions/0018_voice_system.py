"""Organization-scoped voice configuration and audition artifacts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0018_voice_system'
down_revision = '0017_prompt_template_registry'
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade():
    op.create_table('voice_settings',
        sa.Column('organization_id', pg.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('config', pg.JSONB(), nullable=False, server_default='{}'), *timestamps())
    op.create_table('voice_lab_samples',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('organization_id', pg.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('state', sa.String(20), nullable=False),
        sa.Column('request', pg.JSONB(), nullable=False),
        sa.Column('result', pg.JSONB(), nullable=False), *timestamps())
    op.create_index('ix_voice_lab_samples_organization_id', 'voice_lab_samples', ['organization_id'])


def downgrade():
    op.drop_table('voice_lab_samples')
    op.drop_table('voice_settings')
