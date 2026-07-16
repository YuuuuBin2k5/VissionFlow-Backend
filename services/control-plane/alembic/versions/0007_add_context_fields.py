"""Historical no-op migration to repair invalid Alembic state from regression commit b68f90c.

Revision ID: 0007_add_context_fields
Revises: 0006_command_receipts_hardened
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_add_context_fields"
down_revision = "0006_command_receipts_hardened"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op historical regression correction
    pass


def downgrade() -> None:
    # No-op historical regression correction
    pass
