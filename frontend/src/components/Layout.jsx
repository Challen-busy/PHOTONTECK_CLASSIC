import { useEffect, useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout as AntLayout, Menu, Avatar, Dropdown, Tag, Badge } from 'antd';
import {
  DashboardOutlined, TableOutlined, ThunderboltOutlined,
  RobotOutlined, LogoutOutlined, UserOutlined,
  MenuFoldOutlined, MenuUnfoldOutlined, SettingOutlined, ApartmentOutlined,
  CheckSquareOutlined, TeamOutlined, BankOutlined, InboxOutlined, AuditOutlined,
} from '@ant-design/icons';
import { useAuth } from '../auth';
import { getMyTodos } from '../api';

const { Header, Sider, Content } = AntLayout;

const buildMenuItems = (todoCount) => [
  { key: '/', icon: <DashboardOutlined />, label: '看板' },
  { key: '/crm', icon: <TeamOutlined />, label: 'CRM' },
  { key: '/erp', icon: <BankOutlined />, label: 'ERP' },
  { key: '/wms', icon: <InboxOutlined />, label: 'WMS' },
  { key: '/commands', icon: <AuditOutlined />, label: '命令' },
  { key: '/order-chain', icon: <ApartmentOutlined />, label: '链路' },
  {
    key: '/todos',
    icon: <CheckSquareOutlined />,
    label: (
      <span>
        待办{' '}
        {todoCount > 0 && (
          <Badge count={todoCount} size="small" offset={[6, -2]}
            style={{ backgroundColor: '#b8860b' }} />
        )}
      </span>
    ),
  },
  { key: '/data',        icon: <TableOutlined />,     label: '数据' },
  { key: '/actions',     icon: <ThunderboltOutlined />, label: '流程' },
  { key: '/agent',       icon: <RobotOutlined />,     label: 'Agent' },
  { key: '/flow-editor', icon: <ApartmentOutlined />, label: '流程管理', adminOnly: true },
  { key: '/admin',       icon: <SettingOutlined />,   label: '管理',     adminOnly: true },
];

// 克制的语义色 —— 用于角色徽章（降饱和版）
const roleColors = {
  BOSS: '#b42318', OPERATIONS: '#6b46c1', FINANCE: '#b8860b',
  SALES_ENGINEER: '#1f5aa8', SALES_ASSISTANT: '#0e7490',
  PRODUCT_MANAGER: '#1f8f3a', PRODUCT_ASSISTANT: '#4d7c0f',
  LOGISTICS: '#c2410c', ADMIN: '#4e4e4e',
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
      {
        key: 'role',
        label: (
          <Tag style={{
            background: 'transparent',
            border: `1px solid ${roleColors[user?.role] || '#e5e5e5'}`,
            color: roleColors[user?.role] || '#4e4e4e',
          }}>
            {user?.role}
          </Tag>
        ),
        disabled: true,
      },
      { type: 'divider' },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出', danger: true },
    ],
    onClick: ({ key }) => { if (key === 'logout') { logout(); navigate('/login'); } },
  };

  const siderWidth = collapsed ? 80 : 220;

  return (
    <AntLayout style={{ minHeight: '100vh', background: '#ffffff' }}>
      <Sider
        collapsed={collapsed}
        trigger={null}
        collapsible
        theme="light"
        width={220}
        style={{
          background: '#ffffff',
          position: 'fixed',
          top: 0, left: 0, bottom: 0,
          height: '100vh',
          overflow: 'auto',
          zIndex: 10,
          borderRight: '1px solid rgba(0, 0, 0, 0.05)',
        }}
      >
        {/* Logo —— whisper-thin Inter 300 */}
        <div style={{
          height: 56,
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'flex-start',
          paddingInline: collapsed ? 0 : 20,
          borderBottom: '1px solid rgba(0, 0, 0, 0.05)',
        }}>
          <span style={{
            color: '#000',
            fontSize: collapsed ? 16 : 18,
            fontWeight: 300,
            letterSpacing: collapsed ? '0.05em' : '0.12em',
          }}>
            {collapsed ? 'PT' : 'PHOTONTECK'}
          </span>
        </div>
        <Menu
          theme="light"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={buildMenuItems(todoCount)
            .filter(i => !i.adminOnly || user?.is_admin)
            .map(i => ({ key: i.key, icon: i.icon, label: i.label }))}
          onClick={({ key }) => navigate(key)}
          style={{
            background: 'transparent',
            border: 'none',
            paddingBlock: 8,
            fontSize: 14,
          }}
        />
      </Sider>

      <AntLayout style={{ marginLeft: siderWidth, transition: 'margin-left 0.2s', background: '#ffffff' }}>
        <Header style={{
          background: '#ffffff',
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid rgba(0, 0, 0, 0.05)',
          height: 56,
          position: 'sticky',
          top: 0,
          zIndex: 9,
        }}>
          <div
            style={{
              cursor: 'pointer',
              fontSize: 16,
              color: '#4e4e4e',
              width: 32, height: 32,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 8,
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,0,0,0.03)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            onClick={() => setCollapsed(!collapsed)}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </div>
          <Dropdown menu={userMenu} placement="bottomRight">
            <div style={{
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '6px 12px 6px 6px',
              borderRadius: 9999,
              transition: 'background 0.15s',
            }}
              onMouseEnter={e => (e.currentTarget.style.background = '#f5f2ef')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <Avatar size={28} style={{ background: '#000000' }} icon={<UserOutlined />} />
              <span style={{ fontWeight: 500, fontSize: 14 }}>
                {user?.full_name || user?.username}
              </span>
            </div>
          </Dropdown>
        </Header>
        <Content style={{ margin: 24, background: 'transparent' }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  );
}
