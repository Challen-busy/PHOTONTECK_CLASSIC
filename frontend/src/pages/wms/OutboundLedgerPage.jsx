/**
 * OutboundLedgerPage —— 出库台账 / 基本出库视图（PRD 03b 页面 3）
 *
 * 落 UX 律 14 + 决策⑦「明细=真相源，汇总=同页视图，不拆页」：
 *   - Tab「出庫登記（明细）」：只读 BizTable over /api/query shipment_line（A~S 列 schema 驱动）
 *   - Tab「基本出庫（按型号/性质汇总）」：同页 OutboundSummary 聚合视图
 *   - Tab「入仓编号·出库总数量（透视）」：同页 OutboundSummary 按入仓编号聚合
 *
 * ⚠️ 成本/在途单价对 SALES 由后端 /api/schema + /api/query 两路遮蔽，本页按 schema 渲染即可（不写死成本列）。
 * 汇总 Tab 从当前已加载明细行客户端聚合（口径同页面 2）；大数据量跨表实时联动结存属报表扩展点（engineFlag）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Tabs } from 'antd';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema } from '../../api';
import OutboundSummary from './OutboundSummary';
import { schemaToColumns, renderCellByField } from './wmsHelpers';

const TABLE = 'shipment_line';

export default function OutboundLedgerPage() {
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [tab, setTab] = useState('detail');
  const [allLines, setAllLines] = useState([]);   // 汇总 Tab 的聚合数据源
  const [detail, setDetail] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 汇总 Tab：拉本期出库明细行（聚合源）
  useEffect(() => {
    if (tab === 'detail') return;
    let alive = true;
    query(TABLE, { order_by: '-id', limit: 500 }).then(({ data }) => {
      if (alive) setAllLines(data?.data || []);
    }).catch(() => { if (alive) setAllLines([]); });
    return () => { alive = false; };
  }, [tab]);

  const tableRequest = useCallback(async (params = {}) => {
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(TABLE); sc = data; setSchema(data); }
      catch { sc = { fields: [] }; }
    }
    const { current: _c, pageSize, keyword, ...rest } = params;
    const filters = {};
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
      message.error(e.response?.data?.detail || '加载出库明细失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, message]);

  const openDetail = useCallback((row) => { setDetail(row); setDrawerOpen(true); }, []);

  const columns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: ['inbound_number'],
    statusFields: [],
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
          出库台账 / 基本出库
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>仓储 WMS · 引擎表 <code>{TABLE}</code> · 出庫登記明细（真相源）+ 同页汇总/透视视图</span>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="出庫登記（明细）= 真相源；基本出庫 / 入仓编号透视 = 同页聚合视图（不拆页，决策⑦）"
        description="明细按入仓编号/型号/SN/性质/数量/客户/INV#/箱号/送货形式逐行；汇总 Tab 按型号·性质或入仓编号聚合出库总量。成本/在途单价对销售由后端字段防火墙遮蔽，按 schema 渲染即可。"
      />

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'detail',
            label: '出庫登記（明细）',
            children: (
              <BizTable
                headerTitle="出库明细台账"
                rowKey="id"
                columns={columns}
                request={tableRequest}
                rowSelection={false}
                onRow={(row) => ({ onClick: () => openDetail(row), style: { cursor: 'pointer' } })}
                scroll={{ x: 'max-content', y: 'calc(100vh - 480px)' }}
              />
            ),
          },
          {
            key: 'summary',
            label: '基本出庫（按型号/性质汇总）',
            children: <OutboundSummary rows={allLines} mode="model" />,
          },
          {
            key: 'pivot',
            label: '入仓编号·出库总数量（透视）',
            children: <OutboundSummary rows={allLines} mode="inbound" />,
          },
        ]}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`出库明细详情${detail?.inbound_number ? ` · ${detail.inbound_number}` : ''}`}
        width={560}
        submitter={false}
      >
        <Descriptions column={1} size="small" bordered
          styles={{ label: { width: 150, color: '#777169' } }}>
          {detailFields.map((f) => (
            <Descriptions.Item key={f.name} label={f.label || f.name}>
              {renderCellByField(f, detail?.[f.name])}
            </Descriptions.Item>
          ))}
        </Descriptions>
      </BizDrawerForm>
    </div>
  );
}
