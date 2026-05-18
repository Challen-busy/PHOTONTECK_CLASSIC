import { useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Table, Card, Input, Select, Space, Tag, Button, Drawer, Row, Col,
  Breadcrumb, Tooltip, Popover, Checkbox, Empty, Segmented,
} from 'antd';
import {
  ReloadOutlined, HistoryOutlined, ArrowRightOutlined, HomeOutlined,
  DownloadOutlined, SettingOutlined, ColumnHeightOutlined,
  TeamOutlined, ShopOutlined, AppstoreOutlined, InboxOutlined,
  ShoppingCartOutlined, ShoppingOutlined, FileTextOutlined,
  DollarOutlined, BankOutlined, AuditOutlined, SwapOutlined,
  ProjectOutlined, HistoryOutlined as LogOutlined, ContainerOutlined,
  TruckOutlined, GoldOutlined, FileDoneOutlined, LockOutlined,
} from '@ant-design/icons';
import { query, aggregate } from '../api';
import { useAuth } from '../auth';

// ---------- 元信息：表的人文描述 ----------
const TABLE_META = {
  // 主数据
  customer:           { cn: '客户',         desc: '客户主数据与联系方式',         icon: <TeamOutlined />,        cat: 'master' },
  supplier:           { cn: '供应商',       desc: '供应商主数据与资质',           icon: <ShopOutlined />,        cat: 'master' },
  material:           { cn: '物料',         desc: '统一物料编码与规格',           icon: <AppstoreOutlined />,    cat: 'master' },
  warehouse:          { cn: '仓库',         desc: '仓库与库位主数据',             icon: <InboxOutlined />,       cat: 'master' },
  // 交易
  sales_order:        { cn: '销售订单',     desc: '从客户下单到回款的主单据',     icon: <ShoppingCartOutlined />,cat: 'txn' },
  sales_order_line:   { cn: '销售订单行',   desc: '销售订单的物料明细',           icon: <FileTextOutlined />,    cat: 'txn' },
  purchase_order:     { cn: '采购订单',     desc: '向供应商采购的主单据',         icon: <ShoppingOutlined />,    cat: 'txn' },
  purchase_order_line:{ cn: '采购订单行',   desc: '采购订单的物料明细',           icon: <FileTextOutlined />,    cat: 'txn' },
  framework_contract: { cn: '框架合同',     desc: '与客户的长期框架协议',         icon: <FileDoneOutlined />,    cat: 'txn' },
  sales_inquiry:      { cn: '客户询价',     desc: '客户需求、目标价、交期与包装要求', icon: <TeamOutlined />,        cat: 'crm' },
  sales_inquiry_line: { cn: '询价明细',     desc: '询价单的产品和数量明细',       icon: <FileTextOutlined />,    cat: 'crm' },
  quotation:          { cn: '报价单',       desc: 'PM 授权后的正式客户报价',     icon: <FileDoneOutlined />,    cat: 'crm' },
  quotation_line:     { cn: '报价明细',     desc: '报价单产品、价格和税率明细',   icon: <FileTextOutlined />,    cat: 'crm' },
  purchase_notice:    { cn: '采购通知',     desc: '销售订单传递给采购侧的需求',   icon: <ShoppingOutlined />,    cat: 'txn' },
  purchase_notice_line:{ cn: '采购通知行',  desc: '采购通知的物料需求明细',       icon: <FileTextOutlined />,    cat: 'txn' },
  // 仓储
  inventory:          { cn: '库存批次',     desc: '按批次记录的现货库存',         icon: <GoldOutlined />,        cat: 'wms' },
  inventory_reservation:{ cn: '库存预留',   desc: '客户或销售订单锁定的包装库存', icon: <LockOutlined />,        cat: 'wms' },
  inventory_policy:   { cn: '库存策略',     desc: '安全库存、补货点和库存预警规则', icon: <SettingOutlined />,     cat: 'wms' },
  inventory_count:    { cn: '盘点任务',     desc: '库存盘点任务和调整状态',       icon: <AuditOutlined />,       cat: 'wms' },
  inventory_count_line:{ cn: '盘点明细',    desc: '盘点快照、实盘数和差异',       icon: <FileTextOutlined />,    cat: 'wms' },
  shipment_request:   { cn: '发货单',       desc: '出库发货指令',                 icon: <TruckOutlined />,       cat: 'wms' },
  goods_receipt:      { cn: '入库单',       desc: '到货收货登记',                 icon: <ContainerOutlined />,   cat: 'wms' },
  supplier_sn_rule:   { cn: 'SN/LOT规则',   desc: '按供应商配置序列号校验规则',   icon: <AuditOutlined />,       cat: 'wms' },
  wms_attachment:     { cn: 'WMS附件',      desc: '入库照片、标签照片和附件',     icon: <FileTextOutlined />,    cat: 'wms' },
  sales_return:       { cn: '销售退货',     desc: '客户退货通知和退货入库源单',   icon: <TruckOutlined />,       cat: 'wms' },
  sales_return_line:  { cn: '销售退货行',   desc: '退货物料和处理方式',           icon: <FileTextOutlined />,    cat: 'wms' },
  // 财务
  voucher:            { cn: '凭证',         desc: '记账凭证主表',                 icon: <AuditOutlined />,       cat: 'fin' },
  voucher_entry:      { cn: '凭证分录',     desc: '凭证的借贷明细',               icon: <FileTextOutlined />,    cat: 'fin' },
  account:            { cn: '会计科目',     desc: '会计科目主数据',               icon: <BankOutlined />,        cat: 'fin' },
  accounts_receivable:{ cn: '应收账款',     desc: '客户欠款台账',                 icon: <DollarOutlined />,      cat: 'fin' },
  accounts_payable:   { cn: '应付账款',     desc: '应付供应商账款',               icon: <DollarOutlined />,      cat: 'fin' },
  advance_receipt:    { cn: '预收单',       desc: '客户未发货前付款登记',         icon: <DollarOutlined />,      cat: 'fin' },
  advance_payment:    { cn: '预付单',       desc: '向供应商提前付款登记',         icon: <DollarOutlined />,      cat: 'fin' },
  purchase_invoice:   { cn: '采购发票',     desc: '采购发票与入库勾稽',           icon: <FileDoneOutlined />,    cat: 'fin' },
  purchase_invoice_line:{ cn: '采购发票行', desc: '采购发票物料明细',             icon: <FileTextOutlined />,    cat: 'fin' },
  sales_invoice:      { cn: '销售发票',     desc: '销售发票与出库勾稽',           icon: <FileDoneOutlined />,    cat: 'fin' },
  sales_invoice_line: { cn: '销售发票行',   desc: '销售发票物料和成本明细',       icon: <FileTextOutlined />,    cat: 'fin' },
  customer_credit:    { cn: '客户信用',     desc: '给客户的信用额度',             icon: <DollarOutlined />,      cat: 'fin' },
  supplier_credit:    { cn: '供应商信用',   desc: '供应商授予的信用额度',         icon: <DollarOutlined />,      cat: 'fin' },
  exchange_rate:      { cn: '汇率',         desc: '多币种兑换汇率',               icon: <SwapOutlined />,        cat: 'fin' },
  // CRM
  project:            { cn: '选型项目',     desc: '客户选型与跟踪',               icon: <ProjectOutlined />,     cat: 'crm' },
  // 系统
  workflow_log:       { cn: '操作日志',     desc: '所有数据修改的完整审计流水',   icon: <LogOutlined />,         cat: 'sys' },
};

