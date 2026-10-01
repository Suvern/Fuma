"""Share immutable source cache across App-specific Debug entries.

Keep the first ready entry's storage filename so already-issued grants remain valid.
Old duplicate files are explicitly tracked/budgeted until safe cleanup reclaims them.
"""

from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "0005_shared_source_cache"
down_revision = "0004_distribution"
branch_labels = None
depends_on = None

CACHE_FIELDS = (
    "cache_state",
    "downloaded_bytes",
    "sha256",
    "cache_error_code",
    "cache_updated_at",
    "last_access_at",
)


def upgrade():
    cache = op.create_table(
        "source_caches",
        sa.Column("source_identity", sa.String(64), primary_key=True),
        sa.Column("storage_key", sa.Uuid(), nullable=False, unique=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("cache_state", sa.String(16), nullable=False),
        sa.Column("downloaded_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("cache_error_code", sa.String(100)),
        sa.Column("cache_updated_at", sa.DateTime(timezone=True)),
        sa.Column("last_access_at", sa.DateTime(timezone=True)),
        sa.Column("legacy_storage_keys", sa.JSON(), nullable=False),
    )
    op.add_column("debug_entries", sa.Column("cache_identity", sa.String(64), nullable=True))
    op.create_foreign_key(
        "fk_debug_entries_cache_identity_source_caches",
        "debug_entries",
        "source_caches",
        ["cache_identity"],
        ["source_identity"],
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT * FROM debug_entries ORDER BY created_at, id")
    ).mappings()
    groups = defaultdict(list)
    for row in rows:
        groups[row["source_identity"]].append(dict(row))
    entries = sa.table(
        "debug_entries",
        sa.column("source_identity", sa.String(64)),
        sa.column("cache_identity", sa.String(64)),
        *(sa.column(name) for name in CACHE_FIELDS),
    )
    for identity, peers in groups.items():
        chosen = next((row for row in peers if row["cache_state"] == "ready"), peers[0])
        values = {name: chosen[name] for name in CACHE_FIELDS}
        digests = {row["sha256"] for row in peers if row["sha256"]}
        values["sha256"] = chosen["sha256"] or next(iter(digests), None)
        if len(digests) > 1:
            values.update(cache_state="failed", cache_error_code="SOURCE_CHANGED")
        connection.execute(
            cache.insert().values(
                source_identity=identity,
                storage_key=chosen["id"],
                file_name=chosen["file_name"],
                platform=chosen["platform"],
                size_bytes=chosen["size_bytes"],
                **values,
                legacy_storage_keys=[
                    str(row["id"])
                    for row in peers
                    if (row["id"] != chosen["id"] or len(digests) > 1)
                    and row["cache_state"] == "ready"
                ],
            )
        )
        connection.execute(
            entries.update()
            .where(entries.c.source_identity == identity)
            .values(cache_identity=identity, **values)
        )


def downgrade():
    # Entry projections retain metadata. Files remain shared, so mark old-code caches missing;
    # never incorrectly claim per-entry paths exist after reverting schema.
    op.execute("UPDATE debug_entries SET cache_state='missing', downloaded_bytes=0")
    op.drop_constraint(
        "fk_debug_entries_cache_identity_source_caches", "debug_entries", type_="foreignkey"
    )
    op.drop_column("debug_entries", "cache_identity")
    op.drop_table("source_caches")
