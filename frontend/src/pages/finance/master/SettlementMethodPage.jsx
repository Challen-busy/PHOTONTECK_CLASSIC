/**
 * SettlementMethodPage —— 结算方式（财务基础资料）
 *
 * 复用 MasterDataPage（schema 驱动台账 + 详情抽屉 + /api/transition 唯一写入）。
 * doc_type=SETTLEMENT_METHOD；seed_master_gl 已种轻量单状态机（单态 ACTIVE 自环编辑），故 writable。
 * 引擎表 settlement_method（AuditMixin + company_id 隔离 +（company_id, code）唯一）。
 *  - method_type=CASH 现金 / TRANSFER 转账 / NOTE 票据 / WIRE 电汇。
 *  - needs_settlement_no=票据/电汇通常需结算号（票号）。
 *  - 被 VoucherEntry.settlement_method 弱引用（按 code）。
 */
import MasterDataPage from '../../master/MasterDataPage';

export default function SettlementMethodPage() {
  return (
    <MasterDataPage
      table="settlement_method"
      title="结算方式"
      domain="财务 / 总账 · 基础资料"
      docType="SETTLEMENT_METHOD"
      writable
      primaryCols={['code', 'name', 'method_type']}
      todoNote="结算方式建档/改档走引擎唯一写入路径 /api/transition（SETTLEMENT_METHOD 单状态机，seed_master_gl 已种）。method_type=CASH 现金 / TRANSFER 转账 / NOTE 票据 / WIRE 电汇；needs_settlement_no=票据/电汇是否需结算号（票号）。被凭证分录 settlement_method 引用。"
    />
  );
}
