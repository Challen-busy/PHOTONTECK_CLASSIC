import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Empty, Input, Select, Space, Spin, Tag, Tooltip } from 'antd';
import { HistoryOutlined, ReloadOutlined } from '@ant-design/icons';
import { getOrderChains } from '../api';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

const GROUP_STYLES = {
  crm: { color: '#1f8f3a', bg: '#ebf5ee' },
  erp_sales: { color: '#1f5aa8', bg: '#eaf1fb' },
  erp_purchase: { color: '#6b46c1', bg: '#f0ebf8' },
  wms: { color: '#b8860b', bg: '#fbf5e4' },
  finance: { color: '#8a4b16', bg: '#f7eee7' },
};

const DOC_LABELS = {
  SALES_INQUIRY: '客户询价',
  QUOTATION: '报价单',
  SALES_ORDER: '销售订单',
  PURCHASE_NOTICE: '采购通知',
  PURCHASE_ORDER: '采购订单',
  GOODS_RECEIPT: '采购收货',
  SHIPMENT: '发货单',
  SALES_RETURN: '销售退货',
  ADVANCE_RECEIPT: '预收单',
  ADVANCE_PAYMENT: '预付单',
  PURCHASE_INVOICE: '采购发票',
  SALES_INVOICE: '销售发票',
  ACCOUNTS_PAYABLE: '应付',
  ACCOUNTS_RECEIVABLE: '应收',
};

const DEFAULT_STAGE_OPTIONS = [
  { key: 'all', name: '全部阶段' },
  { key: 'crm', name: 'CRM 售前' },
  { key: 'erp_sales', name: 'ERP 销售' },
  { key: 'erp_purchase', name: 'ERP 采购' },
  { key: 'wms', name: 'WMS 仓储' },
  { key: 'finance', name: '财务勾稽' },
  { key: 'completed', name: '已完成' },
  { key: 'exception', name: '异常/取消' },
];

function statusColor(status = '') {
  const s = String(status);
  if (['COMPLETED', 'DONE', 'CLOSED', 'PAID', 'STOCKED_IN', 'SALES_OUTBOUND', 'AR_CREATED', 'AP_CREATED'].includes(s)) return 'green';
  if (['DRAFT', 'PENDING'].includes(s)) return 'default';
  if (s.includes('REJECT') || s.includes('CANCEL')) return 'red';
  if (s.includes('WAIT') || s.includes('REVIEW') || s.includes('MATCH')) return 'gold';
  return 'blue';
}

function formatAmount(doc) {
  if (doc.amount == null) return '';
  const amount = Number(doc.amount);
  if (!Number.isFinite(amount)) return '';
  return `${amount.toLocaleString()} ${doc.currency || ''}`.trim();
}

