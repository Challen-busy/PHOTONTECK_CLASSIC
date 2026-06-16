/**
 * MovementPage —— 库存流水 / 事务台账（inventory_movement，事件溯源，PRD 03a-4）⭐
 *
 * 落 UX 律 14 + 决策⑩：只读 BizTable over /api/query inventory_movement（schema 驱动列）。
 *   - movement_type 药丸过滤（IN/OUT/RESERVE/RELEASE/TRANSFER_IN/TRANSFER_OUT/COUNT_ADJUST/STATUS_CHANGE；后端补值自动可选）
 *   - quantity_delta / reserved_delta 千分位右对齐；来源单（source_doc_type/source_doc_id）、操作人/时间
 *   - 点行 → 右抽屉只读详情（含命令链 command_log_id，可下钻命令中心）
 *   - 流水只增不改：本页无任何写入/编辑入口（PRD 验收：不可编辑/删除）
 *
 * ⚠️ unit_cost 对 SALES 由后端字段防火墙遮蔽，按 schema 渲染即可（不写死成本列）。
 */
import { useCallback, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions } from 'antd';
import { useNavigate } from 'react-router-dom';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema } from '../../api';
import { schemaToColumns, renderCellByField } from './wmsHelpers';
import { StatusPill } from './wmsShared';

const TABLE = 'inventory_movement';

const TYPE_ENUM = [
  { text: 'IN 入库', value: 'IN' },
  { text: 'OUT 出库', value: 'OUT' },
  { text: 'RESERVE 预留', value: 'RESERVE' },
  { text: 'RELEASE 释放', value: 'RELEASE' },
  { text: 'TRANSFER_IN 调入', value: 'TRANSFER_IN' },
  { text: 'TRANSFER_OUT 调出', value: 'TRANSFER_OUT' },
  { text: 'COUNT_ADJUST 盘点调整', value: 'COUNT_ADJUST' },
  { text: 'STATUS_CHANGE 状态变更', value: 'STATUS_CHANGE' },
];

export default function MovementPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [schema, setSchema] = useState(null);
  const [detail, setDetail] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const tableRequest = useCallback(async (params = {}) => {
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(TABLE); sc = data; setSchema(data); }
      catch { sc = { fields: [] }; }
    }
    const { current: _c, pageSize, keyword, movement_type, ...rest } = params;
    const filters = {};
    if (movement_type) filters.movement_type = movement_type;
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
      message.error(e.response?.data?.detail || '加载库存流水失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, message]);

  const openDetail = useCallback((row) => { setDetail(row); setDrawerOpen(true); }, []);

  const columns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: ['movement_type'],
    statusFilter: ['movement_type'],
    statusEnum: { movement_type: TYPE_ENUM },
    statusFields: ['movement_type'],
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
          库存流水 / 事务台账
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>仓储 WMS · 引擎表 <code>{TABLE}</code> · 事件溯源真相源（只增不改）</span>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="库存 = 这些流水的累加投影；每次进/出/调拨/盘点/状态变更写一条不可改流水"
        description="入库审核通过写一条 IN；出库写 OUT/RESERVE；同一命令的流水可经 command_log_id 在命令中心联查。本台账无任何编辑/删除入口。"
      />

      <BizTable
        headerTitle="库存流水台账"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        onRow={(row) => ({ onClick: () => openDetail(row), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`库存流水详情${detail?.id ? ` · #${detail.id}` : ''}`}
        width={560}
        submitter={false}
      >
        <Descriptions column={1} size="small" bordered
          styles={{ label: { width: 150, color: '#777169' } }}>
          {detailFields.map((f) => (
            <Descriptions.Item key={f.name} label={f.label || f.name}>
              {f.name === 'movement_type'
                ? <StatusPill value={detail?.[f.name]} />
                : renderCellByField(f, detail?.[f.name])}
            </Descriptions.Item>
          ))}
        </Descriptions>
        {detail?.command_log_id && (
          <Button type="link" style={{ marginTop: 12, paddingLeft: 0 }}
            onClick={() => navigate('/data/inventory_movement')}>
            来源命令 #{detail.command_log_id} · 在命令中心查看（admin）
          </Button>
        )}
      </BizDrawerForm>
    </div>
  );
}