// 降饱和的分类色调
const CATEGORIES = [
  { key: 'master', label: '主数据',  hint: '业务的基石，相对稳定',        color: '#4e4e4e', bg: '#f5f2ef' },
  { key: 'txn',    label: '交易单据', hint: '订单流转，业务的脉搏',        color: '#1f5aa8', bg: '#eaf1fb' },
  { key: 'wms',    label: '仓储',    hint: '货物的进、存、出',            color: '#b8860b', bg: '#fbf5e4' },
  { key: 'fin',    label: '财务',    hint: '凭证、应收应付、信用与汇率',  color: '#6b46c1', bg: '#f1ebfa' },
  { key: 'crm',    label: 'CRM',     hint: '客户关系与项目跟踪',          color: '#1f8f3a', bg: '#ebf5ee' },
  { key: 'sys',    label: '系统',    hint: '只增不改的审计现场',          color: '#777169', bg: '#f5f5f5' },
];

// 状态 —— 淡底 + 深字的克制方案
const STATUS_STYLE = {
  DRAFT:            { bg: '#f5f2ef', color: '#4e4e4e' },
  PENDING_APPROVAL: { bg: '#fbf5e4', color: '#b8860b' },
  PENDING:          { bg: '#fbf5e4', color: '#b8860b' },
  PENDING_FINANCE:  { bg: '#fbf5e4', color: '#b8860b' },
  APPROVED:         { bg: '#ebf5ee', color: '#1f8f3a' },
  IN_PROCUREMENT:   { bg: '#eaf1fb', color: '#1f5aa8' },
  ORDERED:          { bg: '#eaf1fb', color: '#1f5aa8' },
  SHIPPED:          { bg: '#e7f3f5', color: '#0e7490' },
  COMPLETED:        { bg: '#f5f5f5', color: '#4e4e4e' },
  CANCELLED:        { bg: '#fdecea', color: '#b42318' },
  RECEIVED:         { bg: '#ebf5ee', color: '#1f8f3a' },
  AVAILABLE:        { bg: '#ebf5ee', color: '#1f8f3a' },
  RESERVED:         { bg: '#fbf5e4', color: '#b8860b' },
  DAMAGED:          { bg: '#fdecea', color: '#b42318' },
  POSTED:           { bg: '#ebf5ee', color: '#1f8f3a' },
  REVERSED:         { bg: '#fdecea', color: '#b42318' },
  ACTIVE:           { bg: '#ebf5ee', color: '#1f8f3a' },
  OPEN:             { bg: '#ebf5ee', color: '#1f8f3a' },
  CLOSED:           { bg: '#f5f5f5', color: '#4e4e4e' },
  AUDITED:          { bg: '#eaf1fb', color: '#1f5aa8' },
  RECONCILED:       { bg: '#e7f3f5', color: '#0e7490' },
  PAID:             { bg: '#ebf5ee', color: '#1f8f3a' },
  OVERDUE:          { bg: '#fdecea', color: '#b42318' },
  BAD_DEBT:         { bg: '#f5f5f5', color: '#1a1a1a' },
};

