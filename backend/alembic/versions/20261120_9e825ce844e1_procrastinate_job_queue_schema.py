"""procrastinate job queue schema

Applies the schema bundled with the installed procrastinate version. When
procrastinate is upgraded, add its SQL migrations (procrastinate's
``sql/migrations`` folder) as new Alembic revisions.

Revision ID: 9e825ce844e1
Revises: a9b5423d01e1
Create Date: 2026-11-20 19:55:00

"""
from typing import Sequence, Union

from alembic import op
from procrastinate.schema import SchemaManager

# revision identifiers, used by Alembic.
revision: str = '9e825ce844e1'
down_revision: Union[str, Sequence[str], None] = 'a9b5423d01e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Drops every procrastinate table, function, enum and composite type in the public schema.
DROP_PROCRASTINATE = """
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables
             WHERE schemaname = 'public' AND tablename LIKE 'procrastinate%' LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', r.tablename);
    END LOOP;
    FOR r IN SELECT p.oid::regprocedure AS signature FROM pg_proc p
             JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public' AND p.proname LIKE 'procrastinate%' LOOP
        EXECUTE format('DROP FUNCTION IF EXISTS %s CASCADE', r.signature);
    END LOOP;
    FOR r IN SELECT t.typname FROM pg_type t
             JOIN pg_namespace n ON n.oid = t.typnamespace
             WHERE n.nspname = 'public' AND t.typname LIKE 'procrastinate%' AND t.typtype IN ('e', 'c') LOOP
        EXECUTE format('DROP TYPE IF EXISTS %I CASCADE', r.typname);
    END LOOP;
END $$;
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(SchemaManager.get_schema())


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(DROP_PROCRASTINATE)
