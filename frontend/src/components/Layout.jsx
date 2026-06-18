import { useEffect, useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout as AntLayout, Menu, Avatar, Dropdown, Tag, Badge } from 'antd';
import {
  LogoutOutlined, UserOutlined,
  MenuFoldOutlined, MenuUnfoldOutlined, ApartmentOutlined,
  CheckSquareOutlined, TeamOutlined, ShoppingOutlined, InboxOutlined,
  FileProtectOutlined, AccountBookOutlined, BarChartOutlined,
  DatabaseOutlined, ProfileOutlined, BankOutlined, TableOutlined,
} from '@ant-design/icons';
import { useAuth } from '../auth';
import { getMyTodos } from '../api';
import CompanySwitcher from './CompanySwitcher';
import { FEATURE_SPECIAL_BATCH_SHIPMENT } from '../pages/sales/SpecialShipmentPage';

const { Header, Sider, Content } = AntLayout;

/**
 * 业务导向导航树（落 PRD 00 §2 IA：10 个业务域 0~9）。
 * 旧引擎导航（看板/CRM/ERP/WMS/命令/链路/数据/流程/Agent/流程管理/管理）已移除。
 * 引擎壳页（数据浏览 DataExplorer / 流程管理 FlowEditor）降为 admin 专属、收进域 9。
 * Agent 入口不挂（本项目不做 AI，00b 明确隐藏）。
 */
