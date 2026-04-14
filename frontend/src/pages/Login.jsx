import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Form, Input, Button, Card, message, Typography } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { useAuth } from '../auth';

export default function Login() {
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const onFinish = async ({ username, password }) => {
    setLoading(true);
    const ok = await login(username, password);
    setLoading(false);
    if (ok) { message.success('登录成功'); navigate('/'); }
    else message.error('用户名或密码错误');
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)' }}>
      <Card style={{ width: 380, borderRadius: 16, boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }} bordered={false}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <Typography.Title level={3} style={{ margin: 0, color: '#1a1a2e' }}>PHOTONTECK</Typography.Title>
          <Typography.Text type="secondary">业务运营平台</Typography.Text>
        </div>
        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block style={{ height: 42 }}>登录</Button>
          </Form.Item>
        </Form>
        <div style={{ textAlign: 'center', color: '#999', fontSize: 12 }}>
          jerry / demo1234 &middot; sa_li / demo1234 &middot; pa_chen / demo1234
        </div>
      </Card>
    </div>
  );
}