function StatusPill({ value }) {
  const s = STATUS_STYLE[value] || { bg: '#f5f2ef', color: '#4e4e4e' };
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 10px',
      borderRadius: 4,
      background: s.bg,
      color: s.color,
      fontSize: 12,
      fontWeight: 500,
      letterSpacing: '0.02em',
    }}>
      {value}
    </span>
  );
}

const DOC_TYPE_MAP = {
  sales_inquiry: 'SALES_INQUIRY', quotation: 'QUOTATION',
  sales_order: 'SALES_ORDER', purchase_notice: 'PURCHASE_NOTICE',
  purchase_order: 'PURCHASE_ORDER',
  shipment_request: 'SHIPMENT', voucher: 'VOUCHER',
  goods_receipt: 'GOODS_RECEIPT', sales_return: 'SALES_RETURN', project: 'PROJECT',
  framework_contract: 'FRAMEWORK_CONTRACT',
  accounts_receivable: 'ACCOUNTS_RECEIVABLE',
  accounts_payable: 'ACCOUNTS_PAYABLE',
  advance_receipt: 'ADVANCE_RECEIPT',
  advance_payment: 'ADVANCE_PAYMENT',
  purchase_invoice: 'PURCHASE_INVOICE',
  sales_invoice: 'SALES_INVOICE',
};

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

