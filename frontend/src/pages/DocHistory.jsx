import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Timeline, Button, Empty, Spin, Descriptions } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { getHistory } from '../api';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

function Pill({ bg, color, children }) {
  return (
    <span style={{
      display: 'inline-block', padding: '1px 8px', borderRadius: 4,
      background: bg, color, fontSize: 11, fontWeight: 500, letterSpacing: '0.02em',
      fontFamily: 'ui-monospace, monospace',
    }}>{children}</span>
  );
}

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
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button>
        <h2 style={{
          fontSize: 24, fontWeight: 300, letterSpacing: '-0.01em',
          color: '#000', margin: 0, lineHeight: 1.15,
        }}>
          操作历史
        </h2>
        <span style={{
          color: '#777169', fontSize: 13, letterSpacing: '0.01em',
          fontFamily: 'ui-monospace, monospace',
        }}>
          {docType} #{docId}
        </span>
      </div>

      {logs.length === 0 ? (
        <Card style={{ borderRadius: 16, boxShadow: CARD_SHADOW, border: 'none' }}>
          <Empty description="暂无操作记录" />
        </Card>
      ) : (
        <Card style={{ borderRadius: 16, boxShadow: CARD_SHADOW, border: 'none' }}>
          <Timeline
            items={logs.map((l, i) => ({
              color: l.to_state === 'CANCELLED' ? '#b42318'
                   : ['COMPLETED', 'CLOSED', 'PAID', 'APPROVED'].includes(l.to_state) ? '#1f8f3a'
                   : '#1f5aa8',
              children: (
                <div key={i} style={{ paddingBottom: 8 }}>
                  <div style={{
                    display: 'flex', justifyContent: 'space-between',
                    alignItems: 'center', gap: 8, flexWrap: 'wrap',
                  }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <strong style={{ fontWeight: 500, color: '#000', letterSpacing: '0.01em' }}>
                        {l.transition}
                      </strong>
                      <Pill bg="#f5f2ef" color="#4e4e4e">{l.from_state || '—'}</Pill>
                      <span style={{ color: '#777169' }}>→</span>
                      <Pill bg="#eaf1fb" color="#1f5aa8">{l.to_state}</Pill>
                    </span>
                    <span style={{
                      color: '#bfbbb5', fontSize: 12, letterSpacing: '0.01em',
                      fontFamily: 'ui-monospace, monospace',
                    }}>
                      {l.timestamp?.replace('T', ' ').slice(0, 19)}
                    </span>
                  </div>
                  {l.comment && (
                    <div style={{
                      color: '#4e4e4e', fontSize: 13, marginTop: 6,
                      padding: '8px 10px', background: 'rgba(245, 242, 239, 0.5)',
                      borderRadius: 6, letterSpacing: '0.01em',
                    }}>
                      {l.comment}
                    </div>
                  )}
                  {l.changed_fields && Object.keys(l.changed_fields).length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <Button
                        type="link"
                        size="small"
                        style={{ padding: 0, height: 'auto', color: '#4e4e4e', fontWeight: 500 }}
                        onClick={() => setExpanded(expanded === i ? null : i)}
                      >
                        {expanded === i ? '收起' : '查看变更详情'}
                      </Button>
                      {expanded === i && (
                        <Descriptions
                          size="small"
                          bordered
                          column={1}
                          style={{ marginTop: 8 }}
                          labelStyle={{
                            width: 160, background: '#f5f2ef',
                            color: '#4e4e4e', fontWeight: 500, letterSpacing: '0.02em',
                          }}
                        >
                          {Object.entries(l.changed_fields).map(([field, change]) => (
                            <Descriptions.Item key={field} label={field}>
                              <span style={{ color: '#b42318', textDecoration: 'line-through' }}>
                                {String(change.old ?? '—')}
                              </span>
                              <span style={{ margin: '0 8px', color: '#777169' }}>→</span>
                              <span style={{ color: '#1f8f3a', fontWeight: 500 }}>
                                {String(change.new ?? '—')}
                              </span>
                            </Descriptions.Item>
                          ))}
                        </Descriptions>
                      )}
                    </div>
                  )}
                </div>
              ),
            }))}
          />
        </Card>
      )}
    </div>
  );
}
