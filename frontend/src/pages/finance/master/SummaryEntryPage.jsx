/**
 * SummaryEntryPage —— 摘要库（财务基础资料）
 *
 * 复用 MasterDataPage（schema 驱动台账 + 详情抽屉 + /api/transition 唯一写入）。
 * doc_type=SUMMARY_ENTRY；seed_master_gl 已种轻量单状态机（单态 ACTIVE 自环编辑），故 writable。
 * 引擎表 summary_entry（AuditMixin + company_id 隔离 +（company_id, code）唯一）。
 *  - 常用凭证摘要文本 + 分类（收款/付款/费用/结转/其他）；录凭证时下拉选用填入 description。
 *  - sort_order 排序权重（常用置顶）。
 */
import MasterDataPage from '../../master/MasterDataPage';

export default function SummaryEntryPage() {
  return (
    <MasterDataPage
      table="summary_entry"
      title="摘要库"
      domain="财务 / 总账 · 基础资料"
      docType="SUMMARY_ENTRY"
      writable
      primaryCols={['code', 'category', 'text']}
      todoNote="摘要库建档/改档走引擎唯一写入路径 /api/transition（SUMMARY_ENTRY 单状态机，seed_master_gl 已种）。code=摘要码、category=分类（收款/付款/费用/结转/其他）、text=摘要文本（录凭证下拉填入 description）、sort_order=排序权重（常用置顶）。"
    />
  );
}
