/**
 * 我的工作台 —— 角色化首页（PRD 00b 页面1）
 *
 * 落 UX 律 14 §1「登录直落工作台/待办收件箱，从待办进单」+ 标准布局「工作台/审批中心」：
 *  - 上半屏 = 我的待办（list_user_todos，引擎现成 /api/my-todos）
 *  - 下半屏 = 角色看板卡（占位，EXT-00b-A 报表脚手架，待 P 段/6 报表建造）
 *
 * 角色裁剪（14 §7）：看板卡按 user.role 取 00b 逐角色默认卡；销售端不含成本/利润点（字段防火墙在后端两路一致遮蔽，前端不绕过）。
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Empty, Spin, Button, Tag, Row, Col } from 'antd';
import { ReloadOutlined, RightOutlined, InboxOutlined } from '@ant-design/icons';
import { getMyTodos, aggregate } from '../api';
import { useAuth } from '../auth';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

/**
 * 00b 逐角色默认看板卡。
 *  - 有 `agg` 的卡：接引擎 /api/aggregate 出**真实数字**（仅用引擎能表达的计数/求和，
 *    全部走当前公司过滤 _company_filter；KPI 完整口径仍落 6 报表，GAP-00b-1）。
 *  - 无 `agg` 的卡：标注真实数据源（待 6 报表/P 段铺口径），不伪造数字。
 * agg: { table, field, func, unit }，table 必须是角色可查的 __queryable__/__doc_types__ 表。
 */
const ROLE_CARDS = {
  SALES: [
    { title: '我的客户', agg: { table: 'customer', field: 'id', func: 'COUNT', unit: '家' } },
    { title: '我的商机（按阶段）', source: '商机漏斗口径待 6 报表（reports/opportunity-board）' },
    { title: '应收 / 超额提醒', source: 'accounts_receivable + 信用口径待 6 报表（reports/ar-board）' },
    { title: '业绩 vs 目标 / 提成', source: '目标 vs 实际口径待 6 报表（reports/target）' },
  ],
  SA: [
    { title: '我维护的客户', agg: { table: 'customer', field: 'id', func: 'COUNT', unit: '家' } },
    { title: '发货申请进度', agg: { table: 'shipment_request', field: 'id', func: 'COUNT', unit: '单' } },
    { title: '认证 / 标书待办', source: '客户认证会签口径见审批中心 / 01 模块' },
  ],
  PM: [
    { title: '本产线型号数', agg: { table: 'material', field: 'id', func: 'COUNT', unit: '个' } },
    { title: '本产线毛利看板', source: '毛利口径含成本、落 6 报表（字段防火墙）' },
  ],
  FAE: [
    { title: '本产线型号数', agg: { table: 'material', field: 'id', func: 'COUNT', unit: '个' } },
    { title: '本产线送样 / 小批量商机', source: '送样口径待 04 样品 SDN / 6 报表' },
  ],
  PA: [
    { title: '采购订单在途', agg: { table: 'purchase_order', field: 'id', func: 'COUNT', unit: '单' } },
    { title: '备货消单跟进', source: '备货消单口径待 04 备货 / 6 报表' },
  ],
  LOGISTICS: [
    { title: '待收货（收货单）', agg: { table: 'goods_receipt', field: 'id', func: 'COUNT', unit: '单' } },
    { title: '待发货（发货单）', agg: { table: 'shipment_request', field: 'id', func: 'COUNT', unit: '单' } },
  ],
  LOGISTICS_LEAD: [
    { title: '库位总数', agg: { table: 'warehouse_location', field: 'id', func: 'COUNT', unit: '个' } },
    { title: '库存批次', agg: { table: 'inventory', field: 'id', func: 'COUNT', unit: '批' } },
  ],
  FINANCE: [
    { title: '应收笔数', agg: { table: 'accounts_receivable', field: 'id', func: 'COUNT', unit: '笔' } },
    { title: '应付笔数', agg: { table: 'accounts_payable', field: 'id', func: 'COUNT', unit: '笔' } },
  ],
  FINANCE_DIRECTOR: [
    { title: '应收笔数（授权公司）', agg: { table: 'accounts_receivable', field: 'id', func: 'COUNT', unit: '笔' } },
    { title: '跨公司财务口径汇总（只读）', source: '跨公司汇总口径待 6 报表（reports/cross-company）' },
  ],
  BOSS: [
    { title: '客户总数', agg: { table: 'customer', field: 'id', func: 'COUNT', unit: '家' } },
    { title: '供应商总数', agg: { table: 'supplier', field: 'id', func: 'COUNT', unit: '家' } },
    { title: '销售订单数', agg: { table: 'sales_order', field: 'id', func: 'COUNT', unit: '单' } },
    { title: '6 公司成单 / 毛利对比', source: '跨公司毛利口径待 6 报表（reports/kpi）' },
  ],
  ADMIN: [
    { title: '客户主数据', agg: { table: 'customer', field: 'id', func: 'COUNT', unit: '条' } },
    { title: '供应商主数据', agg: { table: 'supplier', field: 'id', func: 'COUNT', unit: '条' } },
    { title: '型号主数据', agg: { table: 'material', field: 'id', func: 'COUNT', unit: '条' } },
    { title: '审计异常', source: '审计异常口径见 操作日志审计（org/audit）' },
  ],
};

function Pill({ bg, color, children }) {
  return (
    <span style={{
      display: 'inline-block', padding: '2px 10px', background: bg, color,
      borderRadius: 4, fontSize: 12, fontWeight: 500, lineHeight: '18px',
    }}>{children}</span>
  );
}

