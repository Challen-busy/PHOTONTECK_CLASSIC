/**
 * SalesOrderLedgerPage —— SO 签单大表 / 销售台账（PRD 05-客户销售-订单与履约 页面3 ⭐）
 *
 * 只读聚合全景：把「下单 + 发货 + 开票 + 收款」全链收口为一张只读网格——一行一张 SO，
 * 沿 FK 串起 发货（SHIPMENT）/ 开票（SALES_INVOICE）/ 收款（应收）+ 在途数量（SO 数量 − 已发货）。
 * 决策⑩（同采购台账）：台账 = 只读聚合网格 + 点行下钻 SO 详情抽屉（不在大表内联编辑跨独立单据，不跳页）；
 *   编辑回销售订单 SO 单据页推进。
 *
 * ★状态码 / 表名对准真实 seed（services/phase1_workflows.py SALES_ORDER + models.py，已勘）：
 *   主台账 over /api/query sales_order（列 schema 驱动）；明细 sales_order_line（FK sales_order_id，
 *   含 shipped_quantity 已发货）。在途 = Σ数量 − Σ已发货。
 *
 * 字段防火墙：SO 是卖方视角、无买价列（卖价对客户/对内可见），本页无买价遮蔽问题；纯 schema 渲染。
 *
 * 全链聚合段（发货/开票/收款）= 跨单据沿 FK 聚合，属后端 ➕ 只读聚合端点 /api/sales/ledger（沿
 *   shipment_request + sales_invoice + 应收聚合）。端点未开通（404）或无对应行 → drawer 该段降级
 *   「待后端补段」，不写死假列；后端就绪后本段自动补全（同 PurchaseOrderLedgerPage 模式）。
 */
import { useCallback, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Space } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema, getSalesLedger } from '../../api';
import { schemaToColumns, renderCellByField } from '../wms/wmsHelpers';
import { StatusPill } from '../wms/wmsShared';

const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';

const TABLE = 'sales_order';
const LINE_TABLE = 'sales_order_line';
const LINE_FK = 'sales_order_id';

