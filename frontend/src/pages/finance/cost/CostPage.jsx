/**
 * CostPage —— 存货核算（finance-gl 成本波，完全替代金蝶存货核算 P0）
 *
 * ★存货成本引擎（移动平均 InventoryValuation + 出入库成本交易 InventoryTransaction）已在 WMS。
 *   本页 = 成本核算的「财务视图」：暴露成本账 + 业财桥（凭证生成），全后端 _company_filter 隔离。
 *
 * 三 Tab：
 *   · 即时收发明细表 —— /api/reports/inv-cost-ledger（逐成本交易 收入/发出/结存 数量·单价·金额时序滚算）。
 *   · 收发存汇总表 —— /api/reports/inv-inout-summary（按物料 收入/发出 + 当前结存 数量/金额/均价）。
 *   · 凭证生成 —— finance.generate_inventory_vouchers（入库 借库存/贷在途暂估；出库 借主营成本/贷库存）。
 *
 * 期末关账/结账、存货跌价准备为 P1（成本引擎已具备，按需补）。
 */
import { useCallback, useEffect, useState } from 'react';
import { App, Card, Tabs, Table, Tag, Button, Space, Select, Statistic, Row, Col } from 'antd';
import { ReloadOutlined, FileAddOutlined } from '@ant-design/icons';
import { useAuth } from '../../../auth';
import {
  query, getInvCostLedger, getInvInoutSummary, generateInventoryVouchers,
} from '../../../api';
import { MONO, fmtMoney } from '../financeHelpers';

const TYPE = { IN: { label: '入库', color: 'green' }, OUT: { label: '出库', color: 'volcano' } };
const num = (v) => (v == null ? 0 : Number(v));

export default function CostPage() {
  const { user } = useAuth();
  const { message } = App.useApp();
  const [tab, setTab] = useState('ledger');
  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          存货核算
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 存货核算 · 即时收发明细 / 收发存汇总 / 凭证生成（移动平均）· 账簿 = {user?.company_name || `公司 #${user?.company_id ?? ''}`}
        </span>
      </div>
      <Card styles={{ body: { padding: '12px 16px' } }}>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            { key: 'ledger', label: '即时收发明细表', children: <LedgerTab message={message} /> },
            { key: 'summary', label: '收发存汇总表', children: <SummaryTab message={message} /> },
            { key: 'voucher', label: '凭证生成', children: <VoucherTab message={message} /> },
          ]}
        />
      </Card>
    </div>
  );
}

/* ── 即时收发明细表 ── */
function LedgerTab({ message }) {
  const [rows, setRows] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [matId, setMatId] = useState(undefined);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    query('material', { limit: 1000, order_by: 'id' })
      .then(({ data }) => setMaterials(data?.data || []))
      .catch(() => {});
  }, []);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getInvCostLedger(matId ? { material_id: matId } : {});
      setRows(data?.data || []);
    } catch (e) { message.error('加载失败：' + (e.response?.data?.detail || e.message)); }
    finally { setLoading(false); }
  }, [message, matId]);
  useEffect(() => { load(); }, [load]);

  const columns = [
    { title: '物料', dataIndex: 'material_name', render: (v, r) => v || r.material_code || `#${r.material_id}` },
    { title: '类型', dataIndex: 'transaction_type', width: 70, render: (v) => { const t = TYPE[v] || { label: v, color: 'default' }; return <Tag color={t.color}>{t.label}</Tag>; } },
    { title: '日期', dataIndex: 'transaction_date', width: 110 },
    { title: '收入·数量', dataIndex: 'in_qty', align: 'right', render: (v) => v ? num(v) : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '收入·金额', dataIndex: 'in_amount', align: 'right', render: (v) => v ? <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '发出·数量', dataIndex: 'out_qty', align: 'right', render: (v) => v ? num(v) : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '发出·金额', dataIndex: 'out_amount', align: 'right', render: (v) => v ? <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '单价', dataIndex: 'unit_cost', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{num(v).toFixed(4)}</span> },
    { title: '结存·数量', dataIndex: 'balance_qty', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{num(v)}</span> },
    { title: '结存·金额', dataIndex: 'balance_amount', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '凭证', dataIndex: 'voucher_id', width: 70, render: (v) => v ? <Tag color="blue">#{v}</Tag> : <span style={{ color: '#bfbbb5' }}>未生</span> },
  ];
  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Select allowClear showSearch optionFilterProp="label" style={{ width: 280 }} placeholder="全部物料 / 选单物料"
          value={matId} onChange={setMatId}
          options={materials.map((m2) => ({ value: m2.id, label: `${m2.name || ''}${m2.sku ? `（${m2.sku}）` : ''}` }))} />
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Table rowKey="id" size="small" loading={loading} dataSource={rows} columns={columns} pagination={{ pageSize: 30 }} scroll={{ x: 1100 }} />
    </>
  );
}

