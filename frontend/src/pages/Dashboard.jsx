import { useEffect, useState } from 'react';
import { Card, Col, Row, Statistic, Table, Tag, Spin, Progress } from 'antd';
import { ShoppingCartOutlined, ShoppingOutlined, DollarOutlined, InboxOutlined } from '@ant-design/icons';
import { aggregate, query } from '../api';
import { useAuth } from '../auth';

const FULL_ACCESS_ROLES = new Set(['BOSS', 'FINANCE', 'OPERATIONS', 'ADMIN']);

// 状态中文标签 —— 与流程图一致
const STATUS_LABEL = {
  DRAFT: '草稿',
  PENDING_APPROVAL: '待审批',
  APPROVED: '已批准',
  IN_PROCUREMENT: '采购中',
  SHIPPED: '已发货',
  COMPLETED: '已完成',
  CANCELLED: '已取消',
  ORDERED: '已下单',
  PENDING: '待处理',
  SIMULATED_QUOTE: '模拟报价',
  SHIPPING_NOTICE: '发货通知',
  INVOICE: '已开票',
  AR_MANAGED: '应收管理',
};

// 降饱和状态色 —— 淡底 + 深字，克制可辨
const STATUS_STYLE = {
  DRAFT:            { bg: '#f5f2ef', color: '#4e4e4e' },
  PENDING_APPROVAL: { bg: '#fbf5e4', color: '#b8860b' },
  APPROVED:         { bg: '#ebf5ee', color: '#1f8f3a' },
  IN_PROCUREMENT:   { bg: '#eaf1fb', color: '#1f5aa8' },
  SHIPPED:          { bg: '#e7f3f5', color: '#0e7490' },
  COMPLETED:        { bg: '#f5f5f5', color: '#4e4e4e' },
  CANCELLED:        { bg: '#fdecea', color: '#b42318' },
  ORDERED:          { bg: '#eaf1fb', color: '#1f5aa8' },
  PENDING:          { bg: '#fbf5e4', color: '#b8860b' },
};