// 状态药丸候选（对齐真实 seed SALES_ORDER 流程）
const STATUS_ENUM = [
  { text: '草稿/录入 DRAFT', value: 'DRAFT' },
  { text: '销售经理审核 SALES_MANAGER_REVIEW', value: 'SALES_MANAGER_REVIEW' },
  { text: '待客户预收 ADVANCE_RECEIPT_REQUIRED', value: 'ADVANCE_RECEIPT_REQUIRED' },
  { text: '可发起采购通知 READY_FOR_PURCHASE', value: 'READY_FOR_PURCHASE' },
  { text: '采购处理中 PURCHASE_NOTICE_SENT', value: 'PURCHASE_NOTICE_SENT' },
  { text: '待发货通知 READY_TO_SHIP', value: 'READY_TO_SHIP' },
  { text: '发货执行中 SHIPMENT_REQUESTED', value: 'SHIPMENT_REQUESTED' },
  { text: '已完成 COMPLETED', value: 'COMPLETED' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

// 全链聚合段字段（发货/开票/收款，沿 FK 聚合 shipment_request + sales_invoice + 应收）。
// ★键名严格对准 /api/sales/ledger 行真实键（routers/sales.py 返回，已勘）：发货数量段
// ordered/shipped/in_transit_quantity + last_shipped_date + shipment_count + shipment_number；
// 发票段 invoice_number/invoice_date；收款段 receivable_amount/received_amount + receipt_status。
// 由聚合行携带；缺对应键 → chainPresent 不渲该项（不写死假列）。
const CHAIN_FIELDS = [
  { key: 'ordered_quantity', label: '订单数量', type: 'num' },
  { key: 'shipped_quantity', label: '已发货数量', type: 'num' },
  { key: 'in_transit_quantity', label: '在途数量（数量−已发货）', type: 'num' },
  { key: 'last_shipped_date', label: '最近发货日期', type: 'date' },
  { key: 'shipment_count', label: '发货单数', type: 'num' },
  { key: 'shipment_number', label: '最近发货编号', type: 'text' },
  { key: 'invoice_number', label: '最近发票号', type: 'text' },
  { key: 'invoice_date', label: '最近开票日期', type: 'date' },
  { key: 'receivable_amount', label: '应收金额', type: 'num' },
  { key: 'received_amount', label: '已收款金额', type: 'num' },
  { key: 'receipt_status', label: '收款状态', type: 'text' },
];

function chainCell(type, v) {
  if (v == null || v === '') return <span style={{ color: '#bfbbb5' }}>—</span>;
  if (type === 'num') return <span style={{ fontFamily: MONO }}>{Number(v).toLocaleString()}</span>;
  if (type === 'date') return String(v).slice(0, 10);
  return String(v);
}

export default function SalesOrderLedgerPage() {
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [detail, setDetail] = useState(null);
  const [lineRows, setLineRows] = useState([]);
  const [chainRow, setChainRow] = useState(null);     // 当前 SO 的全链聚合行（/api/sales/ledger）
  const [chainState, setChainState] = useState('idle'); // idle | loading | ready | unavailable
  const [drawerOpen, setDrawerOpen] = useState(false);

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
      message.error(e.response?.data?.detail || '加载销售台账失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, message]);

  const loadLines = useCallback(async (headId) => {
    if (!headId) { setLineRows([]); return; }
    try {
      const { data } = await query(LINE_TABLE, { filters: { [LINE_FK]: headId }, limit: 200 });
      setLineRows((data?.data || []).map((r) => ({ ...r })));
    } catch { setLineRows([]); }
  }, []);

  // 拉本 SO 的全链聚合行（发货/开票/收款/在途段，沿 FK 聚合）。
  // 端点未开通（404，段3b 前端先落、后端聚合后补）或无对应行 → unavailable，drawer 显示降级而非写死假列。
  const loadChainRow = useCallback(async (so) => {
    if (!so?.id) { setChainRow(null); setChainState('idle'); return; }
    setChainState('loading');
    try {
      const { data } = await getSalesLedger({ limit: 500 });
      const found = (data?.rows || []).find((r) => r.sales_order_id === so.id) || null;
      setChainRow(found);
      setChainState(found ? 'ready' : 'unavailable');
    } catch {
      setChainRow(null);
      setChainState('unavailable');
    }
  }, []);

  const openDetail = useCallback((row) => {
    setDetail(row);
    loadLines(row?.id);
    loadChainRow(row);
    setDrawerOpen(true);
  }, [loadLines, loadChainRow]);

  const exportCsv = useCallback(async () => {
    try {
      const { data } = await query(TABLE, { order_by: '-id', limit: 1000 });
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
      const BOM = String.fromCharCode(0xFEFF);   // Excel UTF-8 BOM
      const blob = new Blob([`${BOM}${head}\n${body}`], { type: 'text/csv;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `销售签单台账_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
      message.success(`已导出 ${rows.length} 行`);
    } catch (e) {
      message.error(e.response?.data?.detail || '导出失败');
    }
  }, [schema, message]);

  const columns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: ['order_number', 'status'],
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

  // 聚合行里实际存在的全链段字段（后端未补对应键则该键不在 → 不出现）
  const chainPresent = useMemo(
    () => (chainRow ? CHAIN_FIELDS.filter((f) => f.key in chainRow) : []),
    [chainRow]
  );

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          SO 签单大表 / 销售台账
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          客户 / 销售 · 引擎表 <code>{TABLE}</code> · 下单+发货+开票+收款全链只读全景（决策⑩：网格 + 下钻，不跳页）
        </span>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="销售签单台账 = 下单 + 发货 + 开票 + 收款全链一行；点行下钻 SO 详情（不在大表内联编辑，编辑回 SO 单据页）"
        description="按事业部 / 状态 / 客户筛（ProTable 查询条 + 状态药丸）；列含 内部订单号 / 客户订单号 / 客户 / 销售 / PM / 币种 / 税率 / 订单金额 / 状态。SO 是卖方视角、无买价列（卖价对客户/对内可见）。下钻 SO 详情含全链聚合段（已发货 / 在途数量=数量−已发货 / 已开票 / 应收余额，沿 FK 聚合发货+开票+收款，/api/sales/ledger）。支持 CSV 导出。"
      />

      <BizTable
        headerTitle="销售订单签单台账"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        toolBarRender={() => [
          <Space key="tools" size={8}>
            <Button icon={<DownloadOutlined />} onClick={exportCsv}>导出 CSV</Button>
          </Space>,
        ]}
        onRow={(row) => ({ onClick: () => openDetail(row), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 480px)' }}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`SO 详情${detail?.order_number ? ` · ${detail.order_number}` : ''}`}
        width={920}
        submitter={false}
      >
        {detail && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <StatusPill value={detail.status} />
            <span style={{ color: '#bfbbb5', fontSize: 12 }}>
              编辑回销售订单 SO 页推进（台账只读，决策⑩）
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
          型号明细 · {lineRows.length} 行
        </div>
        <LineReadonly rows={lineRows} fields={lineDisplayFields(lineRows)} />

        <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '16px 0 8px' }}>
          发货 / 开票 / 收款全链段（沿 FK 聚合 shipment + 发票 + 应收）
        </div>
        {chainState === 'ready' ? (
          <Descriptions column={2} size="small" bordered
            styles={{ label: { width: 150, color: '#777169' } }}>
            {chainPresent.map((f) => (
              <Descriptions.Item key={f.key} label={f.label}>
                {chainCell(f.type, chainRow?.[f.key])}
              </Descriptions.Item>
            ))}
          </Descriptions>
        ) : chainState === 'loading' ? (
          <span style={{ color: '#bfbbb5', fontSize: 13 }}>聚合中…</span>
        ) : (
          <Alert
            type="warning" showIcon style={{ borderRadius: 12 }}
            title="发货 / 开票 / 收款段聚合中 · 待后端补段"
            description="已发货数量 / 在途数量（订单数量−已发货）/ 最近发货日期 / 已开票金额 / 应收余额 / 已收款 等（沿 FK 聚合 shipment_request + sales_invoice + 应收）由后端只读端点 /api/sales/ledger 出列；端点就绪后本段自动补全，本页不写死假列。"
          />
        )}
      </BizDrawerForm>
    </div>
  );
}

// 只读子表列：从行对象推断可显示键（隐藏系统/FK 父键）
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
