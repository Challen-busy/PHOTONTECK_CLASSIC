/**
 * InventoryPage —— 库存台账（INVENTORY，PRD 03a-3）⭐
 *
 * 落 UX 律 14 + 决策⑩「大台账=只读网格 + 下钻」：
 *   - 只读 BizTable over /api/query inventory（schema 驱动列；冻结 入仓编号/型号/状态）
 *   - status 7 态药丸过滤（AVAILABLE/RESERVED 引擎已有；QUARANTINE/NG/SAMPLE/VENDOR_HOLD/SCRAP 为 PRD E2 扩展，后端补值后自动可选）
 *   - 千分位数字、批次/SN/LOT/库位列、原厂报备客户列（reported_customer_id 后端补列后经 schema 自动出现）
 *   - 点行 → 右抽屉只读详情（Descriptions，schema 全字段）
 *   - 批量：选中 N 行 → 打印入仓编号标签（62×29mm 占位）
 *
 * ⚠️ 成本列防火墙：unit_cost/total_cost 对 SALES 由后端 /api/schema + /api/query 两路遮蔽，
 *    本页按 schema 渲染即可——SALES 拿不到这两列、表里自然不出（不在前端写死成本列）。
 */
import { useCallback, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Space } from 'antd';
import { PrinterOutlined } from '@ant-design/icons';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema } from '../../api';
import { schemaToColumns, renderCellByField } from './wmsHelpers';
import { StatusPill, LabelPrintModal } from './wmsShared';

const TABLE = 'inventory';

// 库存状态 7 态过滤候选（PRD §5.4；引擎现仅前二者有值，余者扩展后自动有数据）
const STATUS_ENUM = [
  { text: 'AVAILABLE 可售', value: 'AVAILABLE' },
  { text: 'RESERVED 已预留', value: 'RESERVED' },
  { text: 'QUARANTINE 待处理/待检', value: 'QUARANTINE' },
  { text: 'NG 不良', value: 'NG' },
  { text: 'SAMPLE 样品', value: 'SAMPLE' },
  { text: 'VENDOR_HOLD 原厂暂存', value: 'VENDOR_HOLD' },
  { text: 'SCRAP 报废', value: 'SCRAP' },
];

export default function InventoryPage() {
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [detail, setDetail] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [labelModal, setLabelModal] = useState({ open: false, codes: [] });

  const tableRequest = useCallback(async (params = {}) => {
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(TABLE); sc = data; setSchema(data); }
      catch { sc = { fields: [] }; }
    }
    const { current: _c, pageSize, keyword, status, ...rest } = params;
    const filters = {};
    if (status) filters.status = status;
    for (const [k, v] of Object.entries(rest)) {
      if (v == null || v === '' || k === '_timestamp') continue;
      filters[k] = v;
    }
    try {
      const { data } = await query(TABLE, {
        filters, search: keyword || '', order_by: '-id',
        limit: Math.min(pageSize || 20, 100),
      });
      return { data: data.data || [], success: true, total: data.total ?? (data.data || []).length };
    } catch (e) {
      message.error(e.response?.data?.detail || '加载库存失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, message]);

  const openDetail = useCallback((row) => { setDetail(row); setDrawerOpen(true); }, []);

  const columns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: ['inbound_number', 'material_id', 'status'],
    statusFilter: ['status'],
    statusEnum: { status: STATUS_ENUM },
    actionCol: {
      title: '操作', dataIndex: '_action', width: 80, fixed: 'right', search: false, hideInSetting: true,
      render: (_, row) => (
        <Button type="link" size="small"
          onClick={(e) => { e.stopPropagation(); openDetail(row); }}>详情</Button>
      ),
    },
  }), [schema, openDetail]);

  const detailFields = useMemo(
    () => (schema?.fields || []).filter((f) => f.name !== 'id'),
    [schema]
  );

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          库存
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>仓储 WMS · 引擎表 <code>{TABLE}</code> · 批次/SN/LOT/库位真相台账（只读）</span>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="库存 = 库存流水累加的投影（只读，不在此直接改数）"
        description="按批次（=入仓编号）粒度；状态变更/出库占用走流水。成本列（unit_cost/total_cost）对销售由后端字段防火墙遮蔽，按 schema 渲染即可。原厂报备客户/来源品质标记/7 态枚举为 PRD E2/E3 扩展，后端补齐后经 schema 自动出现。"
      />

      <BizTable
        headerTitle="库存批次台账"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={{}}
        tableAlertOptionRender={({ selectedRows }) => (
          <Space size={12}>
            <span style={{ color: '#777169' }}>已选 {selectedRows.length} 批次</span>
            <Button type="link" size="small" icon={<PrinterOutlined />}
              onClick={() => setLabelModal({
                open: true,
                codes: selectedRows.map((r) => r.inbound_number).filter(Boolean),
              })}>打印标签</Button>
          </Space>
        )}
        onRow={(row) => ({ onClick: () => openDetail(row), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`库存批次详情${detail?.inbound_number ? ` · ${detail.inbound_number}` : ''}`}
        width={640}
        submitter={false}
      >
        <Descriptions column={1} size="small" bordered
          styles={{ label: { width: 150, color: '#777169' } }}>
          {detailFields.map((f) => (
            <Descriptions.Item key={f.name} label={f.label || f.name}>
              {f.name === 'status'
                ? <StatusPill value={detail?.[f.name]} />
                : renderCellByField(f, detail?.[f.name])}
            </Descriptions.Item>
          ))}
        </Descriptions>
      </BizDrawerForm>

      <LabelPrintModal
        open={labelModal.open}
        onClose={() => setLabelModal({ open: false, codes: [] })}
        codes={labelModal.codes}
      />
    </div>
  );
}