function DocItem({ doc }) {
  const navigate = useNavigate();
  const title = DOC_LABELS[doc.doc_type] || doc.doc_type || doc.table;
  const amount = formatAmount(doc);
  return (
    <div style={{
      border: '1px solid rgba(0,0,0,0.07)',
      borderRadius: 8,
      padding: '9px 10px',
      background: '#fff',
      minHeight: 72,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: '#000', fontSize: 13, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {title}
          </div>
          <div style={{ color: '#777169', fontSize: 12, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {doc.number || `#${doc.id}`}
          </div>
        </div>
        <Tooltip title="查看操作历史">
          <Button
            type="text"
            size="small"
            icon={<HistoryOutlined />}
            onClick={() => navigate(`/history/${doc.doc_type}/${doc.id}`)}
            style={{ flexShrink: 0 }}
          />
        </Tooltip>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginTop: 8 }}>
        <Tag color={statusColor(doc.status)} style={{ margin: 0, maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {doc.status_name || doc.status || '无状态'}
        </Tag>
        {amount && (
          <span style={{ color: '#4e4e4e', fontSize: 12, whiteSpace: 'nowrap' }}>
            {amount}
          </span>
        )}
      </div>
    </div>
  );
}

function GroupColumn({ group }) {
  const style = GROUP_STYLES[group.key] || { color: '#4e4e4e', bg: '#f6f6f6' };
  const docs = group.docs || [];
  return (
    <div style={{
      minWidth: 210,
      flex: '1 1 220px',
      border: '1px solid rgba(0,0,0,0.06)',
      borderRadius: 8,
      background: '#fafafa',
      padding: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
        <Tag style={{ margin: 0, border: 'none', background: style.bg, color: style.color, fontWeight: 500 }}>
          {group.name}
        </Tag>
        <span style={{ color: '#777169', fontSize: 12 }}>{docs.length} 单</span>
      </div>
      {!group.visible && (
        <div style={{ color: '#9b958d', fontSize: 12, padding: '12px 2px' }}>当前角色无权限</div>
      )}
      {group.visible && docs.length === 0 && (
        <div style={{ color: '#9b958d', fontSize: 12, padding: '12px 2px' }}>未生成</div>
      )}
      <div style={{ display: 'grid', gap: 8 }}>
        {docs.map(doc => <DocItem key={`${doc.table}-${doc.id}`} doc={doc} />)}
      </div>
    </div>
  );
}

function OrderCard({ item }) {
  const summary = item.summary || {};
  const amount = formatAmount(summary);
  const rootLabel = summary.root_label || DOC_LABELS[summary.root_doc_type] || DOC_LABELS[summary.doc_type] || '单据';
  const rootNumber = summary.root_number || summary.order_number || summary.number || `#${summary.root_id || summary.sales_order_id || summary.id}`;
  const stageName = summary.stage_name || '未分阶段';
  return (
    <Card
      style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}
      styles={{ body: { padding: 18 } }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 240, flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <h3 style={{ margin: 0, fontSize: 18, lineHeight: '24px', fontWeight: 500, color: '#000', letterSpacing: 0 }}>
              {rootLabel}：{rootNumber}
            </h3>
            <Tag style={{ margin: 0 }}>
              {stageName}
            </Tag>
            <Tag color={statusColor(summary.status)} style={{ margin: 0 }}>
              {summary.status_name || summary.status || '无状态'}
            </Tag>
          </div>
          <div style={{ color: '#777169', fontSize: 12, marginTop: 6, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span>客户：{summary.customer_name || '不可见/未填'}</span>
            {summary.sales_order_id ? (
              <span>客户 PO：{summary.customer_po_number || '未填'}</span>
            ) : (
              <span>尚未生成销售订单</span>
            )}
          </div>
        </div>
        {amount && (
          <div style={{ textAlign: 'right', minWidth: 120 }}>
            <div style={{ color: '#777169', fontSize: 12 }}>金额</div>
            <div style={{ color: '#000', fontSize: 17, fontWeight: 500 }}>{amount}</div>
          </div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'stretch' }}>
        {(item.groups || []).map(group => <GroupColumn key={group.key} group={group} />)}
      </div>
    </Card>
  );
}

export default function OrderChainMonitor() {
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState('');
  const [pendingSearch, setPendingSearch] = useState('');
  const [stage, setStage] = useState('all');
  const [stageOptions, setStageOptions] = useState(DEFAULT_STAGE_OPTIONS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async (value = '', selectedStage = 'all') => {
    setLoading(true);
    setError('');
    try {
      const { data } = await getOrderChains({ search: value, stage: selectedStage, limit: 50 });
      setItems(data.items || []);
      if (data.stage_options?.length) setStageOptions(data.stage_options);
    } catch (err) {
      setError(err.response?.data?.detail || '链路数据加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load('', 'all');
  }, [load]);

  const totalDocs = useMemo(
    () => items.reduce((sum, item) => sum + (item.groups || []).reduce((n, group) => n + (group.docs || []).length, 0), 0),
    [items],
  );

  const handleSearch = (value) => {
    const next = value.trim();
    setSearch(next);
    load(next, stage);
  };

  const handleStageChange = (next) => {
    setStage(next);
    load(search, next);
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 20, flexWrap: 'wrap' }}>
        <div>
          <Tag style={{ border: 'none', background: '#f0ebf8', color: '#6b46c1', fontWeight: 500, marginBottom: 10 }}>
            订单链路
          </Tag>
          <h2 style={{ margin: 0, color: '#000', fontSize: 28, fontWeight: 300, lineHeight: 1.15, letterSpacing: 0 }}>
            单据链路监控
          </h2>
          <div style={{ color: '#777169', fontSize: 13, marginTop: 8 }}>
            {items.length} 条链路，{totalDocs} 张可见关联单据
          </div>
        </div>
        <Space wrap align="start">
          <Select
            value={stage}
            onChange={handleStageChange}
            options={stageOptions.map(opt => ({ value: opt.key, label: opt.name }))}
            style={{ width: 150 }}
          />
          <Input.Search
            allowClear
            placeholder="搜索任意单号/客户PO"
            value={pendingSearch}
            onChange={e => setPendingSearch(e.target.value)}
            onSearch={handleSearch}
            style={{ width: 300, maxWidth: 'calc(100vw - 80px)' }}
          />
          <Button icon={<ReloadOutlined />} onClick={() => load(search, stage)} loading={loading}>
            刷新
          </Button>
        </Space>
      </div>

      {error && (
        <Card style={{ borderRadius: 8, marginBottom: 16, borderColor: '#ffccc7' }} styles={{ body: { padding: 14 } }}>
          <span style={{ color: '#cf1322' }}>{error}</span>
        </Card>
      )}

      {loading ? (
        <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />
      ) : items.length === 0 ? (
        <Card style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
          <Empty description="没有找到可见的单据链路" />
        </Card>
      ) : (
        <div style={{ display: 'grid', gap: 14 }}>
          {items.map(item => (
            <OrderCard
              key={`${item.summary.root_table || 'sales_order'}-${item.summary.root_id || item.summary.sales_order_id}`}
              item={item}
            />
          ))}
        </div>
      )}
    </div>
  );
}
