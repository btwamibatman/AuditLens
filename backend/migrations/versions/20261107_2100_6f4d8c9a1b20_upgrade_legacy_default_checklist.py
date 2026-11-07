"""Upgrade only the untouched, active starter checklist from the old CQA draft.

Existing evaluation snapshots and user-edited checklists are left as they are.
"""

import hashlib
import json

import sqlalchemy as sa
from alembic import op

from app.features.checklists.defaults import default_checklist_config

revision = "6f4d8c9a1b20"
down_revision = "553578697693"
branch_labels = None
depends_on = None

# Canonical JSON of the original starter config from commit 232f211, after
# ChecklistConfig serialization. A changed criterion or rule must not match.
LEGACY_DEFAULT_SHA256 = "a65cc5d37654a43bca35f31454f3c5296c85d6346192e06f702ee3b6b99b3700"


def upgrade() -> None:
    checklists = sa.table(
        "checklists",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("version", sa.Integer),
        sa.column("is_active", sa.Boolean),
        sa.column("config", sa.JSON),
        sa.column("updated_at", sa.DateTime),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(checklists).where(
            checklists.c.name == "AuditLens · Базовый чек-лист поддержки",
            checklists.c.description == "Стартовая конфигурация из 8 критериев",
            checklists.c.version == 1,
            checklists.c.is_active.is_(True),
        )
    )
    for row in rows:
        encoded = json.dumps(
            row.config, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != LEGACY_DEFAULT_SHA256:
            continue
        connection.execute(
            sa.update(checklists)
            .where(checklists.c.id == row.id)
            .values(
                config=default_checklist_config().model_dump(mode="json"),
                version=row.version + 1,
                updated_at=sa.func.now(),
            )
        )


def downgrade() -> None:
    # The new checklist may have been edited since upgrade. Do not overwrite it.
    pass