export default function Workbench() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [todos, setTodos] = useState([]);
  const [loading, setLoading] = useState(true);
  // 看板卡真实数字：{ cardTitle: number | null }（null=该公司无权/加载失败，标 —）
  const [metrics, setMetrics] = useState({});

  const cards = ROLE_CARDS[user?.role] || [];

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await getMyTodos();
      setTodos(data || []);
    } catch { setTodos([]); }
    setLoading(false);
  };

  // 看板卡接 /api/aggregate（仅有 agg 源的卡；后端按当前公司 _company_filter 过滤）
  const loadMetrics = async (cardList) => {
    const withAgg = cardList.filter((c) => c.agg);
    if (!withAgg.length) { setMetrics({}); return; }
    const results = await Promise.allSettled(
      withAgg.map((c) => aggregate(c.agg.table, c.agg.field, c.agg.func))
    );
    const next = {};
    results.forEach((r, i) => {
      const ok = r.status === 'fulfilled' && r.value?.data && r.value.data.error == null;
      next[withAgg[i].title] = ok ? (r.value.data.value ?? 0) : null;
    });
    setMetrics(next);
  };

  useEffect(() => {
    load();
    loadMetrics(cards);
    // 公司切换后重取待办 + 看板数字（active_company_id 改变 → 数字应随之变）
    const onSwitch = () => { load(); loadMetrics(cards); };
    window.addEventListener('pt:company-changed', onSwitch);
    return () => window.removeEventListener('pt:company-changed', onSwitch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.role]);

  // 按 流程 > 节点 分组（沿用待办语义）
  const grouped = useMemo(() => {
    const g = {};
    for (const t of todos) {
      const key = `${t.workflow_id}|${t.state_code}`;
      if (!g[key]) {
        g[key] = {
          workflow_id: t.workflow_id, workflow_name: t.workflow_name,
          state_code: t.state_code, state_name: t.state_name, items: [],
        };
      }
      g[key].items.push(t);
    }
    return Object.values(g).sort((a, b) =>
      (a.workflow_name || '').localeCompare(b.workflow_name || ''));
  }, [todos]);

  return (
    <div>
      {/* Hero */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 28, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0 }}>
          我的工作台
        </h2>
        <Pill bg="#fbf5e4" color="#b8860b">{todos.length} 条待办</Pill>
        <span style={{ color: '#777169', fontSize: 13 }}>
          {user?.full_name || user?.username} · {user?.role}
        </span>
        <div style={{ flex: 1 }} />
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
      </div>

      {/* 上半屏：我的待办（引擎现成 list_user_todos） */}
      <Card
        title={<span style={{ fontWeight: 500 }}>我的待办</span>}
        extra={<Button type="text" size="small" onClick={() => navigate('/approvals')}>去审批中心 <RightOutlined style={{ fontSize: 11 }} /></Button>}
        style={{ borderRadius: 16, boxShadow: CARD_SHADOW, border: 'none', marginBottom: 20 }}
        styles={{ body: { padding: grouped.length ? 0 : 24 } }}
      >
        {loading ? (
          <Spin style={{ display: 'block', margin: '40px auto' }} />
        ) : grouped.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`无待办 — ${user?.role} 当前没有可处理的单据`} />
        ) : (
          grouped.map((g) => (
            <div key={`${g.workflow_id}-${g.state_code}`}
              style={{ padding: '12px 20px', borderBottom: '1px solid rgba(0,0,0,0.05)', cursor: 'pointer' }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(245,242,239,0.5)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              onClick={() => navigate(`/node/${g.workflow_id}/${g.state_code}`)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <InboxOutlined style={{ color: '#bfbbb5' }} />
                <span style={{ fontWeight: 500, fontSize: 14 }}>{g.workflow_name}</span>
                <Pill bg="#eaf1fb" color="#1f5aa8">{g.state_name}</Pill>
                <Pill bg="#f5f2ef" color="#4e4e4e">{g.items.length}</Pill>
                <div style={{ flex: 1 }} />
                <RightOutlined style={{ fontSize: 11, color: '#bfbbb5' }} />
              </div>
            </div>
          ))
        )}
      </Card>

      {/* 下半屏：角色看板卡 —— 有 agg 源的接 /api/aggregate 出真实数字，余者标真实数据源 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '4px 0 12px' }}>
        <span style={{ fontWeight: 500, fontSize: 15, color: '#000' }}>我的看板</span>
        <Tag style={{ background: '#eaf1fb', color: '#1f5aa8', border: 'none' }}>实时计数接引擎 · 完整 KPI 落 6 报表</Tag>
      </div>
      <Row gutter={[16, 16]}>
        {(cards.length ? cards : [{ title: '（该角色看板卡待配置）' }]).map((c) => {
          const hasAgg = !!c.agg;
          const val = metrics[c.title];
          return (
            <Col key={c.title} xs={24} sm={12} lg={8}>
              <Card size="small" style={{ borderRadius: 16, boxShadow: CARD_SHADOW, border: 'none', minHeight: 110 }}>
                <div style={{ fontWeight: 500, fontSize: 14, marginBottom: 10 }}>{c.title}</div>
                {hasAgg ? (
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                    <span style={{ fontSize: 28, fontWeight: 300, letterSpacing: '-0.02em', color: '#000' }}>
                      {val == null ? '—' : Number(val).toLocaleString()}
                    </span>
                    <span style={{ color: '#777169', fontSize: 13 }}>{c.agg.unit || ''}</span>
                  </div>
                ) : (
                  <div style={{ color: '#bfbbb5', fontSize: 12, lineHeight: 1.5 }}>
                    数据源：{c.source || '待 6 报表口径'}
                  </div>
                )}
              </Card>
            </Col>
          );
        })}
      </Row>
    </div>
  );
}