const buildMenuItems = (todoCount, isAdmin) => {
  const items = [
    {
      key: 'g0',
      icon: <CheckSquareOutlined />,
      label: '工作台',
      children: [
        {
          key: '/',
          label: (
            <span>
              我的工作台{' '}
              {todoCount > 0 && (
                <Badge count={todoCount} size="small" offset={[6, -2]}
                  style={{ backgroundColor: '#b8860b' }} />
              )}
            </span>
          ),
        },
        { key: '/notifications', label: '通知中心' },
        { key: '/approvals', label: '我的审批 / 审批中心' },
      ],
    },
    {
      key: 'g1',
      icon: <TeamOutlined />,
      label: '客户 / 销售',
      children: [
        { key: '/sales/customers', label: '客户 / 联系人' },
        { key: '/sales/leads', label: '线索' },
        { key: '/sales/opportunities', label: '商机 / 项目' },
        { key: '/sales/quotes', label: '报价单' },
        { key: '/sales/orders', label: '销售订单 SO' },
        { key: '/sales/orders-ledger', label: 'SO 签单大表 / 销售台账' },
        { key: '/sales/shipment-requests', label: '发货申请 / 通知' },
        // 特批发货（先发后补单）= 可隐藏模块（决策⑫）：feature.special_batch_shipment 默认 OFF →
        // 导航不出此入口（条件渲染）。开关 ON 时显示。待后端 ➕ per-company /api/features 后改读后端。
        ...(FEATURE_SPECIAL_BATCH_SHIPMENT
          ? [{ key: '/sales/special-shipment', label: '特批发货（先发后补单）' }]
          : []),
        { key: '/sales/invoices', label: '销项发票' },
        { key: '/sales/tickets', label: '售后技术工单' },
        { key: '/sales/qualification', label: '客户认证 / 标书' },
        { key: '/sales/forecast', label: 'Forecast 接单' },
      ],
    },
    {
      key: 'g2',
      icon: <ShoppingOutlined />,
      label: '采购 / 供应链',
      children: [
        { key: '/purchase/inquiries', label: '内部询价' },
        { key: '/purchase/supplier-inquiries', label: '对原厂询价' },
        { key: '/purchase/notices', label: '采购通知' },
        { key: '/purchase/orders', label: '采购订单 PO' },
        { key: '/purchase/orders-ledger', label: 'PO 总表 / 采购台账' },
        { key: '/purchase/stockup', label: '备货申请' },
        { key: '/purchase/samples', label: '样品 SDN' },
        { key: '/purchase/rma', label: 'RMA 退货' },
        { key: '/purchase/invoices', label: '进项发票' },
        { key: '/purchase/intransit', label: '采购在途' },
        { key: '/purchase/payments', label: '付款申请' },
      ],
    },
    {
      key: 'g3',
      icon: <InboxOutlined />,
      label: '仓储 WMS',
      children: [
        { key: '/wms/inbound', label: '入库收货' },
        { key: '/wms/inventory', label: '库存' },
        { key: '/wms/transactions', label: '库存流水 / 事务台账' },
        { key: '/wms/outbound', label: '出库发货' },
        { key: '/wms/outbound-ledger', label: '出库台账 / 基本出库' },
        { key: '/wms/subcontract', label: '委外加工' },
        { key: '/wms/transfer', label: '调拨' },
        { key: '/wms/count', label: '盘点' },
        { key: '/wms/stock-adjustment', label: '库存调整单' },
        { key: '/wms/locations', label: '库位管理' },
        { key: '/wms/labels', label: '标签打印' },
      ],
    },
    {
      key: 'g4',
      icon: <FileProtectOutlined />,
      label: '报关',
      children: [
        { key: '/customs/declarations', label: '报关单' },
        { key: '/customs/return-monitor', label: '退运监控（180天）' },
        { key: '/customs/fees', label: '报关费补录' },
        { key: '/customs/licenses', label: '进出口证台账' },
        { key: '/customs/logistics', label: '物流 API 货物进度' },
      ],
    },
    {
      key: 'g5',
      icon: <AccountBookOutlined />,
      label: '财务 / 总账',
      children: [
        { key: '/finance/accounts', label: '科目表' },
        { key: '/finance/opening-balance', label: '期初建账' },
        { key: '/finance/voucher-word', label: '凭证字' },
        { key: '/finance/aux-dimension', label: '核算维度' },
        { key: '/finance/cashflow-item', label: '现金流量项目' },
        { key: '/finance/currency', label: '币别' },
        { key: '/finance/exchange-rate', label: '汇率体系' },
        { key: '/finance/settlement-method', label: '结算方式' },
        { key: '/finance/accounting-policy', label: '会计政策' },
        { key: '/finance/accounting-system', label: '核算体系' },
        { key: '/finance/summary-entry', label: '摘要库' },
        { key: '/finance/voucher', label: '凭证录入（总账）' },
        { key: '/finance/voucher-workbench', label: '凭证工作台（批量审核/过账）' },
        { key: '/finance/voucher-query', label: '凭证查询' },
        { key: '/finance/voucher-summary', label: '凭证汇总表' },
        { key: '/finance/ledger-books', label: '账簿（明细/总账/试算/维度）' },
        { key: '/finance/balance-sheet', label: '资产负债表' },
        { key: '/finance/income-statement', label: '利润表' },
        { key: '/finance/cash-flow', label: '现金流量表' },
        { key: '/finance/cashflow-assign', label: '现金流量指定/归集' },
        { key: '/finance/cashflow-tlist', label: '现金流量 T 型账' },
        { key: '/finance/recurring-schemes', label: '定期凭证（转账/摊销/预提）' },
        { key: '/finance/ledger-report', label: '账表查询（科目余额 / 明细账）' },
        { key: '/finance/period-close', label: '期末结账' },
        { key: '/finance/ar', label: '应收管理' },
        { key: '/finance/ap', label: '应付视图' },
        { key: '/finance/advance', label: '预收 / 预付到账确认' },
        { key: '/finance/credit-note', label: 'Credit Note' },
        { key: '/finance/kingdee-outbox', label: '单据推送中心（金蝶）' },
        { key: '/finance/chain', label: '单据链路追踪' },
        { key: '/finance/reconcile', label: '对账' },
      ],
    },
    {
      key: 'g6',
      icon: <BarChartOutlined />,
      label: '报表 / 看板',
      children: [
        { key: '/reports/kpi', label: '经营 KPI' },
        { key: '/reports/opportunity-board', label: '商机看板' },
        { key: '/reports/ar-board', label: '应收看板' },
        { key: '/reports/target', label: '业绩目标 vs 实际' },
        { key: '/reports/commission', label: '提成' },
        { key: '/reports/cross-company', label: '跨公司只读汇总' },
      ],
    },
    {
      key: 'g7',
      icon: <DatabaseOutlined />,
      label: '主数据',
      children: [
        { key: '/master/customers', label: '客户' },
        { key: '/master/suppliers', label: '供应商 / 原厂' },
        { key: '/master/products', label: '产品 / 型号' },
        { key: '/master/product-codes', label: '产品代码' },
        { key: '/master/product-lines', label: '产线' },
        { key: '/master/locations', label: '库位' },
        { key: '/master/hscode', label: 'HS 编码' },
        { key: '/master/uom', label: '计量单位' },
      ],
    },
    {
      key: 'g8',
      icon: <ProfileOutlined />,
      label: '配置 / 模板',
      children: [
        { key: '/config/label-templates', label: '标签模板' },
        { key: '/config/doc-templates', label: '单据模板' },
        { key: '/config/numbering', label: '编号规则' },
        { key: '/config/approval-flow', label: '审批流配置' },
        { key: '/config/commission', label: '提成规则配置' },
      ],
    },
  ];

  if (isAdmin) {
    items.push({
      key: 'g9',
      icon: <BankOutlined />,
      label: '企业 / 账号管理',
      children: [
        { key: '/org/companies', label: '公司 / 租户' },
        { key: '/org/users', label: '用户' },
        { key: '/org/roles', label: '角色与权限' },
        { key: '/org/audit', label: '操作日志审计' },
        { type: 'divider' },
        { key: '/data', icon: <TableOutlined />, label: '数据浏览（引擎）' },
        { key: '/flow-editor', icon: <ApartmentOutlined />, label: '流程管理（引擎）' },
      ],
    });
  }

  return items;
};

