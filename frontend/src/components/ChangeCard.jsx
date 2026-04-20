/**
 * 统一的修改卡片组件 — Agent页面和流程页面共用
 */

import { Card, Button, Space } from 'antd';
import { CheckOutlined, CloseOutlined } from '@ant-design/icons';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

function Pill({ bg, color, children, style }) {
  return (
    <span style={{
      display: 'inline-block', padding: '1px 8px', borderRadius: 4,
      background: bg, color, fontSize: 11, fontWeight: 500,
      letterSpacing: '0.02em', ...style,
    }}>{children}</span>
  );
}

export default function ChangeCard({ card, onApprove, onReject, disabled }) {
  const isReject = card.recommendation === 'reject';
  const accentColor = isReject ? '#b42318' : '#b8860b';

  return (
    <Card
      size="small"
      style={{
        borderRadius: 12, marginBottom: 10,
        borderLeft: `4px solid ${accentColor}`,
        boxShadow: CARD_SHADOW,
        border: 'none',
        borderLeftWidth: 4,
        borderLeftStyle: 'solid',
        borderLeftColor: accentColor,
        opacity: disabled ? 0.55 : 1,
        transition: 'opacity 0.15s',
      }}
      styles={{ body: { padding: '12px 16px' } }}
    >
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        alignItems: 'flex-start', gap: 12,
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontWeight: 500, marginBottom: 6,
            display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
            letterSpacing: '0.01em', color: '#000',
          }}>
            <span>{card.transition_name}</span>
            <Pill bg="#f5f2ef" color="#4e4e4e">
              {card.doc_type}
              <span style={{ marginLeft: 3, fontFamily: 'ui-monospace, monospace', opacity: 0.8 }}>
                #{card.doc_id}
              </span>
            </Pill>
            {isReject && <Pill bg="#fdecea" color="#b42318">不建议执行</Pill>}
          </div>
          {card.changes?.map((c, i) => (
            <div
              key={i}
              style={{
                fontSize: 12, padding: '3px 0',
                color: '#4e4e4e', letterSpacing: '0.01em',
              }}
            >
              <span style={{ color: '#777169' }}>{c.field}:</span>{' '}
              <span style={{
                textDecoration: 'line-through',
                color: '#b42318',
                opacity: 0.75,
              }}>
                {c.from ?? '—'}
              </span>
              <span style={{ color: '#bfbbb5', margin: '0 4px' }}>→</span>
              <span style={{ color: '#1f8f3a', fontWeight: 500 }}>
                {c.to ?? '—'}
              </span>
            </div>
          ))}
          {card.checks?.length > 0 && (
            <div style={{
              marginTop: 6, fontSize: 11, color: '#777169',
              letterSpacing: '0.02em',
            }}>
              {card.checks.join(' · ')}
            </div>
          )}
          {card.reason && (
            <div style={{
              color: '#b42318', fontSize: 12, marginTop: 6,
              letterSpacing: '0.01em',
            }}>
              {card.reason}
            </div>
          )}
        </div>
        <Space style={{ flexShrink: 0 }}>
          <Button
            size="small"
            danger
            icon={<CloseOutlined />}
            onClick={() => onReject(card)}
            disabled={disabled}
          >
            拒绝
          </Button>
          <Button
            size="small"
            type="primary"
            icon={<CheckOutlined />}
            onClick={() => onApprove(card)}
            disabled={disabled}
          >
            批准
          </Button>
        </Space>
      </div>
    </Card>
  );
}
