/**
 * AccountingPolicyPage —— 会计政策（财务基础资料）
 *
 * 复用 MasterDataPage（schema 驱动台账 + 详情抽屉 + /api/transition 唯一写入）。
 * doc_type=ACCOUNTING_POLICY；seed_master_gl 已种轻量单状态机（单态 ACTIVE 自环编辑），故 writable。
 * 引擎表 accounting_policy（AuditMixin + company_id 隔离 +（company_id, code）唯一）。
 *
 * 字段较多（准则 + 计量/折旧/存货计价/坏账/会计年度起始月），靠 schema 字段顺序自然分组：
 *   标识(code/name/standard) → 计量口径(measurement_basis/depreciation_method/
 *   inventory_valuation/bad_debt_method) → 会计年度(fiscal_year_start_month) → is_active。
 *   表单控件由 MasterFormFields 按 schema 自动生成（extra JSONB 不列入可编辑字段）。
 *   primaryCols 把 code/name/standard 排前并左冻结，台账一眼看清准则归属。
 */
import MasterDataPage from '../../master/MasterDataPage';

export default function AccountingPolicyPage() {
  return (
    <MasterDataPage
      table="accounting_policy"
      title="会计政策"
      domain="财务 / 总账 · 基础资料"
      docType="ACCOUNTING_POLICY"
      writable
      primaryCols={['code', 'name', 'standard']}
      todoNote="会计政策建档/改档走引擎唯一写入路径 /api/transition（ACCOUNTING_POLICY 单状态机，seed_master_gl 已种）。standard=CAS 内地 / HKFRS 香港；含计量基础/折旧方法/存货计价/坏账方法/会计年度起始月（HK 多 4 月、CN 1 月）。一公司一条主政策（按 code 命名版本）。extra JSONB 为扩展键值，不列入本页可编辑字段。"
    />
  );
}
