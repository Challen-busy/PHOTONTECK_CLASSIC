/**
 * 我的待办 — 按"流程 > 节点"分组列出当前用户角色可操作的单据
 * 点行进入对应 NodeView
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Empty, Spin, Button, Tooltip } from 'antd';
import { ReloadOutlined, RightOutlined } from '@ant-design/icons';
import { getMyTodos } from '../api';
import { useAuth } from '../auth';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

// 极简"淡底深字"小徽章
function Pill({ bg, color, children, border }) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 10px',
      background: bg,
      color,
      border: border ? `1px solid ${border}` : 'none',
      borderRadius: 4,
      fontSize: 12,
      fontWeight: 500,
      letterSpacing: '0.02em',
      lineHeight: '18px',
    }}>
      {children}
    </span>
  );
}

export default function MyTodos() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [todos, setTodos] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await getMyTodos();
      setTodos(data || []);
    } catch {
      setTodos([]);
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  // group by workflow + state
  const grouped = useMemo(() => {
    const g = {};
    for (const t of todos) {
      const key = `${t.workflow_id}|${t.state_code}`;
      if (!g[key]) {
        g[key] = {
          workflow_id: t.workflow_id,
          workflow_name: t.workflow_name,
          state_code: t.state_code,
          state_name: t.state_name,
          is_initial: t.is_initial,
          doc_type: t.doc_type,
          actions: t.actions,
          items: [],
        };
      }
      g[key].items.push(t);
    }
    return Object.values(g).sort((a, b) =>
      a.workflow_name.localeCompare(b.workflow_name) || a.state_name.localeCompare(b.state_name)
    );
  }, [todos]);

  const total = todos.length;

  return (
    <div>
      {/* Hero */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <h2 style={{
          fontSize: 28,
          fontWeight: 300,
          letterSpacing: '-0.01em',
          color: '#000',
          margin: 0,
          lineHeight: 1.15,
        }}>
          我的待办
        </h2>
        <Pill bg="#fbf5e4" color="#b8860b">{total} 条</Pill>
        <span style={{ color: '#777169', fontSize: 13, letterSpacing: '0.01em' }}>
          {user?.full_name} · {user?.role}
        </span>
        <div style={{ flex: 1 }} />
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
      </div>

      {loading ? (
        <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />
      ) : grouped.length === 0 ? (
        <Card style={{ borderRadius: 16, boxShadow: CARD_SHADOW, border: 'none' }}>
          <Empty description={`无待办 — ${user?.role} 当前没有可处理的单据`} />
        </Card>
      ) : (
        grouped.map(g => (
          <Card
            key={`${g.workflow_id}-${g.state_code}`}
            size="small"
            style={{
              borderRadius: 16,
              marginBottom: 14,
              boxShadow: CARD_SHADOW,
              border: 'none',
            }}
            styles={{ body: { padding: 0 } }}
            title={(
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0' }}>
                <span style={{ fontWeight: 500, fontSize: 15, letterSpacing: '0.01em', color: '#000' }}>
                  {g.workflow_name}
                </span>
                <Pill bg="#eaf1fb" color="#1f5aa8">{g.state_name}</Pill>
                {g.is_initial && <Pill bg="#fbf5e4" color="#b8860b">起始</Pill>}
                <Pill bg="#f5f2ef" color="#4e4e4e">{g.items.length}</Pill>
              </div>
            )}
            extra={(
              <Button
                size="small"
                type="text"
                style={{ color: '#4e4e4e', fontWeight: 500 }}
                onClick={() => navigate(`/node/${g.workflow_id}/${g.state_code}`)}
              >
                打开节点 <RightOutlined style={{ fontSize: 11 }} />
              </Button>
            )}
          >
            <div>
              {g.items.slice(0, 20).map((it, idx, arr) => (
                <div
                  key={it.doc_id}
                  style={{
                    padding: '12px 20px',
                    borderBottom: idx === arr.length - 1 && g.items.length <= 20 ? 'none' : '1px solid rgba(0, 0, 0, 0.05)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    cursor: 'pointer',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(245, 242, 239, 0.5)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                  onClick={() => navigate(`/node/${g.workflow_id}/${g.state_code}`)}
                >
                  <span style={{
                    color: '#bfbbb5', fontSize: 12, minWidth: 52,
                    fontFamily: 'ui-monospace, monospace',
                  }}>#{it.doc_id}</span>
                  <span style={{
                    flex: 1, fontSize: 13, color: '#000',
                    letterSpacing: '0.01em',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>{it.summary}</span>
                  {it.actions.length > 0 && (
                    <Tooltip title={it.actions.map(a => a.label).join(' / ')}>
                      <Pill bg="#ebf5ee" color="#1f8f3a">
                        {it.actions.length} 个动作
                      </Pill>
                    </Tooltip>
                  )}
                  {it.updated_at && (
                    <span style={{ color: '#bfbbb5', fontSize: 11, letterSpacing: '0.01em' }}>
                      {it.updated_at.replace('T', ' ').slice(0, 16)}
                    </span>
                  )}
                </div>
              ))}
              {g.items.length > 20 && (
                <div style={{
                  textAlign: 'center', padding: 12, color: '#777169', fontSize: 12,
                  borderTop: '1px solid rgba(0,0,0,0.05)', background: 'rgba(245,242,239,0.3)',
                }}>
                  …还有 {g.items.length - 20} 条，点"打开节点"查看全部
                </div>
              )}
            </div>
          </Card>
        ))
      )}
    </div>
  );
}
