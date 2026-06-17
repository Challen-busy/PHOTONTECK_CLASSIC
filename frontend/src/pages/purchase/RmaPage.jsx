/**
 * RmaPage —— RMA 退货统一单（SA/PA 双视图，共用 RMA 号，PRD 04b-5）⭐
 *
 * 一张统一单 = 一个共用 RMA 号；SA 与 PA 看同一单的不同视图（决策⑨）：
 *   - SA（销售助理）视图：客户侧——客户报来的失效描述 / 退回数量 / 退换给客户 / 关闭（对客户、不对原厂）。
 *   - PA（采购助理）视图：货物侧——核 SN/LOT+PO+入库判「是否我方卖 / 是否过保」、上报 PM、
 *       对接原厂换/退/修、跟货回入库（对原厂、不对客户）。
 *
 * 🔒 双视图 = 字段级防火墙（引擎原生 ✅）：采购侧列（supplier_id / po_number / unit_price /
 *   supplier_rma_number）对 SA / SALES 由后端按 (表×角色) 遮蔽——/api/schema + /api/query 两路一致，
 *   schema 不返回即不渲。本页纯 schema 驱动、不写死这些列，故同一组件天然分视图。
 *
 * 流程：客户报修(SA) → PA 核料[成立/驳回] → 上报 PM → PM 决策[报原厂换/退/修 · 内部消化] →
 *   货回入库（带来源标记，§5.4）→ SA 退客户 → 关闭。一张 RMA 可含多 SN 行 → 头 + 子表 rma_line。
 *
 * 复用积木：PurchaseDocPage（台账 → 右抽屉 → 顶部动作按钮，全 schema 驱动；动作一律
 *   /api/transitions → /api/transition 唯一写入路径，不写死状态码）+ 子表网格 PurchaseLineGrid
 *   （扫码录 SN/LOT + Excel 粘贴建行，录单增强 14 律 §3）。
 *
 * ★引擎实况：RMA doc_type / rma 表 / rma_line 子表 / 流程 / 字段防火墙由后端段2d 注册。
 *   未注册时 PurchaseDocPage 显示「功能已就绪 · 待后端开通」占位（14 律 §8），注册后自动点亮。
 */
import PurchaseDocPage from './PurchaseDocPage';

// 状态药丸候选（仅台账筛选提示；真实可走边以 /api/transitions 为准，不写死状态码推进）
const STATUS_ENUM = [
  { text: '客户报修 REPORTED', value: 'REPORTED' },
  { text: 'PA 核料 PA_VERIFY', value: 'PA_VERIFY' },
  { text: '上报 PM ESCALATED_PM', value: 'ESCALATED_PM' },
  { text: '对接原厂 VENDOR_RMA', value: 'VENDOR_RMA' },
  { text: '内部消化 INTERNAL', value: 'INTERNAL' },
  { text: '货回入库 GOODS_RETURNED', value: 'GOODS_RETURNED' },
  { text: '退客户 RETURN_TO_CUSTOMER', value: 'RETURN_TO_CUSTOMER' },
  { text: '已关闭 CLOSED', value: 'CLOSED' },
  { text: '已驳回 REJECTED', value: 'REJECTED' },
];

export default function RmaPage() {
  return (
    <PurchaseDocPage
      docType="RMA"
      table="rma"
      lineTable="rma_line"
      lineFk="rma_id"
      title="RMA 退货统一单"
      subtitle="SA/PA 双视图（共用 RMA 号）· 客户报修 → PA 核料 → PM 决策 → 货回入库 → 退客户 → 关闭"
      numberField="rma_number"
      statusEnum={STATUS_ENUM}
      editableStates={['REPORTED', 'PA_VERIFY', 'ESCALATED_PM', 'VENDOR_RMA', 'INTERNAL', 'GOODS_RETURNED', 'RETURN_TO_CUSTOMER']}
      lineTitle="退货明细（型号 / SN-LOT / 数量 / 失效描述 · 网格录入）"
      scanSequence={['material_id', 'serial_lot_number', 'quantity']}
      newLabel="新建 RMA"
      primaryToStates={['PA_VERIFY', 'ESCALATED_PM', 'VENDOR_RMA', 'INTERNAL', 'GOODS_RETURNED', 'RETURN_TO_CUSTOMER']}
      intro={{
        title: '一张 RMA 统一单 = 一个共用 RMA 号，SA 看客户侧、PA 看货物侧（同一单两视图，决策⑨）——采购侧列（供应商 / PO# / 单价 / 原厂 RMA 号）对 SA / 销售由后端字段防火墙遮蔽即不渲，故同一页天然分视图',
        description: 'RMA 号 RMA-{YYMM}-{NNN}（月度连号，后端取号 effect 生成）。流程：客户报修(SA) → PA 核料凭 SN/LOT+PO+入库倒查判「是否我方卖 / 是否过保」（非我方卖或过保 → 驳回，不进 PM）→ 上报 PM → PM 决策「报原厂换/退/修」或「内部消化」→ 货回入库（带来源标记，好货混回可售 §5.4）→ SA 退/换给客户 → 关闭。一张 RMA 可含多 SN 行（明细网格扫码录 SN/LOT + Excel 粘贴建行）。采购侧列与单价（成本侧 §00-8）对 SA / 销售遮蔽——本页按 schema 渲染，SA 登录时这些列不出现、PA 登录给全列。跨境退运走退关（180 天预警，关联 04 报关域）；香港卖的退回香港公司（行级公司隔离天然保证）。动作一律走 /api/transitions（按当前状态 + 角色过滤真实边）→ /api/transition（唯一写入路径），不写死状态码。',
      }}
      todoNote="RMA 为 ➕ 新增 RMA doc_type（引擎 02 §2.9 明确排除「退货」业务；本段 RMA 是采购侧统一单，非 WMS 客退 SALES_RETURN）。需后端段2d 建 rma 表（含 customer_id/supplier_id/material_id/failure_description/po_number/unit_price/ship_date/supplier_rma_number/sold_by_us/under_warranty/pm_decision/return_customs_status 等 + rma_line 子表：material_id/serial_lot_number/quantity/failure_description）+ WorkflowDefinition（REPORTED→PA_VERIFY→ESCALATED_PM→VENDOR_RMA/INTERNAL→GOODS_RETURNED→RETURN_TO_CUSTOMER→CLOSED / REJECTED，节点级 allowed_roles：REPORTED=[SA]、PA_VERIFY=[PA]、ESCALATED_PM=[PM]，规避 D-02e 边级角色坑）+ 建单取号 effect（rma_number 月度连号）+ 核料判定 effect（倒查 SN/LOT+PO+出库写 sold_by_us、ship_date+质保期 vs today 写 under_warranty）+ 货回入库 effect（GOODS_RETURNED→退货入库 inbound_type=退货入库 + inventory.source_marker，§5.4）；并把 (rma 表 × SA/SALES) 的采购侧列 supplier_id/po_number/unit_price/supplier_rma_number 加入字段防火墙遮蔽。注册后本页自动点亮，SA 视图自动遮蔽采购侧列。"
    />
  );
}
