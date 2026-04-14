import { useEffect, useState } from 'react';
import { Card, Col, Row, Statistic, Table, Tag, Spin } from 'antd';
import { ShoppingCartOutlined, ShoppingOutlined, DollarOutlined, InboxOutlined } from '@ant-design/icons';
import { aggregate, query } from '../api';
import { useAuth } from '../auth';

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

  const statusColors = { DRAFT: 'default', PENDING_APPROVAL: 'orange', APPROVED: 'green', IN_PROCUREMENT: 'blue', SHIPPED: 'cyan', COMPLETED: 'default', CANCELLED: 'red', ORDERED: 'blue' };

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 600, color: '#1a1a2e', marginBottom: 20 }}>
        {user?.full_name}，欢迎回来
      </h2>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} lg={6}>
          <Card size="small" style={{ borderRadius: 12 }}>
            <Statistic title="销售订单" value={stats.soCount || 0} prefix={<ShoppingCartOutlined style={{ color: '#4dabf7' }} />} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card size="small" style={{ borderRadius: 12 }}>
            <Statistic title="销售总额" value={stats.soTotal || 0} prefix={<DollarOutlined style={{ color: '#51cf66' }} />} precision={0} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card size="small" style={{ borderRadius: 12 }}>
            <Statistic title="采购订单" value={stats.poCount || 0} prefix={<ShoppingOutlined style={{ color: '#ffa94d' }} />} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card size="small" style={{ borderRadius: 12 }}>
            <Statistic title="库存总量" value={stats.invQty || 0} prefix={<InboxOutlined style={{ color: '#845ef7' }} />} precision={0} />
          </Card>
        </Col>
      </Row>

      <Card title="最近销售订单" size="small" style={{ borderRadius: 12 }}>
        <Table dataSource={orders} rowKey="id" size="small" pagination={false} columns={[
          { title: '订单号', dataIndex: 'order_number' },
          { title: '客户ID', dataIndex: 'customer_id' },
          { title: '状态', dataIndex: 'status', render: v => <Tag color={statusColors[v]}>{v}</Tag> },
          { title: '金额', dataIndex: 'total_amount', align: 'right', render: v => v != null ? Number(v).toLocaleString() : '-' },
          { title: '日期', dataIndex: 'order_date' },
        ]} />
      </Card>
    </div>
  );
}
