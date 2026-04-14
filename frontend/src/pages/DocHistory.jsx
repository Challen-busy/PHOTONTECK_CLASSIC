import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Timeline, Tag, Button, Empty, Spin, Descriptions } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { getHistory } from '../api';

export default function DocHistory() {
  const { docType, docId } = useParams();
  const navigate = useNavigate();
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    getHistory(docType, docId).then(r => { setLogs(r.data); setLoading(false); });
  }, [docType, docId]);

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button>
        <h2 style={{ fontSize: 20, fontWeight: 600, color: '#1a1a2e', margin: 0 }}>
          操作历史 · {docType} #{docId}
        </h2>
      </div>

      {logs.length === 0 ? (
        <Empty description="暂无操作记录" />
      ) : (
        <Card style={{ borderRadius: 12 }}>
          <Timeline items={logs.map((l, i) => ({
            color: l.to_state === 'CANCELLED' ? 'red' : 'blue',
            children: (
              <div key={i} style={{ paddingBottom: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>
                    <strong>{l.transition}</strong>
                    <Tag style={{ marginLeft: 8 }}>{l.from_state}</Tag>
                    <span style={{ margin: '0 4px' }}>→</span>
                    <Tag color="blue">{l.to_state}</Tag>
                  </span>
                  <span style={{ color: '#999', fontSize: 12 }}>{l.timestamp?.replace('T', ' ').slice(0, 19)}</span>
                </div>
                {l.comment && <div style={{ color: '#666', fontSize: 13, marginTop: 4 }}>备注: {l.comment}</div>}
                {l.changed_fields && Object.keys(l.changed_fields).length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <Button type="link" size="small" onClick={() => setExpanded(expanded === i ? null : i)}>
                      {expanded === i ? '收起' : '查看变更详情'}
                    </Button>
                    {expanded === i && (
                      <Descriptions size="small" bordered column={1} style={{ marginTop: 8 }}>
                        {Object.entries(l.changed_fields).map(([field, change]) => (
                          <Descriptions.Item key={field} label={field}>
                            <span style={{ color: '#cf1322', textDecoration: 'line-through' }}>{change.old}</span>
                            <span style={{ margin: '0 8px' }}>→</span>
                            <span style={{ color: '#389e0d' }}>{change.new}</span>
                          </Descriptions.Item>
                        ))}
                      </Descriptions>
                    )}
                  </div>
                )}
              </div>
            ),
          }))} />
        </Card>
      )}
    </div>
  );
}