// ---------- 落地页：表选择 ----------
function DataLanding({ onPick }) {
  const { user } = useAuth();
  const [counts, setCounts] = useState({});
  // allowed_tables: null=全开,数组=受限角色的白名单
  const allowed = user?.allowed_tables;
  const tables = Object.keys(TABLE_META).filter(
    t => allowed == null || allowed.includes(t)
  );

  useEffect(() => {
    (async () => {
      const results = await Promise.allSettled(
        tables.map(t => aggregate(t, 'id', 'COUNT'))
      );
      const map = {};
      results.forEach((r, i) => {
        map[tables[i]] = r.status === 'fulfilled' ? (r.value.data.value ?? 0) : null;
      });
      setCounts(map);
    })();
  }, []);

  return (
    <div>
      {/* Hero */}
      <div style={{ marginBottom: 32 }}>
        <h2 style={{
          fontSize: 28,
          fontWeight: 300,
          letterSpacing: '-0.01em',
          color: '#000',
          margin: 0,
          lineHeight: 1.15,
        }}>
          数据
        </h2>
        <div style={{ color: '#777169', marginTop: 6, fontSize: 13, letterSpacing: '0.01em' }}>
          一群人按规则操作的一张共享表格 · 选一张看看
        </div>
      </div>

      {CATEGORIES.map(cat => {
        const items = tables.filter(t => TABLE_META[t].cat === cat.key);
        if (items.length === 0) return null;
        return (
          <div key={cat.key} style={{ marginBottom: 32 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 14 }}>
              <span style={{
                fontSize: 12, fontWeight: 500, color: cat.color,
                padding: '3px 10px', background: cat.bg, borderRadius: 4,
                letterSpacing: '0.02em',
              }}>
                {cat.label}
              </span>
              <span style={{ fontSize: 12, color: '#777169', letterSpacing: '0.01em' }}>{cat.hint}</span>
            </div>
            <Row gutter={[16, 16]}>
              {items.map(t => {
                const meta = TABLE_META[t];
                const c = counts[t];
                return (
                  <Col xs={24} sm={12} md={8} lg={6} key={t}>
                    <Card
                      hoverable
                      onClick={() => onPick(t)}
                      style={{
                        borderRadius: 16,
                        cursor: 'pointer',
                        height: '100%',
                        boxShadow: CARD_SHADOW,
                        border: 'none',
                      }}
                      styles={{ body: { padding: 18 } }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
                        <div style={{
                          width: 36, height: 36, borderRadius: 10,
                          background: cat.bg, color: cat.color,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 16,
                        }}>
                          {meta.icon}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 15, fontWeight: 500, color: '#000', letterSpacing: '0.01em' }}>
                            {meta.cn}
                          </div>
                          <div style={{ fontSize: 11, color: '#bfbbb5', fontFamily: 'ui-monospace, monospace' }}>
                            {t}
                          </div>
                        </div>
                      </div>
                      <div style={{
                        fontSize: 12,
                        color: '#777169',
                        minHeight: 32,
                        lineHeight: '16px',
                        letterSpacing: '0.01em',
                      }}>
                        {meta.desc}
                      </div>
                      <div style={{
                        marginTop: 14, paddingTop: 12,
                        borderTop: '1px solid rgba(0,0,0,0.05)',
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      }}>
                        <span style={{ fontSize: 12, color: '#4e4e4e' }}>
                          {c == null
                            ? <span style={{ color: '#bfbbb5' }}>—</span>
                            : <><strong style={{ fontWeight: 500 }}>{c.toLocaleString()}</strong>
                                <span style={{ color: '#777169' }}> 条</span></>}
                        </span>
                        <ArrowRightOutlined style={{ color: '#777169', fontSize: 12 }} />
                      </div>
                    </Card>
                  </Col>
                );
              })}
            </Row>
          </div>
        );
      })}
    </div>
  );
}

