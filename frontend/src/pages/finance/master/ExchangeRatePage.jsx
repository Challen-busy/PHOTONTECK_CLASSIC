/**
 * ExchangeRatePage —— 汇率（财务基础资料）
 *
 * 复用 MasterDataPage（schema 驱动台账 + 详情抽屉 + /api/transition 唯一写入）。
 * doc_type=EXCHANGE_RATE；seed_master_gl 已种轻量单状态机（单态 ACTIVE 自环编辑），故 writable。
 * 引擎表 exchange_rate（全局表，无 company_id；唯一键 from_currency+to_currency+effective_date）。
 *  - 突出「外币→本位币 + 生效日」：primaryCols 把 from/to/rate/effective_date 排前并左冻结。
 *  - 同一对币别多版本按 effective_date 切换（取最近生效）。
 */
import MasterDataPage from '../../master/MasterDataPage';

export default function ExchangeRatePage() {
  return (
    <MasterDataPage
      table="exchange_rate"
      title="汇率"
      domain="财务 / 总账 · 基础资料"
      docType="EXCHANGE_RATE"
      writable
      primaryCols={['from_currency', 'to_currency', 'rate', 'effective_date']}
      todoNote="汇率建档/改档走引擎唯一写入路径 /api/transition（EXCHANGE_RATE 单状态机，seed_master_gl 已种）。一行 = 「外币(from_currency)→本位币(to_currency) 在 effective_date 当日的折算率(rate)」；唯一键(from_currency,to_currency,effective_date)，同币对多版本按生效日切换。exchange_rate 为全局表（无公司隔离）。"
    />
  );
}
