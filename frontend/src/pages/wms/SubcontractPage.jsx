/**
 * SubcontractPage —— 委外加工（PRD 03a-9）
 *
 * 委外加工入库 = 入库页(GOODS_RECEIPT, inbound_type=OUTSOURCE_IN)；委外发料 = 出库页(SHIPMENT, outbound_type=OUTSOURCE)。
 * 不新增 doc_type / 状态机：复用整套 GOODS_RECEIPT / SHIPMENT 流程与 effect（段1a 已加 goods_receipt.inbound_type 列、
 * 本段后端补 inbound_type 值 OUTSOURCE_IN + source_issue_number 弱关联委外发料单号）。
 *
 * 本页只给「可见独立入口 + 两视图 Tab」：复用 InboundPage / OutboundPage 积木（presetType 固定类型过滤 + 新建默认值）。
 * 后端补 inbound_type / outbound_type 列前，过滤为空操作（/api/query 忽略未知字段），列表照常显示全量；
 * 补列后自动按委外类型收窄——schema/列驱动，前端不写死。
 */
import { Tabs } from 'antd';
import InboundPage from './InboundPage';
import OutboundPage from './OutboundPage';

export default function SubcontractPage() {
  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          委外加工
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          仓储 WMS · 委外加工入库复用入库流程、委外发料复用出库流程（不新增单据类型）
        </span>
      </div>
      <Tabs
        defaultActiveKey="in"
        items={[
          {
            key: 'in',
            label: '委外加工入库',
            children: (
              <InboundPage
                title="委外加工入库"
                subtitle={<>仓储 WMS · 复用 <code>GOODS_RECEIPT</code> 流程 · inbound_type=OUTSOURCE_IN · 弱关联委外发料单号</>}
                presetType={{ field: 'inbound_type', value: 'OUTSOURCE_IN' }}
              />
            ),
          },
          {
            key: 'out',
            label: '委外发料',
            children: (
              <OutboundPage
                title="委外发料"
                subtitle={<>仓储 WMS · 复用 <code>SHIPMENT</code> 流程 · outbound_type=OUTSOURCE · 发料给委外厂加工</>}
                presetType={{ field: 'outbound_type', value: 'OUTSOURCE' }}
              />
            ),
          },
        ]}
      />
    </div>
  );
}