function StatusTag({ value }) {
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

// 统计卡片 —— 图标单色 + 暖石底圆角方块
function Stat({ title, value, icon, precision }) {
  return (
    <Card
      size="small"
      style={{
        borderRadius: 16,
        boxShadow: 'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px',
      }}
      styles={{ body: { padding: 20 } }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{
          width: 40, height: 40, borderRadius: 12,
          background: '#f5f2ef', color: '#4e4e4e',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 18,
        }}>{icon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Statistic
            title={<span style={{ fontSize: 12, color: '#777169', letterSpacing: '0.02em' }}>{title}</span>}
            value={value ?? 0}
            precision={precision}
            valueStyle={{
              fontSize: 24,
              fontWeight: 300,
              letterSpacing: '-0.01em',
              color: '#000',
              lineHeight: 1.1,
            }}
          />
        </div>
      </div>
    </Card>
  );
}

// 全公司视角块 —— 仅 BOSS / FINANCE / OPERATIONS / ADMIN 可见
function BossOverview({ companies, soByCompany, poByCompany, soByStatus, poByStatus }) {
  const companyRows = companies.map(c => {
    const soSum = soByCompany.find(x => String(x.group) === String(c.id))?.value || 0;
    const poSum = poByCompany.find(x => String(x.group) === String(c.id))?.value || 0;
    return { id: c.id, name: c.short_name || c.name, soSum, poSum };
  });

  const statusRows = (data) => {
    const total = data.reduce((s, x) => s + x.value, 0) || 1;
    return data
      .filter(x => x.group && x.group !== 'None')
      .map(x => ({ status: x.group, count: x.value, pct: x.value / total * 100 }))
      .sort((a, b) => b.count - a.count);
  };

  const cardStyle = {
    borderRadius: 16,
    boxShadow: 'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px',
  };

  const StatusBars = ({ rows }) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {rows.length === 0 && <div style={{ color: '#777169', fontSize: 13 }}>暂无数据</div>}
      {rows.map(r => {
        const s = STATUS_STYLE[r.status] || { bg: '#f5f2ef', color: '#4e4e4e' };
        return (
          <div key={r.status}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
              <span style={{ color: s.color, fontWeight: 500 }}>{STATUS_LABEL[r.status] || r.status}</span>
              <span style={{ color: '#777169' }}>{r.count}</span>
            </div>
            <Progress percent={r.pct} showInfo={false} strokeColor={s.color} trailColor="#f5f2ef" size="small" />
          </div>
        );
      })}
    </div>
  );

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ fontSize: 14, fontWeight: 500, color: '#777169', letterSpacing: '0.04em', marginBottom: 12, textTransform: 'uppercase' }}>
        全公司视角
      </div>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title={<span style={{ fontSize: 14, fontWeight: 500 }}>各主体业务分布</span>} size="small" style={cardStyle}>
            <Table
              dataSource={companyRows}
              rowKey="id"
              size="small"
              pagination={false}
              columns={[
                { title: '法人主体', dataIndex: 'name' },
                { title: '销售总额', dataIndex: 'soSum', align: 'right', render: v => Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }) },
                { title: '采购总额', dataIndex: 'poSum', align: 'right', render: v => Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }) },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={6}>
          <Card title={<span style={{ fontSize: 14, fontWeight: 500 }}>销售流程进度</span>} size="small" style={cardStyle}>
            <StatusBars rows={statusRows(soByStatus)} />
          </Card>
        </Col>
        <Col xs={24} lg={6}>
          <Card title={<span style={{ fontSize: 14, fontWeight: 500 }}>采购流程进度</span>} size="small" style={cardStyle}>
            <StatusBars rows={statusRows(poByStatus)} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState({});
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [boss, setBoss] = useState(null);
  const { user } = useAuth();
  const isBoss = user && FULL_ACCESS_ROLES.has(user.role);

  useEffect(() => {
    (async () => {
      try {
        const [soCount, soSum, poCount, invCount, recentOrders] = await Promise.all([
          aggregate('sales_order', 'id', 'COUNT'),
          aggregate('sales_order', 'total_amount', 'SUM'),
          aggregate('purchase_order', 'id', 'COUNT'),
          aggregate('inventory', 'quantity', 'SUM'),
          query('sales_order', { order_by: '-id', limit: 5 }),
        ]);
        setStats({
          soCount: soCount.data.value,
          soTotal: soSum.data.value,
          poCount: poCount.data.value,
          invQty: invCount.data.value,
        });
        setOrders(recentOrders.data.data);

        if (isBoss) {
          const [companies, soByCompany, poByCompany, soByStatus, poByStatus] = await Promise.all([
            query('company', { order_by: 'id', limit: 50 }),
            aggregate('sales_order', 'total_amount', 'SUM', { group_by: 'company_id' }),
            aggregate('purchase_order', 'total_amount', 'SUM', { group_by: 'company_id' }),
            aggregate('sales_order', 'id', 'COUNT', { group_by: 'status' }),
            aggregate('purchase_order', 'id', 'COUNT', { group_by: 'status' }),
          ]);
          setBoss({
            companies: companies.data.data,
            soByCompany: soByCompany.data.data,
            poByCompany: poByCompany.data.data,
            soByStatus: soByStatus.data.data,
            poByStatus: poByStatus.data.data,
          });
        }
      } catch (e) { console.error(e); }
      setLoading(false);
    })();
  }, [isBoss]);

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>;

  return (
    <div>
      {/* Hero —— Inter 300 whisper-thin */}
      <div style={{ marginBottom: 28 }}>
        <h2 style={{
          fontSize: 28,
          fontWeight: 300,
          letterSpacing: '-0.01em',
          color: '#000',
          margin: 0,
          lineHeight: 1.15,
        }}>
          {user?.full_name}
          <span style={{ color: '#777169' }}>，欢迎回来</span>
        </h2>
        <div style={{ marginTop: 6, color: '#777169', fontSize: 13, letterSpacing: '0.01em' }}>
          {isBoss ? '集团业务一览' : '今日业务一览'}
        </div>
      </div>

      {isBoss && boss && <BossOverview {...boss} />}

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} lg={6}>
          <Stat title="销售订单" value={stats.soCount} icon={<ShoppingCartOutlined />} />
        </Col>
        <Col xs={12} lg={6}>
          <Stat title="销售总额" value={stats.soTotal} icon={<DollarOutlined />} precision={0} />
        </Col>
        <Col xs={12} lg={6}>
          <Stat title="采购订单" value={stats.poCount} icon={<ShoppingOutlined />} />
        </Col>
        <Col xs={12} lg={6}>
          <Stat title="库存总量" value={stats.invQty} icon={<InboxOutlined />} precision={0} />
        </Col>
      </Row>

      <Card
        title={<span style={{ fontSize: 16, fontWeight: 500, letterSpacing: '0.01em' }}>最近销售订单</span>}
        size="small"
        style={{
          borderRadius: 16,
          boxShadow: 'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px',
        }}
      >
        <Table
          dataSource={orders}
          rowKey="id"
          size="small"
          pagination={false}
          columns={[
            { title: '订单号', dataIndex: 'order_number' },
            { title: '客户ID', dataIndex: 'customer_id', width: 100 },
            { title: '状态', dataIndex: 'status', width: 140, render: v => <StatusTag value={v} /> },
            { title: '金额', dataIndex: 'total_amount', align: 'right', render: v => v != null ? Number(v).toLocaleString() : '—' },
            { title: '日期', dataIndex: 'created_at', width: 130, render: v => v ? v.slice(0, 10) : '—' },
          ]}
        />
      </Card>
    </div>
  );
}
