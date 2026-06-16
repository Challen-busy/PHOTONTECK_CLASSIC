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
import { getMyTodos } from '../api';
import { useAuth } from '../auth';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

// 00b 逐角色默认看板卡（占位标题；KPI 口径落 6 报表，GAP-00b-1）
const ROLE_CARDS = {
  SALES: ['我的商机（按阶段）', '待跟进客户', '应收 / 超额提醒', '业绩 vs 目标 / 提成'],
  SA: ['待对账', '认证 / 标书待办', '发货申请进度'],
  PM: ['本产线毛利看板'],
  FAE: ['本产线送样 / 小批量商机'],
  PA: ['采购在途到货提醒', '备货消单跟进'],
  LOGISTICS: ['今日待收货 / 待上架 / 待拣货'],
  LOGISTICS_LEAD: ['仓库统筹概览', '库位占用'],
  FINANCE: ['应收 / 应付到期'],
  FINANCE_DIRECTOR: ['跨公司财务口径汇总（只读）'],
  BOSS: ['跨公司经营汇总', '6 公司成单 / 毛利对比', '应收风险', '商机漏斗'],
  ADMIN: ['主数据健康度', '审计异常'],
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

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await getMyTodos();
      setTodos(data || []);
    } catch { setTodos([]); }
    setLoading(false);
  };

  useEffect(() => {
    load();
    // 公司切换后重取（CompanySwitcher 广播；真正按 active_company_id 过滤待后端接线 EXT-00b-B）
    const onSwitch = () => load();
    window.addEventListener('pt:company-changed', onSwitch);
    return () => window.removeEventListener('pt:company-changed', onSwitch);
  }, []);

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

  const cards = ROLE_CARDS[user?.role] || [];

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

      {/* 下半屏：角色看板卡（占位，EXT-00b-A，待 P 段 / 6 报表建造） */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '4px 0 12px' }}>
        <span style={{ fontWeight: 500, fontSize: 15, color: '#000' }}>我的看板</span>
        <Tag style={{ background: '#f5f2ef', color: '#777169', border: 'none' }}>待 P 段建造</Tag>
      </div>
      <Row gutter={[16, 16]}>
        {(cards.length ? cards : ['（该角色看板卡待配置）']).map((c) => (
          <Col key={c} xs={24} sm={12} lg={8}>
            <Card size="small" style={{ borderRadius: 16, boxShadow: CARD_SHADOW, border: 'none', minHeight: 110 }}>
              <div style={{ fontWeight: 500, fontSize: 14, marginBottom: 8 }}>{c}</div>
              <div style={{ color: '#bfbbb5', fontSize: 12 }}>功能已就绪 · 待开通</div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
