/**
 * 统一的修改卡片组件 — Agent页面和流程页面共用
 */

import { Card, Tag, Button, Space } from 'antd';
import { CheckOutlined, CloseOutlined } from '@ant-design/icons';

export default function ChangeCard({ card, onApprove, onReject, disabled }) {
  const isReject = card.recommendation === 'reject';
  return (
    <Card size="small" style={{
      borderRadius: 8, marginBottom: 8,
      borderLeft: `4px solid ${isReject ? '#ff4d4f' : '#faad14'}`,
      opacity: disabled ? 0.5 : 1,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            {card.transition_name}
            <Tag style={{ marginLeft: 8 }}>{card.doc_type} #{card.doc_id}</Tag>
            {isReject && <Tag color="red">不建议执行</Tag>}
          </div>
          {card.changes?.map((c, i) => (
            <div key={i} style={{ fontSize: 12, padding: '2px 0', color: '#555' }}>
              <span style={{ color: '#888' }}>{c.field}:</span>{' '}
              <span style={{ textDecoration: 'line-through', color: '#cf1322' }}>{c.from}</span>
              {' → '}
              <span style={{ color: '#389e0d', fontWeight: 500 }}>{c.to}</span>
            </div>
          ))}
          {card.checks?.length > 0 && (
            <div style={{ marginTop: 4, fontSize: 11, color: '#888' }}>
              {card.checks.join(' · ')}
            </div>
          )}
          {card.reason && <div style={{ color: '#cf1322', fontSize: 12, marginTop: 4 }}>{card.reason}</div>}
        </div>
        <Space style={{ marginLeft: 12, flexShrink: 0 }}>
          <Button size="small" danger icon={<CloseOutlined />} onClick={() => onReject(card)} disabled={disabled}>拒绝</Button>
          <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => onApprove(card)} disabled={disabled}>批准</Button>
        </Space>
      </div>
    </Card>
  );
}
