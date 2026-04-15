import { useEffect, useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout as AntLayout, Menu, Avatar, Dropdown, Tag, Badge } from 'antd';
import {
  DashboardOutlined, TableOutlined, ThunderboltOutlined,
  RobotOutlined, LogoutOutlined, UserOutlined,
  MenuFoldOutlined, MenuUnfoldOutlined, SettingOutlined, ApartmentOutlined,
  CheckSquareOutlined,
} from '@ant-design/icons';
import { useAuth } from '../auth';
import { getMyTodos } from '../api';

const { Header, Sider, Content } = AntLayout;

const buildMenuItems = (todoCount) => [
  { key: '/', icon: <DashboardOutlined />, label: '看板' },
  {
    key: '/todos',
    icon: <CheckSquareOutlined />,
    label: <span>待办 {todoCount > 0 && <Badge count={todoCount} size="small" offset={[6, -2]} style={{ backgroundColor: '#faad14' }} />}</span>,
  },
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
  const [todoCount, setTodoCount] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  useEffect(() => {
    let alive = true;
    const load = () => getMyTodos().then(r => { if (alive) setTodoCount((r.data || []).length); }).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => { alive = false; clearInterval(t); };
  }, [location.pathname]);

  const userMenu = {
    items: [
      { key: 'role', label: <Tag color={roleColors[user?.role]}>{user?.role}</Tag>, disabled: true },
      { type: 'divider' },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出', danger: true },
    ],
    onClick: ({ key }) => { if (key === 'logout') { logout(); navigate('/login'); } },
  };

  const siderWidth = collapsed ? 80 : 200;

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider collapsed={collapsed} trigger={null} collapsible
        theme="dark" width={200}
        style={{ background: '#1a1a2e', position: 'fixed', top: 0, left: 0, bottom: 0, height: '100vh', overflow: 'auto', zIndex: 10 }}>
        <div style={{ height: 56, display: 'flex', alignItems: 'center', justifyContent: 'center',
          borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
          <span style={{ color: '#fff', fontSize: collapsed ? 14 : 17, fontWeight: 700, letterSpacing: 1 }}>
            {collapsed ? 'PT' : 'PHOTONTECK'}
          </span>
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[location.pathname]}
          items={buildMenuItems(todoCount).filter(i => !i.adminOnly || user?.is_admin).map(({ adminOnly, ...item }) => item)}
          onClick={({ key }) => navigate(key)}
          style={{ background: 'transparent', borderRight: 0 }} />
      </Sider>
      <AntLayout style={{ marginLeft: siderWidth, transition: 'margin-left 0.2s' }}>
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
