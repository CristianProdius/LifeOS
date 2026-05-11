"""sport program engine

Revision ID: 0003_sport_program_engine
Revises: 0002_lifeos_v11_core
Create Date: 2026-05-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_sport_program_engine"
down_revision = "0002_lifeos_v11_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sport_goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("start_weight_kg", sa.Float(), nullable=False),
        sa.Column("target_weight_kg", sa.Float(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("stretch_weight_kg", sa.Float()),
        sa.Column("stretch_date", sa.Date()),
        sa.Column("healthy_weekly_loss_min_kg", sa.Float(), nullable=False, server_default="0.45"),
        sa.Column("healthy_weekly_loss_max_kg", sa.Float(), nullable=False, server_default="0.9"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_sport_goals_user_name"),
    )
    op.create_table(
        "training_programs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sport_goal_id", sa.Integer(), sa.ForeignKey("sport_goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("duration_weeks", sa.Integer(), nullable=False),
        sa.Column("current_week_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("default_location_context", sa.String(length=80), nullable=False, server_default="grandparents_home"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "sport_goal_id", "name", name="uq_training_programs_user_goal_name"),
    )
    op.create_table(
        "training_program_weeks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("training_programs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=80), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("target_weight_kg", sa.Float(), nullable=False),
        sa.Column("target_steps_avg", sa.Integer(), nullable=False),
        sa.Column("target_active_minutes", sa.Integer(), nullable=False),
        sa.Column("target_strength_sessions", sa.Integer(), nullable=False),
        sa.Column("target_cardio_sessions", sa.Integer(), nullable=False),
        sa.Column("target_recovery_sessions", sa.Integer(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("program_id", "week_number", name="uq_training_program_weeks_program_week"),
    )
    op.create_table(
        "program_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("training_programs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("adjustment_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("planned_workouts", sa.Column("program_id", sa.Integer(), nullable=True))
    op.add_column("planned_workouts", sa.Column("program_week_id", sa.Integer(), nullable=True))
    op.add_column("planned_workouts", sa.Column("program_day", sa.Integer(), nullable=True))
    op.add_column("planned_workouts", sa.Column("source", sa.String(length=40), nullable=False, server_default="manual"))
    op.add_column("planned_workouts", sa.Column("adaptation_reason", sa.String(length=120), nullable=True))
    op.create_foreign_key(
        "fk_planned_workouts_program_id",
        "planned_workouts",
        "training_programs",
        ["program_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_planned_workouts_program_week_id",
        "planned_workouts",
        "training_program_weeks",
        ["program_week_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_planned_workouts_program_week_id", "planned_workouts", type_="foreignkey")
    op.drop_constraint("fk_planned_workouts_program_id", "planned_workouts", type_="foreignkey")
    op.drop_column("planned_workouts", "adaptation_reason")
    op.drop_column("planned_workouts", "source")
    op.drop_column("planned_workouts", "program_day")
    op.drop_column("planned_workouts", "program_week_id")
    op.drop_column("planned_workouts", "program_id")
    op.drop_table("program_adjustments")
    op.drop_table("training_program_weeks")
    op.drop_table("training_programs")
    op.drop_table("sport_goals")
