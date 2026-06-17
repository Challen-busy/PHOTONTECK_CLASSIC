/**
 * ShipmentRequestPage —— 发货申请入口（PRD 05-客户销售-订单与履约 页面4）
 *
 * 发货申请 = SHIPMENT 出库单（段1b-1 已建，OutboundPage）：必关联 SO（sales_order_id）+ 串货隔离
 *   + ★财务放行 FINANCE_APPROVAL + 仓库互检 PICKING_RECHECK。本页不重造发货单，薄包装指向同一
 *   SHIPMENT 单据——从客户/销售域进入「发货申请」与从仓储域进入「出库发货」是同一引擎单据的两个入口。
 *
 * ★引擎实况（services/phase1_workflows.py SHIPMENT 流程，已勘）：doc_type=SHIPMENT /
 *   shipment_request 表 / shipment_line 子表（FK shipment_id）；状态机
 *   DRAFT→PACKING_LABELING→PICKING_RECHECK（互检★）→FINANCE_APPROVAL（财务放行★）→SALES_OUTBOUND→
 *   CUSTOMER_RECEIVED；shipment_request.sales_order_id 必关联 SO（客户发货由 validator 兜底，不可凭空）。
 *
 * 安全律提示：① 必关联 SO（sales_order_id）——发货数量回写减 SO 在途（SO 数量 - 已发货）；
 *   ② 财务未放行货坚决不出仓（FINANCE_APPROVAL 关）；委外发料（outbound_type=OUTSOURCE）绕过财务放行直发。
 */
import { Alert } from 'antd';
import OutboundPage from '../wms/OutboundPage';

export default function ShipmentRequestPage() {
  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16, borderRadius: 12 }}
        title="发货申请 = 出库单（SHIPMENT）：必关联销售订单 SO + 仓库互检★ + 财务放行★，不可凭空发货"
        description="从客户/销售域提交的「发货申请」与仓储域的「出库发货」是同一引擎单据（doc_type=SHIPMENT / shipment_request）。每张发货申请必关联一张 SO（sales_order_id），发货数量回写减 SO 在途（SO 数量 − 已发货）；走 仓库互检（PICKING_RECHECK）→ 财务放行（FINANCE_APPROVAL，未放行货不出仓）→ 销售出库（SALES_OUTBOUND，扣库存/推金蝶）。动作一律由引擎流程边生成 → /api/transition 唯一写入路径，不写死状态码。"
      />
      <OutboundPage />
    </div>
  );
}
