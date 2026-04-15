import { useRef, useState } from 'react';
import { Card, Input, Button, Tag, Spin, Space, message } from 'antd';
import { SendOutlined, RobotOutlined, CheckCircleOutlined } from '@ant-design/icons';
import { agentChat, commitTransition } from '../api';
import ChangeCard from '../components/ChangeCard';

export default function AgentChat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [pendingCards, setPendingCards] = useState([]);
  const [processedCards, setProcessedCards] = useState(new Set());
  const bottomRef = useRef(null);

  const scrollDown = () => setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);

  const hasPending = pendingCards.length > 0 && processedCards.size < pendingCards.length;

  const send = async () => {
    if (!input.trim() || hasPending) return;  // 卡片没处理完不能继续对话
    const q = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: q }]);
    setLoading(true);
    scrollDown();

    try {
      const { data } = await agentChat(q);
      setMessages(prev => [...prev, {
        role: 'agent', content: data.response,
        tools: data.tools_called, tokens: data.tokens_used, duration: data.duration_ms,
      }]);
      if (data.cards?.length > 0) {
        setPendingCards(data.cards);
        setProcessedCards(new Set());
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: 'agent', content: '出错了: ' + (e.response?.data?.detail || e.message) }]);
    }
    setLoading(false);
    scrollDown();
  };

  const approveCard = async (card) => {
    setLoading(true);
    try {
      const { data } = await commitTransition(card);
      const msg = data.success
        ? `✅ ${card.transition_name}: ${data.from_state} → ${data.to_state}`
        : `❌ ${card.transition_name}: ${data.error}`;
      setMessages(prev => [...prev, { role: 'system', content: msg }]);
      if (data.success) message.success(msg);
      else message.error(msg);
    } catch (e) { message.error('执行失败'); }
    setProcessedCards(prev => new Set([...prev, card.card_id]));
    setLoading(false);
    scrollDown();
  };

  const rejectCard = (card) => {
    setMessages(prev => [...prev, { role: 'system', content: `🚫 已拒绝: ${card.transition_name}` }]);
    setProcessedCards(prev => new Set([...prev, card.card_id]));
    scrollDown();
  };

  const approveAll = async () => {
    for (const card of pendingCards) {
      if (!processedCards.has(card.card_id)) {
        await approveCard(card);
      }
    }
  };

  const rejectAll = () => {
    pendingCards.forEach(card => {
      if (!processedCards.has(card.card_id)) rejectCard(card);
    });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, color: '#1a1a2e', marginBottom: 12 }}>Agent 助手</h2>

      <Card style={{ flex: 1, borderRadius: 12, overflow: 'auto', marginBottom: 12 }} styles={{ body: { padding: 16 } }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
            <RobotOutlined style={{ fontSize: 48, marginBottom: 16 }} />
            <p>输入问题开始对话</p>
            <p style={{ fontSize: 12 }}>查询: "Intel销售情况" · 操作: "提交腾讯的订单审批" · 多步: "把所有草稿订单都提交审批"</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ display: 'flex', marginBottom: 12, justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{
              maxWidth: '80%', padding: '10px 14px', borderRadius: 12,
              background: m.role === 'user' ? '#1a1a2e' : m.role === 'system' ? '#f0f5ff' : '#f5f5f5',
              color: m.role === 'user' ? '#fff' : '#333',
            }}>
              <div style={{ whiteSpace: 'pre-wrap', fontSize: 14 }}>{m.content}</div>
              {m.tools?.length > 0 && (
                <div style={{ marginTop: 6, fontSize: 11, color: '#999' }}>
                  工具: {m.tools.map(t => t.tool).join(', ')}
                  {m.tokens > 0 && ` · ${m.tokens} tokens`}
                  {m.duration > 0 && ` · ${m.duration}ms`}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && <div style={{ textAlign: 'center', padding: 12 }}><Spin /></div>}
        <div ref={bottomRef} />
      </Card>

      {/* 修改卡片区域 */}
      {pendingCards.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontWeight: 600, color: '#1a1a2e' }}>
              修改申请 ({processedCards.size}/{pendingCards.length} 已处理)
              {processedCards.size >= pendingCards.length && <CheckCircleOutlined style={{ color: '#52c41a', marginLeft: 8 }} />}
            </span>
            {processedCards.size < pendingCards.length && (
              <Space>
                <Button size="small" danger onClick={rejectAll}>全部拒绝</Button>
                <Button size="small" type="primary" onClick={approveAll} loading={loading}>全部批准</Button>
              </Space>
            )}
          </div>
          {pendingCards.map(card => (
            <ChangeCard key={card.card_id} card={card}
              onApprove={approveCard} onReject={rejectCard}
              disabled={processedCards.has(card.card_id)} />
          ))}
        </div>
      )}

      {/* 输入框 */}
      <div style={{ display: 'flex', gap: 8 }}>
        <Input value={input} onChange={e => setInput(e.target.value)}
          onPressEnter={send} size="large" style={{ borderRadius: 8 }}
          placeholder={hasPending ? "请先处理上方的修改申请..." : "输入问题..."}
          disabled={hasPending} />
        <Button type="primary" size="large" icon={<SendOutlined />}
          onClick={send} loading={loading} disabled={hasPending}
          style={{ borderRadius: 8 }}>发送</Button>
      </div>
    </div>
  );
}
