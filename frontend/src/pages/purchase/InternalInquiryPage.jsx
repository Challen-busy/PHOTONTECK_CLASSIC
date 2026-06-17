/**
 * InternalInquiryPage —— 内部询价（销售 → PA 内部询价单，PRD 04a-1）
 *
 * 复用 SALES_INQUIRY doc_type + sales_inquiry_line 子表（➕扩 6 列由后端段2b 迁移）。
 * 头 schema 驱动：客户/账期/项目阶段/目标价/竞品价/负责销售/PM；明细网格：型号/描述/数量/目标单价/需求交期。
 * ★sales_inquiry_line 父 FK = inquiry_id（非 sales_inquiry_id，引擎现状）。
 */
import PurchaseDocPage from './PurchaseDocPage';

const STATUS_ENUM = [
  { text: 'DRAFT 草稿', value: 'DRAFT' },
  { text: '询价中 INQUIRING', value: 'INQUIRING' },
  { text: '已报价 QUOTED', value: 'QUOTED' },
  { text: '关闭 CLOSED', value: 'CLOSED' },
];

export default function InternalInquiryPage() {
  return (
    <PurchaseDocPage
      docType="SALES_INQUIRY"
      table="sales_inquiry"
      lineTable="sales_inquiry_line"
      lineFk="inquiry_id"
      title="内部询价"
      subtitle="销售 → PA 内部询价单"
      numberField="inquiry_number"
      statusEnum={STATUS_ENUM}
      editableStates={['DRAFT', 'INQUIRING']}
      lineTitle="询价明细（型号 / 描述 / 数量 / 目标单价 / 需求交期 · 网格录入）"
      scanSequence={['material_id', 'quantity']}
      newLabel="新建内部询价"
      primaryToStates={['INQUIRING', 'QUOTED']}
      intro={{
        title: '一张内部询价单 = 销售一次客户问价需求；落 PA 待办 → PA 据此对原厂询价（对原厂询价页）→ PM 定利润点 → 出报价单',
        description: '容忍 PA 代录 + 邮件兜底：销售只补 end-customer / 项目阶段 / 目标价 / 竞品价等关键字段。DRAFT / 询价中态可改头与明细；推进后经已报价 → 关闭。状态药丸与动作按钮均由引擎流程边生成，不写死。',
      }}
      todoNote="内部询价单复用引擎 SALES_INQUIRY doc_type + sales_inquiry_line 子表。后端段2b 须为 sales_inquiry ➕ 6 列（home_page/application/project_phase/demand_forecast/competitor/competitor_price）+ 注册轻量流程（DRAFT→询价中→已报价→关闭）+ 月度连号编号规则。注册后本页自动点亮。"
    />
  );
}
