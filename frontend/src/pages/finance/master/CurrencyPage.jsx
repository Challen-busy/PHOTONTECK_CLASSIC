/**
 * CurrencyPage —— 币别（财务基础资料）
 *
 * 复用 MasterDataPage（schema 驱动台账 + 详情抽屉 + /api/transition 唯一写入）。
 * doc_type=CURRENCY；seed_master_gl 已种轻量单状态机（单态 ACTIVE 自环编辑），故 writable。
 * 引擎表 currency（AuditMixin + company_id 隔离 +（company_id, code）唯一）。
 *  - is_base=本位币（一家公司应只一条 True，软约束）；decimal_places=金额小数位。
 *  - currency.code 被凭证/汇率/单据的 currency 字段弱引用（按 code）。
 */
import MasterDataPage from '../../master/MasterDataPage';

export default function CurrencyPage() {
  return (
    <MasterDataPage
      table="currency"
      title="币别"
      domain="财务 / 总账 · 基础资料"
      docType="CURRENCY"
      writable
      primaryCols={['code', 'name', 'symbol']}
      todoNote="币别建档/改档走引擎唯一写入路径 /api/transition（CURRENCY 单状态机，seed_master_gl 已种）。code=ISO 货币码（HKD/CNY/USD）、is_base=本位币（一公司一条 True 软约束）、decimal_places=金额小数位。若引擎报「没有活跃的流程定义」，需后端跑 seed_master_gl。"
    />
  );
}
