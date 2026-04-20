import { useEffect, useState } from 'react';
import { Card, Col, Row, Statistic, Table, Tag, Spin } from 'antd';
import { ShoppingCartOutlined, ShoppingOutlined, DollarOutlined, InboxOutlined } from '@ant-design/icons';
import { aggregate, query } from '../api';
import { useAuth } from '../auth';

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

export default function Dashboard() {
  const [stats, setStats] = useState({});
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const { user } = useAuth();

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
      } catch (e) { console.error(e); }
      setLoading(false);
    })();
  }, []);

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
          今日业务一览
        </div>
      </div>

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
            { title: '日期', dataIndex: 'order_date', width: 130 },
          ]}
        />
      </Card>
    </div>
  );
}
