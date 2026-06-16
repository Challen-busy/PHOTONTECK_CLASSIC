"""tenant_authz_session_revocation_company_region

段0a 后端核心底座：
- company 区域配置列 region/invoice_title/numbering_prefix/kingdee_org_code（EXT-01-D）
- user_account.session_version 服务端会话吊销（D-05f 升级）
- user_company_access.is_primary/valid_until 用户×公司授权（决策B / EXT-01-C）

Revision ID: 5fe25ee326e8
Revises: 2c3d4e5f
Create Date: 2026-06-16 19:21:55.012941

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5fe25ee326e8'
down_revision: Union[str, Sequence[str], None] = '2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 公司区域配置（EXT-01-D）
    op.add_column('company', sa.Column('region', sa.String(length=10), server_default='HK', nullable=True))
    op.add_column('company', sa.Column('invoice_title', sa.Text(), server_default='', nullable=True))
    op.add_column('company', sa.Column('numbering_prefix', sa.String(length=20), server_default='', nullable=True))
    op.add_column('company', sa.Column('kingdee_org_code', sa.String(length=40), server_default='', nullable=True))

    # 服务端会话吊销（D-05f 升级）
    op.add_column('user_account', sa.Column('session_version', sa.Integer(), server_default='0', nullable=False))

    # 用户×公司授权（决策B / EXT-01-C）
    op.add_column('user_company_access', sa.Column('is_primary', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('user_company_access', sa.Column('valid_until', sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_company_access', 'valid_until')
    op.drop_column('user_company_access', 'is_primary')
    op.drop_column('user_account', 'session_version')
    op.drop_column('company', 'kingdee_org_code')
    op.drop_column('company', 'numbering_prefix')
    op.drop_column('company', 'invoice_title')
    op.drop_column('company', 'region')
