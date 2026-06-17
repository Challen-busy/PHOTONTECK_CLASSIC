/**
 * SupplierInquiryPage —— 对原厂询价登记（PA → 原厂询价 / 原厂报价记录，PRD 04a-2）➕
 *
 * 复用 ➕ 新建 SUPPLIER_INQUIRY doc_type + supplier_inquiry_line 子表（后端段2b 注册）。
 * 头：供应商 / 关联内部询价 / PM / 状态；明细网格：型号 / 描述 / 对原厂单价 / 货币 / 数量 / UOM /
 *   货期 / 贸易条件 / 付款条件 / 询价日期 / 客户 / 负责销售 / 备注 / 业务模式 / 佣金 / 供应商。
 *
 * 🔒 Q18 字段防火墙：对原厂单价 unit_price / 佣金 commission 等采购进价对销售端（SALES + SA）一并隐藏。
 *    遮蔽在后端（supplier_inquiry_line ∈ BUY_TABLES，unit_price/commission ∈ BUY_PRICE_FIELDS，
 *    _can_view_buy_price 不含 SALES/SA）。本页纯按 /api/schema 渲染——SALES/SA 登录时 schema
 *    不返回该列即不渲，前端不写死价格列。
 */
import PurchaseDocPage from './PurchaseDocPage';

const STATUS_ENUM = [
  { text: '询价中 INQUIRING', value: 'INQUIRING' },
  { text: '已回价 QUOTED', value: 'QUOTED' },
  { text: '已采用 ADOPTED', value: 'ADOPTED' },
  { text: '关闭 CLOSED', value: 'CLOSED' },
];

export default function SupplierInquiryPage() {
  return (
    <PurchaseDocPage
      docType="SUPPLIER_INQUIRY"
      table="supplier_inquiry"
      lineTable="supplier_inquiry_line"
      lineFk="supplier_inquiry_id"
      title="对原厂询价"
      subtitle="PA → 原厂询价 / 原厂报价登记"
      numberField="inquiry_number"
      statusEnum={STATUS_ENUM}
      editableStates={['INQUIRING', 'QUOTED']}
      lineTitle="对原厂询价明细（型号 / 对原厂单价 / 货币 / 数量 / UOM / 货期 / 贸易条件 / 付款条件 / 客户 / 业务模式 · 网格录入）"
      scanSequence={['material_id', 'quantity']}
      newLabel="新建对原厂询价"
      primaryToStates={['QUOTED', 'ADOPTED']}
      intro={{
        title: '一张对原厂询价单 = PA 向 1~N 家供应商/原厂询价并登记其回价（采购侧成本来源，对销售严格隐藏）',
        description: '同一型号可向多家供应商询价、得多个报价行；PA 据此 + PM 利润点出对客户报价。对原厂单价 / 佣金等采购进价由后端字段防火墙对销售端（SALES + SA）遮蔽——本页按 schema 渲染，销售登录时该列不出现。询价中 / 已回价态可改；推进经已采用 → 关闭。',
      }}
      todoNote="对原厂询价登记需后端段2b ➕ 新建 supplier_inquiry（__doc_types__=('SUPPLIER_INQUIRY',)）+ supplier_inquiry_line 子表 + 轻量流程（INQUIRING→QUOTED→ADOPTED→CLOSED）+ SQ 前缀月度连号编号规则；并把 supplier_inquiry_line 加入 BUY_TABLES、unit_price/commission 加入 BUY_PRICE_FIELDS（Q18 防火墙）。注册后本页自动点亮，价格列对 SALES/SA 自动隐藏。"
    />
  );
}