// ---------- 表视图：Excel 风浏览 ----------
function exportCsv(filename, rows, cols) {
  if (!rows.length) return;
  const headers = cols.map(c => c.dataIndex);
  const escape = v => {
    if (v == null) return '';
    const s = typeof v === 'object' ? JSON.stringify(v) : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = [
    headers.join(','),
    ...rows.map(r => headers.map(h => escape(r[h])).join(',')),
  ].join('\n');
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `${filename}.csv`; a.click();
  URL.revokeObjectURL(url);
}

function DataTableView({ table, onBack }) {
  const navigate = useNavigate();
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [detailRow, setDetailRow] = useState(null);
  const [density, setDensity] = useState('small');
  const [hiddenCols, setHiddenCols] = useState([]);

  const meta = TABLE_META[table] || { cn: table, desc: '', cat: 'sys' };
  const cat = CATEGORIES.find(c => c.key === meta.cat) || CATEGORIES[5];

  const load = async (s) => {
    setLoading(true);
    try {
      const { data: res } = await query(table, { search: s ?? search, limit: 200 });
      setData(res.data || []);
      setTotal(res.total || 0);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { setSearch(''); setHiddenCols([]); load(''); /* eslint-disable-line */ }, [table]);

  // 自动列定义
  const allCols = useMemo(() => {
    if (!data.length) return [];
    const keys = Object.keys(data[0]).filter(k => !['created_by_id', 'updated_by_id'].includes(k));

    return keys.map((k, idx) => {
      // 状态列：自动出筛选项
      let filters, onFilter;
      if (k === 'status') {
        const uniq = [...new Set(data.map(r => r[k]).filter(Boolean))];
        filters = uniq.map(v => ({ text: v, value: v }));
        onFilter = (v, r) => r[k] === v;
      }

      // 数字排序
      const sample = data.find(r => r[k] != null)?.[k];
      const isNum = typeof sample === 'number';
      const sorter = isNum
        ? (a, b) => (a[k] ?? 0) - (b[k] ?? 0)
        : (a, b) => String(a[k] ?? '').localeCompare(String(b[k] ?? ''));

      return {
        title: k,
        dataIndex: k,
        key: k,
        ellipsis: true,
        width: k === 'id' ? 70 : 140,
        fixed: idx === 0 ? 'left' : undefined,
        sorter,
        filters, onFilter,
        align: isNum && k !== 'id' ? 'right' : undefined,
        render: (v) => {
          if (v == null) return <span style={{ color: '#bfbbb5' }}>—</span>;
          if (k === 'status') return <StatusPill value={v} />;
          if (typeof v === 'number' && (k.includes('amount') || k.includes('price') ||
              k.includes('cost') || k.includes('quantity') || k.includes('total'))) {
            return Number(v).toLocaleString();
          }
          if (typeof v === 'object') return <span style={{ color: '#777169' }}>{JSON.stringify(v).slice(0, 60)}</span>;
          if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return v.slice(0, 19).replace('T', ' ');
          return String(v);
        },
      };
    });
  }, [data]);

  // 应用列显隐
  const visibleCols = useMemo(() => {
    const cols = allCols.filter(c => !hiddenCols.includes(c.key));
    // 操作列
    const docType = DOC_TYPE_MAP[table] || table.toUpperCase();
    const hasStatus = Object.prototype.hasOwnProperty.call(data[0] || {}, 'status');
    if (hasStatus) {
      cols.push({
        title: '操作', key: '_action', width: 80, fixed: 'right',
        render: (_, r) => (
          <Button type="link" size="small" icon={<HistoryOutlined />}
            onClick={(e) => { e.stopPropagation(); navigate(`/history/${docType}/${r.id}`); }}>
            历史
          </Button>
        ),
      });
    }
    return cols;
  }, [allCols, hiddenCols, data, table, navigate]);

  const colSettings = (
    <div style={{ maxHeight: 360, overflow: 'auto', minWidth: 180 }}>
      {allCols.map(c => (
        <div key={c.key} style={{ padding: '4px 0' }}>
          <Checkbox
            checked={!hiddenCols.includes(c.key)}
            onChange={e => {
              setHiddenCols(prev => e.target.checked
                ? prev.filter(k => k !== c.key)
                : [...prev, c.key]);
            }}
          >
            {c.key}
          </Checkbox>
        </div>
      ))}
    </div>
  );

  return (
    <div>
      {/* 面包屑 + 标题 */}
      <Breadcrumb
        style={{ marginBottom: 12 }}
        items={[
          { title: <a onClick={onBack} style={{ color: '#4e4e4e' }}><HomeOutlined /> 数据</a> },
          { title: (
            <span style={{ color: '#000' }}>
              <span style={{
                display: 'inline-block',
                padding: '1px 8px',
                marginRight: 8,
                fontSize: 11,
                fontWeight: 500,
                background: cat.bg,
                color: cat.color,
                borderRadius: 4,
                letterSpacing: '0.02em',
              }}>
                {cat.label}
              </span>
              {meta.cn}
            </span>
          ) },
        ]}
      />
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 16, flexWrap: 'wrap', gap: 12,
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 12,
              background: cat.bg, color: cat.color,
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18,
            }}>{meta.icon}</div>
            <div>
              <div style={{ fontSize: 22, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', lineHeight: 1.15 }}>
                {meta.cn}
              </div>
              <div style={{ fontSize: 12, color: '#bfbbb5', fontFamily: 'ui-monospace, monospace', marginTop: 2 }}>
                {table} · {total.toLocaleString()} 条
              </div>
            </div>
          </div>
        </div>
        <Space wrap>
          <Input.Search
            placeholder="搜索…" style={{ width: 240 }} allowClear value={search}
            onChange={e => setSearch(e.target.value)}
            onSearch={v => { setSearch(v); load(v); }}
          />
          <Tooltip title="刷新">
            <Button icon={<ReloadOutlined />} onClick={() => load()} />
          </Tooltip>
          <Tooltip title="行高">
            <Segmented
              size="middle"
              value={density}
              onChange={setDensity}
              options={[
                { label: '紧凑', value: 'small' },
                { label: '默认', value: 'middle' },
                { label: '宽松', value: 'large' },
              ]}
            />
          </Tooltip>
          <Popover content={colSettings} title="显示列" trigger="click" placement="bottomRight">
            <Tooltip title="列设置"><Button icon={<SettingOutlined />} /></Tooltip>
          </Popover>
          <Tooltip title="导出 CSV">
            <Button icon={<DownloadOutlined />} onClick={() => exportCsv(table, data, allCols)} />
          </Tooltip>
        </Space>
      </div>

      <Card
        style={{ borderRadius: 16, boxShadow: CARD_SHADOW, border: 'none' }}
        styles={{ body: { padding: 0 } }}
      >
        <Table
          dataSource={data}
          columns={visibleCols}
          rowKey="id"
          loading={loading}
          size={density}
          sticky
          scroll={{ x: 'max-content', y: 'calc(100vh - 320px)' }}
          pagination={{ pageSize: 50, showSizeChanger: true, showTotal: t => `共 ${t} 条` }}
          onRow={r => ({ onClick: () => setDetailRow(r), style: { cursor: 'pointer' } })}
          locale={{ emptyText: <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
        />
      </Card>

      <Drawer
        title={(
          <span>
            <span style={{
              display: 'inline-block', padding: '1px 8px', marginRight: 8,
              fontSize: 11, fontWeight: 500,
              background: cat.bg, color: cat.color,
              borderRadius: 4, letterSpacing: '0.02em',
            }}>{cat.label}</span>
            <span style={{ fontWeight: 500, letterSpacing: '0.01em' }}>{meta.cn} 详情</span>
          </span>
        )}
        open={!!detailRow}
        onClose={() => setDetailRow(null)}
        width={520}
      >
        {detailRow && Object.entries(detailRow).map(([k, v]) => (
          <div key={k} style={{
            display: 'flex', padding: '10px 0',
            borderBottom: '1px solid rgba(0,0,0,0.05)',
          }}>
            <span style={{ width: 160, color: '#777169', flexShrink: 0, fontSize: 13, letterSpacing: '0.01em' }}>{k}</span>
            <span style={{ wordBreak: 'break-all', fontSize: 13, color: '#000' }}>
              {v == null
                ? <span style={{ color: '#bfbbb5' }}>—</span>
                : typeof v === 'object'
                  ? <pre style={{ margin: 0, fontSize: 12, fontFamily: 'ui-monospace, monospace' }}>{JSON.stringify(v, null, 2)}</pre>
                  : String(v)}
            </span>
          </div>
        ))}
      </Drawer>
    </div>
  );
}

// ---------- 入口 ----------
export default function DataExplorer() {
  const { table } = useParams();
  const navigate = useNavigate();

  if (!table) {
    return <DataLanding onPick={t => navigate(`/data/${t}`)} />;
  }
  return <DataTableView table={table} onBack={() => navigate('/data')} />;
}
