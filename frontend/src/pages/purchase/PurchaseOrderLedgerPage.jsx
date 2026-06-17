/**
 * PurchaseOrderLedgerPage —— PO 总表 / 采购台账（PRD 04a-4）⭐ PA 核心工作台
 *
 * 决策⑩：台账 = 只读聚合网格 + cell 下钻 PO 详情抽屉（不在大表内联编辑跨独立单据，不跳页）。
 * 把飞书三张巨表（PO total + Shipping total + 询价表）的「跟单消单」全景收口为一张只读网格：
 *   - Tab「采购台账（按 PO）」：只读 BizTable over /api/query purchase_order（列 schema 驱动）
 *       → 默认按本人 PA 过滤（purchase_assistant_id = 当前用户）；点行下钻 PO 详情抽屉。
 *   - Tab「按原厂 × 月透视」：同页客户端聚合（PM 想知道某原厂某月发了多少，访谈 08:22）。
 *
 * 🔒 Q18 字段防火墙：单价 / 订单金额 / 预付金额 / 备货金额（采购进价/成本）对销售端（SALES + SA）
 *   隐藏——遮蔽在后端（/api/schema + /api/query 两路），本页纯按 schema 渲染，销售登录时该列不出现。
 *
 * ⏳ 在途 / 发货 / 付款段（源 Shipping total：发货日期 / 到库日期 / 发货数量 / 货款到期 / 付款状态 /
 *   应付余额 / 付款日1·2·3）= 跨单据聚合，属 ➕ 只读聚合端点（PO+在途+发货+付款沿 FK），标「待段2c」。
 *   本页 PO 段 + 透视先落地；聚合端点就绪后扩列，本页不写死这些列。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Segmented, Space, Tabs, Tag } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { useAuth } from '../../auth';
import { query, getSchema } from '../../api';
import { schemaToColumns, renderCellByField } from '../wms/wmsHelpers';
import { StatusPill } from '../wms/wmsShared';

const TABLE = 'purchase_order';
const LINE_TABLE = 'purchase_order_line';
const LINE_FK = 'purchase_order_id';

// 仅采购助理（PA）默认收窄到「我的」；其它角色默认全部（财务本公司、管理层只读由后端 _company_filter 兜底）
const PA_ROLE = 'PRODUCT_ASSISTANT';

export default function PurchaseOrderLedgerPage() {
  const { user } = useAuth();
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [tab, setTab] = useState('ledger');
  const [scope, setScope] = useState(user?.role === PA_ROLE ? 'mine' : 'all');
  const [pivotRows, setPivotRows] = useState([]);   // 透视 Tab 聚合数据源
  const [detail, setDetail] = useState(null);
  const [lineRows, setLineRows] = useState([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const isPA = user?.role === PA_ROLE;

  // 「我的」过滤（仅 PA 有意义）：按 purchase_assistant_id = 当前用户
  const scopeFilter = useMemo(
    () => (scope === 'mine' && user?.id ? { purchase_assistant_id: user.id } : {}),
    [scope, user]
  );

  const tableRequest = useCallback(async (params = {}) => {
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(TABLE); sc = data; setSchema(data); }
      catch { sc = { fields: [] }; }
    }
    const { current: _c, pageSize, keyword, status, ...rest } = params;
    const filters = { ...scopeFilter };
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
      message.error(e.response?.data?.detail || '加载采购台账失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, scopeFilter, message]);

  // 透视 Tab：拉本范围 PO（聚合源，仅 PO 段字段，不含买价口径以外）
  useEffect(() => {
    if (tab !== 'pivot') return;
    let alive = true;
    query(TABLE, { filters: { ...scopeFilter }, order_by: '-id', limit: 500 })
      .then(({ data }) => { if (alive) setPivotRows(data?.data || []); })
      .catch(() => { if (alive) setPivotRows([]); });
    return () => { alive = false; };
  }, [tab, scopeFilter]);

  const loadLines = useCallback(async (headId) => {
    if (!headId) { setLineRows([]); return; }
    try {
      const { data } = await query(LINE_TABLE, { filters: { [LINE_FK]: headId }, limit: 200 });
      setLineRows((data?.data || []).map((r) => ({ ...r })));
    } catch { setLineRows([]); }
  }, []);

  const openDetail = useCallback((row) => {
    setDetail(row);
    loadLines(row?.id);
    setDrawerOpen(true);
  }, [loadLines]);

  const exportCsv = useCallback(async () => {
    try {
      const { data } = await query(TABLE, { filters: { ...scopeFilter }, order_by: '-id', limit: 1000 });
      const rows = data?.data || [];
      if (!rows.length) { message.warning('无数据可导出'); return; }
      const fields = (schema?.fields || []).filter((f) => !f.primary_key).map((f) => f.name);
      const head = fields.join(',');
      const body = rows.map((r) => fields.map((k) => {
        const v = r[k];
        if (v == null) return '';
        const s = String(v).replace(/"/g, '""');
        return /[",\n]/.test(s) ? `"${s}"` : s;
      }).join(',')).join('\n');
      const BOM = String.fromCharCode(0xFEFF);   // Excel UTF-8 BOM（避免源码内嵌不可见 BOM 触发 eslint）
      const blob = new Blob([`${BOM}${head}\n${body}`], { type: 'text/csv;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `采购台账_${scope}_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
      message.success(`已导出 ${rows.length} 行（买价列按当前角色权限——SALES/SA 无采购进价列）`);
    } catch (e) {
      message.error(e.response?.data?.detail || '导出失败');
    }
  }, [schema, scopeFilter, scope, message]);

  const columns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: ['order_number', 'status'],
    statusFilter: ['status'],
    statusEnum: {
      status: [
        { text: '草稿 DRAFT', value: 'DRAFT' },
        { text: '待采购审批 PENDING_APPROVAL', value: 'PENDING_APPROVAL' },
        { text: '★采购审批 FINANCE_APPROVAL', value: 'FINANCE_APPROVAL' },
        { text: '已下单 ORDERED', value: 'ORDERED' },
        { text: '部分到货 PARTIAL', value: 'PARTIAL' },
        { text: '已到货 RECEIVED', value: 'RECEIVED' },
        { text: '已关闭 CLOSED', value: 'CLOSED' },
      ],
    },
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
          PO 总表 / 采购台账
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          采购 / 供应链 · 引擎表 <code>{TABLE}</code> · 跟单消单只读全景（决策⑩：网格 + 下钻，不跳页）
        </span>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="采购台账 = 跨单据聚合的只读全景；点行下钻 PO 详情（不在大表内联编辑，编辑回 PO 单据页）"
        description="PA「只拉我的数据」（默认按本人过滤，可切全部）；列含下单日期 / PO号 / 原厂SO# / 报备客户 / 供应商 / PM / 型号 / 订单数量 / 单价🔒 / 是否备货 / 备货消单。单价 / 订单金额 / 备货金额等采购进价由后端字段防火墙对销售端（SALES + SA）遮蔽——按 schema 渲染，销售登录时该列不出现。在途 / 发货 / 付款段属跨单据聚合端点，标「待段2c」。"
      />

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'ledger',
            label: '采购台账（按 PO）',
            children: (
              <BizTable
                key={reloadKey}
                headerTitle="采购订单台账"
                rowKey="id"
                columns={columns}
                request={tableRequest}
                rowSelection={false}
                toolBarRender={() => [
                  <Space key="scope" size={8}>
                    {isPA && (
                      <Segmented
                        size="small"
                        value={scope}
                        onChange={(v) => { setScope(v); setReloadKey((k) => k + 1); }}
                        options={[{ label: '我的', value: 'mine' }, { label: '全部', value: 'all' }]}
                      />
                    )}
                    <Button icon={<DownloadOutlined />} onClick={exportCsv}>导出 CSV</Button>
                  </Space>,
                ]}
                onRow={(row) => ({ onClick: () => openDetail(row), style: { cursor: 'pointer' } })}
                scroll={{ x: 'max-content', y: 'calc(100vh - 480px)' }}
              />
            ),
          },
          {
            key: 'pivot',
            label: '按原厂 × 月透视',
            children: <SupplierMonthPivot rows={pivotRows} />,
          },
        ]}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`PO 详情${detail?.order_number ? ` · ${detail.order_number}` : ''}`}
        width={920}
        submitter={false}
      >
        {detail && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <StatusPill value={detail.status} />
            {detail.is_stock_order ? <Tag color="gold">备货单 · 待消单</Tag> : null}
            <span style={{ color: '#bfbbb5', fontSize: 12 }}>
              编辑回采购订单 PO 页推进（台账只读，决策⑩）
            </span>
          </div>
        )}

        <Descriptions column={2} size="small" bordered
          styles={{ label: { width: 130, color: '#777169' } }}>
          {detailFields.map((f) => (
            <Descriptions.Item key={f.name} label={f.label || f.name}>
              {f.name === 'status'
                ? <StatusPill value={detail?.[f.name]} />
                : renderCellByField(f, detail?.[f.name])}
            </Descriptions.Item>
          ))}
        </Descriptions>

        <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '16px 0 8px' }}>
          采购明细 · {lineRows.length} 行
        </div>
        <LineReadonly rows={lineRows} fields={lineDisplayFields(lineRows)} />

        <Alert
          type="warning" showIcon style={{ marginTop: 16, borderRadius: 12 }}
          title="在途 / 发货 / 付款段 · 待段2c"
          description="发货日期 / 到库日期 / 发货数量 / 货款到期 / 付款状态 / 应付余额 / 付款日1·2·3 等（源 Shipping total）属跨单据聚合（PO + 在途 + 发货 + 付款沿 FK），由后端 ➕ 只读聚合端点出列，段2c 落地后本抽屉自动补段。"
        />
      </BizDrawerForm>
    </div>
  );
}

// 只读子表列：从行对象推断可显示键（隐藏系统/FK 父键），不写死价格列（买价被防火墙遮蔽则本就无）
function lineDisplayFields(rows) {
  if (!rows.length) return [];
  const SKIP = new Set(['id', 'company_id', 'created_at', 'updated_at', 'created_by_id', 'updated_by_id', LINE_FK]);
  return Object.keys(rows[0]).filter((k) => !SKIP.has(k) && !k.startsWith('_'));
}

function LineReadonly({ rows = [], fields = [] }) {
  if (!rows.length) return <span style={{ color: '#bfbbb5' }}>无明细</span>;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'rgba(245,242,239,0.6)' }}>
            {fields.map((k) => (
              <th key={k} style={{ textAlign: 'left', padding: '6px 10px', color: '#777169', fontWeight: 500, whiteSpace: 'nowrap' }}>{k}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
              {fields.map((k) => (
                <td key={k} style={{ padding: '6px 10px', whiteSpace: 'nowrap' }}>
                  {r[k] == null || r[k] === '' ? <span style={{ color: '#bfbbb5' }}>—</span> : String(r[k])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// 按原厂(supplier_id) × 月(po_date 的 YYYY-MM) 聚合 PO 数量/单数（透视，访谈 08:22）
function SupplierMonthPivot({ rows = [] }) {
  const data = useMemo(() => {
    const map = new Map();
    for (const r of rows) {
      const sup = r.supplier_id != null ? `#${r.supplier_id}` : '（未指定供应商）';
      const month = typeof r.po_date === 'string' && r.po_date ? r.po_date.slice(0, 7) : '（无下单日期）';
      const key = `${sup}|${month}`;
      const cur = map.get(key) || { supplier: sup, month, count: 0, amount: 0, stock: 0 };
      cur.count += 1;
      cur.amount += Number(r.total_amount || 0);   // 销售端 schema 无此列时 r.total_amount 为 undefined → 计 0
      if (r.is_stock_order) cur.stock += 1;
      map.set(key, cur);
    }
    return Array.from(map.values()).sort((a, b) => (a.supplier === b.supplier ? a.month.localeCompare(b.month) : a.supplier.localeCompare(b.supplier)));
  }, [rows]);

  if (!rows.length) {
    return (
      <Alert
        type="info" showIcon style={{ borderRadius: 12 }}
        title="无 PO 数据，暂无可透视"
        description="按当前范围（我的 / 全部）拉取 PO 后，按原厂 × 月聚合单数与订单金额。订单金额对销售端遮蔽则计 0。"
      />
    );
  }
  const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'rgba(245,242,239,0.6)' }}>
            {['原厂(供应商)', '月份', 'PO 单数', '其中备货', '订单金额合计🔒'].map((h, i) => (
              <th key={h} style={{ textAlign: i >= 2 ? 'right' : 'left', padding: '8px 12px', color: '#777169', fontWeight: 500, whiteSpace: 'nowrap' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i} style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
              <td style={{ padding: '8px 12px', whiteSpace: 'nowrap' }}>{r.supplier}</td>
              <td style={{ padding: '8px 12px', whiteSpace: 'nowrap' }}>{r.month}</td>
              <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: MONO }}>{r.count}</td>
              <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: MONO }}>{r.stock || <span style={{ color: '#bfbbb5' }}>—</span>}</td>
              <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: MONO }}>
                {r.amount ? r.amount.toLocaleString() : <span style={{ color: '#bfbbb5' }}>—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
