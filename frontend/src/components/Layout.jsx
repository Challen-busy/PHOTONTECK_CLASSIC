import { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout as AntLayout, Menu, Avatar, Dropdown, Tag } from 'antd';
import {
  DashboardOutlined, TableOutlined, ThunderboltOutlined,
  RobotOutlined, LogoutOutlined, UserOutlined,
  MenuFoldOutlined, MenuUnfoldOutlined, SettingOutlined, ApartmentOutlined,
} from '@ant-design/icons';
import { useAuth } from '../auth';

const { Header, Sider, Content } = AntLayout;

const allMenuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '看板' },
  { key: '/data', icon: <TableOutlined />, label: '数据' },
  { key: '/actions', icon: <ThunderboltOutlined />, label: '流程' },
  { key: '/agent', icon: <RobotOutlined />, label: 'Agent' },
  { key: '/flow-editor', icon: <ApartmentOutlined />, label: '流程管理', adminOnly: true },
  { key: '/admin', icon: <SettingOutlined />, label: '管理', adminOnly: true },
];

const roleColors = {
  BOSS: 'red', OPERATIONS: 'purple', FINANCE: 'gold',
  SALES_ENGINEER: 'blue', SALES_ASSISTANT: 'cyan',
  PRODUCT_MANAGER: 'green', PRODUCT_ASSISTANT: 'lime',
  LOGISTICS: 'orange', ADMIN: 'default',
};

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  const userMenu = {
    items: [
      { key: 'role', label: <Tag color={roleColors[user?.role]}>{user?.role}</Tag>, disabled: true },
      { type: 'divider' },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出', danger: true },
    ],
    onClick: ({ key }) => { if (key === 'logout') { logout(); navigate('/login'); } },
  };

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}
        theme="dark" style={{ background: '#1a1a2e' }} width={200}>
        <div style={{ height: 56, display: 'flex', alignItems: 'center', justifyContent: 'center',
          borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
          <span style={{ color: '#fff', fontSize: collapsed ? 14 : 17, fontWeight: 700, letterSpacing: 1 }}>
            {collapsed ? 'PT' : 'PHOTONTECK'}
          </span>
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[location.pathname]}
          items={allMenuItems.filter(i => !i.adminOnly || user?.is_admin).map(({ adminOnly, ...item }) => item)}
          onClick={({ key }) => navigate(key)}
          style={{ background: 'transparent', borderRight: 0 }} />
      </Sider>
      <AntLayout>
        <Header style={{ background: '#fff', padding: '0 20px', display: 'flex',
          alignItems: 'center', justifyContent: 'space-between',
          boxShadow: '0 1px 4px rgba(0,0,0,0.05)', height: 56 }}>
          <div style={{ cursor: 'pointer', fontSize: 18 }}
            onClick={() => setCollapsed(!collapsed)}>
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </div>
          <Dropdown menu={userMenu} placement="bottomRight">
            <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Avatar size="small" style={{ background: '#1a1a2e' }} icon={<UserOutlined />} />
              <span style={{ fontWeight: 500 }}>{user?.full_name || user?.username}</span>
            </div>
          </Dropdown>
        </Header>
        <Content style={{ margin: 20 }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  );
}