// 克制的语义色 —— 用于角色徽章（降饱和版）
const roleColors = {
  BOSS: '#b42318', OPERATIONS: '#6b46c1', FINANCE: '#b8860b',
  FINANCE_DIRECTOR: '#9a6a00',
  SALES: '#1f5aa8', SA: '#0e7490', SALES_ENGINEER: '#1f5aa8', SALES_ASSISTANT: '#0e7490',
  PM: '#1f8f3a', FAE: '#15803d', PA: '#4d7c0f',
  PRODUCT_MANAGER: '#1f8f3a', PRODUCT_ASSISTANT: '#4d7c0f',
  LOGISTICS: '#c2410c', LOGISTICS_LEAD: '#9a3412', ADMIN: '#4e4e4e',
};

// 顶层分组 key（用于 openKeys 默认展开当前所在域）
const GROUP_PREFIX = {
  '/': 'g0', '/notifications': 'g0', '/approvals': 'g0',
  '/sales': 'g1', '/purchase': 'g2', '/wms': 'g3', '/customs': 'g4',
  '/finance': 'g5', '/reports': 'g6', '/master': 'g7', '/config': 'g8',
  '/org': 'g9', '/data': 'g9', '/flow-editor': 'g9',
};

function activeGroup(pathname) {
  if (pathname === '/') return 'g0';
  const seg = '/' + pathname.split('/')[1];
  return GROUP_PREFIX[seg] || GROUP_PREFIX[pathname] || 'g0';
}

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const [todoCount, setTodoCount] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const [openKeys, setOpenKeys] = useState([activeGroup(location.pathname)]);

  useEffect(() => {
    setOpenKeys((prev) => {
      const g = activeGroup(location.pathname);
      return prev.includes(g) ? prev : [...prev, g];
    });
  }, [location.pathname]);

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

  const siderWidth = collapsed ? 80 : 240;

  return (
    <AntLayout style={{ minHeight: '100vh', background: '#ffffff' }}>
      <Sider
        collapsed={collapsed}
        trigger={null}
        collapsible
        theme="light"
        width={240}
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
          openKeys={collapsed ? undefined : openKeys}
          onOpenChange={setOpenKeys}
          items={buildMenuItems(todoCount, user?.is_admin)}
          onClick={({ key }) => { if (key.startsWith('/')) navigate(key); }}
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <CompanySwitcher />
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
          </div>
        </Header>
        <Content style={{ margin: 24, background: 'transparent' }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  );
}
