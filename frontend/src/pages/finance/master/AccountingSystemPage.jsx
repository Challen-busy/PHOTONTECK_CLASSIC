/**
 * AccountingSystemPage —— 会计核算体系（财务基础资料）
 *
 * 复用 MasterDataPage（schema 驱动台账 + 详情抽屉 + /api/transition 唯一写入）。
 * doc_type=ACCOUNTING_SYSTEM；seed_master_gl 已种轻量单状态机（单态 ACTIVE 自环编辑），故 writable。
 * 引擎表 accounting_system（AuditMixin + company_id 隔离 +（company_id, code）唯一）。
 *
 * 字段较多（账簿标识 + 本位币 + 准则 + 政策外键 + 启用期），靠 schema 字段顺序自然分组：
 *   账簿标识(code/name) → 记账口径(base_currency/standard/policy_id) →
 *   启用期(start_year/start_period) → is_active。
 *   policy_id 为 FK→accounting_policy，由 MasterFormFields 渲为 cell 选择器（loadFkOptions）。
 *   primaryCols 把 code/name/base_currency 排前并左冻结。
 */
import MasterDataPage from '../../master/MasterDataPage';

export default function AccountingSystemPage() {
  return (
    <MasterDataPage
      table="accounting_system"
      title="会计核算体系"
      domain="财务 / 总账 · 基础资料"
      docType="ACCOUNTING_SYSTEM"
      writable
      primaryCols={['code', 'name', 'base_currency']}
      todoNote="会计核算体系（账簿主档）建档/改档走引擎唯一写入路径 /api/transition（ACCOUNTING_SYSTEM 单状态机，seed_master_gl 已种）。一公司一套账簿；base_currency=本位币、standard=CAS/HKFRS、policy_id→会计政策(cell 选择器)、start_year+start_period=启用会计期（首次记账期）。"
    />
  );
}
