/**
 * CashflowItemPage —— 现金流量项目主数据维护（finance-gl wave-3 配账基础资料）
 *
 * 现金流量项目（direction=IN 流入 / OUT 流出），parent_id 自引用构成经营 / 投资 / 筹资分类树。
 * 录凭证时分录上指定现金流量项目（见 AuxAccountingModal）。
 *
 * 纯复用主数据通用壳 MasterDataPage（schema 驱动台账 → 详情抽屉 → /api/transition 唯一写入），
 * 与 master/customers、master/suppliers 同壳同范式：
 *   - 台账列由 /api/schema(cashflow_item) 自动生成（含 parent_id 列，自引用层级）；
 *   - 建档(doc_id=null) / 改档(有 id) 抽屉提交走引擎唯一写入路径 /api/transition，doc_type=CASHFLOW_ITEM；
 *     parent_id 为 FK→cashflow_item，MasterFormFields 自动渲 cell 选择器（同表父级）；
 *   - CASHFLOW_ITEM 须有「活跃 WorkflowDefinition」（seed 单态 ACTIVE + 自环编辑）才可写，
 *     否则 MasterDataPage 自动降级只读 + TODO 横幅，绝不伪造写。
 */
import MasterDataPage from '../../master/MasterDataPage';

export default function CashflowItemPage() {
  return (
    <MasterDataPage
      table="cashflow_item"
      title="现金流量项目"
      domain="财务 / 总账 · 基础资料"
      docType="CASHFLOW_ITEM"
      writable
      primaryCols={['code', 'name']}
      todoNote="现金流量项目（direction=IN 流入 / OUT 流出，parent_id 自引用=经营 / 投资 / 筹资分类树）建档 / 改档走 /api/transition（CASHFLOW_ITEM 状态机，单态 ACTIVE + 自环编辑）；父级 parent_id 为同表 FK，抽屉走 cell 选择器。若引擎报「没有活跃的流程定义」，需后端为 CASHFLOW_ITEM 种最小 WorkflowDefinition（参照 CUSTOMER/SUPPLIER）。"
    />
  );
}
