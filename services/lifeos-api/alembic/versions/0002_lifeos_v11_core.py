"""lifeos v1.1 solid core

Revision ID: 0002_lifeos_v11_core
Revises: 0001_initial_lifeos
Create Date: 2026-05-11
"""

from __future__ import annotations

from alembic import op

from lifeos_api.models import Base


revision = "0002_lifeos_v11_core"
down_revision = "0001_initial_lifeos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    op.drop_table("health_daily_summaries")
    op.drop_table("planned_workouts")
    op.drop_table("life_profiles")