/* ── 收发存汇总表 ── */
function SummaryTab({ message }) {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getInvInoutSummary({});
      setRows(data?.data || []);
      setTotal(data?.total_balance_amount || 0);
    } catch (e) { message.error('加载失败：' + (e.response?.data?.detail || e.message)); }
    finally { setLoading(false); }
  }, [message]);
  useEffect(() => { load(); }, [load]);

  const columns = [
    { title: '物料', dataIndex: 'material_name', render: (v, r) => v || r.material_code || `#${r.material_id}` },
    { title: '计价方法', dataIndex: 'cost_method', width: 120, render: (v) => v === 'WEIGHTED_AVG' ? '移动平均' : v },
    { title: '收入·数量', dataIndex: 'in_qty', align: 'right' },
    { title: '收入·金额', dataIndex: 'in_amount', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '发出·数量', dataIndex: 'out_qty', align: 'right' },
    { title: '发出·金额', dataIndex: 'out_amount', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '结存·数量', dataIndex: 'balance_qty', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{num(v)}</span> },
    { title: '结存·均价', dataIndex: 'unit_cost', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{num(v).toFixed(4)}</span> },
    { title: '结存·金额', dataIndex: 'balance_amount', align: 'right', render: (v) => <span style={{ fontFamily: MONO, fontWeight: 500 }}>{fmtMoney(v)}</span> },
  ];
  return (
    <>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col><Statistic title="存货结存总额" value={total} precision={2} /></Col>
        <Col style={{ display: 'flex', alignItems: 'flex-end' }}><Button icon={<ReloadOutlined />} onClick={load}>刷新</Button></Col>
      </Row>
      <Table rowKey="material_id" size="small" loading={loading} dataSource={rows} columns={columns} pagination={{ pageSize: 30 }} scroll={{ x: 1000 }} />
    </>
  );
}

/* ── 凭证生成 ── */
function VoucherTab({ message }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const onGen = async (mode) => {
    setBusy(true);
    try {
      const { data } = await generateInventoryVouchers({ mode });
      setResult(data);
      message.success(`凭证生成完成：${data?.summary?.vouchers ?? 0} 张凭证（${data?.summary?.txns ?? 0} 笔成本交易）`);
    } catch (e) { message.error('凭证生成失败：' + (e.response?.data?.detail || e.message)); }
    finally { setBusy(false); }
  };
  return (
    <div style={{ maxWidth: 720 }}>
      <Card size="small" style={{ marginBottom: 16 }}>
        <p style={{ color: '#555', marginTop: 0 }}>
          把已算好成本的存货交易（移动平均）批量生成总账凭证：<br />
          · 入库 IN：借 库存商品 / 贷 在途物资（暂估，与应付单对接）<br />
          · 出库 OUT：借 主营业务成本 / 贷 库存商品（结转销售成本）<br />
          已生过凭证的交易幂等跳过。
        </p>
        <Space>
          <Button type="primary" icon={<FileAddOutlined />} loading={busy} onClick={() => onGen('SUMMARY')}>汇总生成（按类型）</Button>
          <Button icon={<FileAddOutlined />} loading={busy} onClick={() => onGen('DETAIL')}>明细生成（一笔一凭证）</Button>
        </Space>
      </Card>
      {result && (
        <Card size="small" title="本次生成结果">
          <p>凭证 {result.summary?.vouchers ?? 0} 张 · 成本交易 {result.summary?.txns ?? 0} 笔 · 失败 {result.summary?.failed ?? 0}</p>
          <Table rowKey={(r) => `${r.txn_type}-${r.voucher_id}`} size="small" pagination={false}
            dataSource={result.created || []}
            columns={[
              { title: '类型', dataIndex: 'txn_type', render: (v) => (TYPE[v]?.label || v) },
              { title: '凭证号', dataIndex: 'voucher_id', render: (v) => <Tag color="blue">#{v}</Tag> },
              { title: '金额', dataIndex: 'amount', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
              { title: '笔数', dataIndex: 'txns', align: 'right' },
            ]} />
        </Card>
      )}
    </div>
  );
}
