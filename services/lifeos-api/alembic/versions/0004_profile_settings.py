"""profile settings

Revision ID: 0004_profile_settings
Revises: 0003_sport_program_engine
Create Date: 2026-05-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004_profile_settings"
down_revision = "0003_sport_program_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "profile_settings" not in tables:
        op.create_table(
            "profile_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("domain", sa.String(length=80), nullable=False),
            sa.Column("settings", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("user_id", "domain", name="uq_profile_settings_user_domain"),
        )


def downgrade() -> None:
    op.drop_table("profile_settings")
