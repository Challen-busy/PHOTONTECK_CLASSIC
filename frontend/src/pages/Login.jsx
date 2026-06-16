import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Form, Input, Button, App } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { useAuth } from '../auth';

export default function Login() {
  const [loading, setLoading] = useState(false);
  const { message } = App.useApp();
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
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
      background:
        'radial-gradient(1200px 600px at 50% -10%, #f5f2ef 0%, #ffffff 55%), #ffffff',
    }}>
      <div style={{
        width: 400,
        background: '#ffffff',
        borderRadius: 24,
        padding: '40px 36px 32px',
        boxShadow:
          'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 12px 40px',
      }}>
        {/* Title —— Inter 300 whisper-thin */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{
            fontSize: 32,
            fontWeight: 300,
            letterSpacing: '0.14em',
            color: '#000',
            marginBottom: 6,
            lineHeight: 1.1,
          }}>
            PHOTONTECK
          </div>
          <div style={{
            fontSize: 13,
            color: '#777169',
            letterSpacing: '0.02em',
          }}>
            业务运营平台
          </div>
        </div>

        <Form onFinish={onFinish} size="large" layout="vertical" requiredMark={false}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input
              prefix={<UserOutlined style={{ color: '#777169' }} />}
              placeholder="用户名"
              style={{ borderRadius: 12, height: 44 }}
            />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password
              prefix={<LockOutlined style={{ color: '#777169' }} />}
              placeholder="密码"
              style={{ borderRadius: 12, height: 44 }}
            />
          </Form.Item>
          <Form.Item style={{ marginTop: 8, marginBottom: 20 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              style={{
                height: 44,
                borderRadius: 9999,
                fontWeight: 500,
                letterSpacing: '0.02em',
              }}
            >
              登录
            </Button>
          </Form.Item>
        </Form>

        {/* Demo accounts —— 极淡暖石底 */}
        <div style={{
          textAlign: 'center',
          color: '#777169',
          fontSize: 12,
          background: 'rgba(245, 242, 239, 0.6)',
          border: '1px solid rgba(0, 0, 0, 0.05)',
          borderRadius: 10,
          padding: '10px 12px',
          letterSpacing: '0.01em',
        }}>
          jerry / demo1234 &middot; sa_li / demo1234 &middot; pa_chen / demo1234
        </div>
      </div>
    </div>
  );
}
