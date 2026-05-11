"""food calorie protein engine

Revision ID: 0005_food_calorie_protein_engine
Revises: 0004_profile_settings
Create Date: 2026-05-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_food_calorie_protein_engine"
down_revision = "0004_profile_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "food_targets" not in tables:
        op.create_table(
            "food_targets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
            sa.Column("calories", sa.Integer(), nullable=False),
            sa.Column("protein_g", sa.Float(), nullable=False),
            sa.Column("carbs_g", sa.Float(), nullable=True),
            sa.Column("fat_g", sa.Float(), nullable=True),
            sa.Column("calorie_floor", sa.Integer(), nullable=False, server_default="1800"),
            sa.Column("source", sa.String(length=80), nullable=False, server_default="calculated"),
            sa.Column("calculation", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "food_logs" not in tables:
        op.create_table(
            "food_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("log_date", sa.Date(), nullable=False),
            sa.Column("meal_type", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=False),
            sa.Column("calories", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("protein_g", sa.Float(), nullable=False, server_default="0"),
            sa.Column("carbs_g", sa.Float(), nullable=True),
            sa.Column("fat_g", sa.Float(), nullable=True),
            sa.Column("confidence", sa.String(length=40), nullable=False, server_default="estimated"),
            sa.Column("telegram_metadata", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "food_log_items" not in tables:
        op.create_table(
            "food_log_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("food_log_id", sa.Integer(), sa.ForeignKey("food_logs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=True),
            sa.Column("unit", sa.String(length=40), nullable=True),
            sa.Column("calories", sa.Integer(), nullable=True),
            sa.Column("protein_g", sa.Float(), nullable=True),
            sa.Column("carbs_g", sa.Float(), nullable=True),
            sa.Column("fat_g", sa.Float(), nullable=True),
            sa.Column("confidence", sa.String(length=40), nullable=False, server_default="estimated"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "food_daily_reviews" not in tables:
        op.create_table(
            "food_daily_reviews",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("review_date", sa.Date(), nullable=False),
            sa.Column("hunger", sa.Integer(), nullable=True),
            sa.Column("energy", sa.Integer(), nullable=True),
            sa.Column("adherence_status", sa.String(length=80), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("recommendations", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("user_id", "review_date", name="uq_food_daily_reviews_user_date"),
        )


def downgrade() -> None:
    op.drop_table("food_daily_reviews")
    op.drop_table("food_log_items")
    op.drop_table("food_logs")
    op.drop_table("food_targets")
