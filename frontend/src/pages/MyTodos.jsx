/**
 * 我的待办 — 按"流程 > 节点"分组列出当前用户角色可操作的单据
 * 点行进入对应 NodeView
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Empty, Spin, Tag, Button, Tooltip } from 'antd';
import { ReloadOutlined, RightOutlined } from '@ant-design/icons';
import { getMyTodos } from '../api';
import { useAuth } from '../auth';

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
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <h2 style={{ fontSize: 20, fontWeight: 600, color: '#1a1a2e', margin: 0 }}>我的待办</h2>
        <Tag color="orange">{total} 条</Tag>
        <span style={{ color: '#888', fontSize: 12 }}>
          {user?.full_name} · {user?.role}
        </span>
        <div style={{ flex: 1 }} />
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
      </div>

      {loading ? (
        <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />
      ) : grouped.length === 0 ? (
        <Card style={{ borderRadius: 12 }}>
          <Empty description={`无待办 — ${user?.role} 当前没有可处理的单据`} />
        </Card>
      ) : (
        grouped.map(g => (
          <Card key={`${g.workflow_id}-${g.state_code}`}
            size="small" style={{ borderRadius: 12, marginBottom: 12 }}
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontWeight: 600 }}>{g.workflow_name}</span>
                <Tag color="blue">{g.state_name}</Tag>
                {g.is_initial && <Tag color="gold">起始</Tag>}
                <Tag>{g.items.length}</Tag>
              </div>
            }
            extra={
              <Button size="small" type="link"
                onClick={() => navigate(`/node/${g.workflow_id}/${g.state_code}`)}>
                打开节点 <RightOutlined />
              </Button>
            }>
            <div>
              {g.items.slice(0, 20).map(it => (
                <div key={it.doc_id}
                  style={{
                    padding: '8px 10px', borderBottom: '1px solid #f0f0f0',
                    display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                  }}
                  onClick={() => navigate(`/node/${g.workflow_id}/${g.state_code}`)}>
                  <span style={{ color: '#888', fontSize: 12, minWidth: 52 }}>#{it.doc_id}</span>
                  <span style={{ flex: 1, fontSize: 13 }}>{it.summary}</span>
                  {it.actions.length > 0 && (
                    <Tooltip title={it.actions.map(a => a.label).join(' / ')}>
                      <Tag color="green">{it.actions.length} 个动作</Tag>
                    </Tooltip>
                  )}
                  {it.updated_at && (
                    <span style={{ color: '#bbb', fontSize: 11 }}>
                      {it.updated_at.replace('T', ' ').slice(0, 16)}
                    </span>
                  )}
                </div>
              ))}
              {g.items.length > 20 && (
                <div style={{ textAlign: 'center', padding: 8, color: '#888', fontSize: 12 }}>
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
