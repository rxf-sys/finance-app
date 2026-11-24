"""initial identity and auth tables

Revision ID: a9b5423d01e1
Revises: 
Create Date: 2026-11-20 19:52:58.536970

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a9b5423d01e1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('households',
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_households'))
    )
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('totp_secret_encrypted', sa.LargeBinary(), nullable=True),
    sa.Column('totp_enabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('totp_last_used_step', sa.Integer(), nullable=True),
    sa.Column('failed_login_count', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_audit_log_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index(op.f('ix_audit_log_at'), 'audit_log', ['at'], unique=False)
    op.create_index(op.f('ix_audit_log_user_id'), 'audit_log', ['user_id'], unique=False)
    op.create_table('auth_challenges',
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('purpose', sa.Enum('mfa_login', 'webauthn_register', 'webauthn_login', name='challenge_purpose'), nullable=False),
    sa.Column('challenge', sa.LargeBinary(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_auth_challenges_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_challenges'))
    )
    op.create_index(op.f('ix_auth_challenges_user_id'), 'auth_challenges', ['user_id'], unique=False)
    op.create_table('household_members',
    sa.Column('household_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.Enum('owner', 'member', name='household_role'), nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['household_id'], ['households.id'], name=op.f('fk_household_members_household_id_households'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_household_members_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('household_id', 'user_id', name=op.f('pk_household_members')),
    sa.UniqueConstraint('user_id', name=op.f('uq_household_members_user_id'))
    )
    op.create_table('invites',
    sa.Column('household_id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('role', sa.Enum('owner', 'member', name='household_role'), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_by_id', sa.Uuid(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_invites_created_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['household_id'], ['households.id'], name=op.f('fk_invites_household_id_households'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invites')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_invites_token_hash'))
    )
    op.create_index(op.f('ix_invites_household_id'), 'invites', ['household_id'], unique=False)
    op.create_table('user_sessions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_user_sessions_token_hash'))
    )
    op.create_index(op.f('ix_user_sessions_user_id'), 'user_sessions', ['user_id'], unique=False)
    op.create_table('webauthn_credentials',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('credential_id', sa.LargeBinary(), nullable=False),
    sa.Column('public_key', sa.LargeBinary(), nullable=False),
    sa.Column('sign_count', sa.Integer(), nullable=False),
    sa.Column('transports', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_webauthn_credentials_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webauthn_credentials')),
    sa.UniqueConstraint('credential_id', name=op.f('uq_webauthn_credentials_credential_id'))
    )
    op.create_index(op.f('ix_webauthn_credentials_user_id'), 'webauthn_credentials', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_webauthn_credentials_user_id'), table_name='webauthn_credentials')
    op.drop_table('webauthn_credentials')
    op.drop_index(op.f('ix_user_sessions_user_id'), table_name='user_sessions')
    op.drop_table('user_sessions')
    op.drop_index(op.f('ix_invites_household_id'), table_name='invites')
    op.drop_table('invites')
    op.drop_table('household_members')
    op.drop_index(op.f('ix_auth_challenges_user_id'), table_name='auth_challenges')
    op.drop_table('auth_challenges')
    op.drop_index(op.f('ix_audit_log_user_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_at'), table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_table('users')
    op.drop_table('households')
    sa.Enum(name='household_role').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='challenge_purpose').drop(op.get_bind(), checkfirst=True)
