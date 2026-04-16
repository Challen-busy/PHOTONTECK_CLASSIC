/**
 * Agent 助手 - LLM 对话页面
 * - Markdown 渲染（表格、粗体、代码块等）
 * - SSE 流式思维链（实时显示 Agent 在做什么 + 耗时）
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Card, Input, Button, Tag, Space, message } from 'antd';
import {
  SendOutlined, RobotOutlined, CheckCircleOutlined,
  LoadingOutlined, CheckOutlined, ToolOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { commitTransition } from '../api';
import ChangeCard from '../components/ChangeCard';

/* markdown 在聊天气泡里的样式 */
const mdComponents = {
  table: ({ children }) => (
    <table style={{
      borderCollapse: 'collapse', width: '100%', margin: '8px 0', fontSize: 13,
    }}>{children}</table>
  ),
  th: ({ children }) => (
    <th style={{
      border: '1px solid #d9d9d9', padding: '6px 10px', background: '#fafafa',
      textAlign: 'left', fontWeight: 600,
    }}>{children}</th>
  ),
  td: ({ children }) => (
    <td style={{
      border: '1px solid #d9d9d9', padding: '6px 10px',
    }}>{children}</td>
  ),
  code: ({ inline, children }) => inline
    ? <code style={{ background: '#f0f0f0', padding: '1px 5px', borderRadius: 3, fontSize: 13 }}>{children}</code>
    : <pre style={{ background: '#f5f5f5', padding: 10, borderRadius: 6, overflow: 'auto', fontSize: 13 }}><code>{children}</code></pre>,
  p: ({ children }) => <p style={{ margin: '4px 0' }}>{children}</p>,
};

/* 思维链单步图标 */
function StepIcon({ type, isDone }) {
  if (type === 'tool_call') return <ToolOutlined style={{ color: '#1890ff', fontSize: 12 }} />;
  if (type === 'tool_result') return <CheckOutlined style={{ color: '#52c41a', fontSize: 12 }} />;
  if (isDone) return <CheckOutlined style={{ color: '#52c41a', fontSize: 12 }} />;
  return <LoadingOutlined style={{ color: '#1890ff', fontSize: 12 }} />;
}

export default function AgentChat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [pendingCards, setPendingCards] = useState([]);
  const [processedCards, setProcessedCards] = useState(new Set());
  const [thinkingSteps, setThinkingSteps] = useState([]);
  const bottomRef = useRef(null);
  const abortRef = useRef(null);

  const scrollDown = useCallback(
    () => setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 80),
    [],
  );

  const hasPending = pendingCards.length > 0 && processedCards.size < pendingCards.length;

  /* ---- SSE 流式发送 ---- */
  const send = async () => {
    if (!input.trim() || hasPending) return;
    const q = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: q }]);
    setLoading(true);
    setThinkingSteps([]);
    scrollDown();

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const resp = await fetch('/api/agent/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ query: q }),
        signal: controller.signal,
      });

      if (!resp.ok) {
        const err = await resp.text();
        throw new Error(err || `HTTP ${resp.status}`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          let event;
          try { event = JSON.parse(line.slice(6)); } catch { continue; }

          if (event.type === 'thinking') {
            setThinkingSteps(prev => [...prev, { ...event, isDone: false }]);
            scrollDown();
          } else if (event.type === 'tool_call') {
            setThinkingSteps(prev => [...prev, { ...event, isDone: false }]);
            scrollDown();
          } else if (event.type === 'tool_result') {
            setThinkingSteps(prev => {
              const next = [...prev];
              const idx = next.findLastIndex(s => s.type === 'tool_call' && s.tool === event.tool && !s.isDone);
              if (idx >= 0) next[idx] = { ...next[idx], isDone: true, resultSummary: event.summary, elapsed_ms: event.elapsed_ms };
              return next;
            });
            scrollDown();
          } else if (event.type === 'done') {
            setThinkingSteps(prev => prev.map(s => ({ ...s, isDone: true })));
            setMessages(prev => [...prev, {
              role: 'agent', content: event.response,
              tools: event.tools_called, tokens: event.tokens_used, duration: event.duration_ms,
            }]);
            if (event.cards?.length > 0) {
              setPendingCards(event.cards);
              setProcessedCards(new Set());
            }
          }
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        setMessages(prev => [...prev, { role: 'agent', content: '出错了: ' + e.message }]);
      }
    }

    setLoading(false);
    abortRef.current = null;
    scrollDown();
  };

  /* 组件卸载时中断请求 */
  useEffect(() => () => abortRef.current?.abort(), []);

  /* ---- 卡片操作（不变） ---- */
  const approveCard = async (card) => {
    setLoading(true);
    try {
      const { data } = await commitTransition(card);
      const msg = data.success
        ? `[ok] ${card.transition_name}: ${data.from_state} -> ${data.to_state}`
        : `[fail] ${card.transition_name}: ${data.error}`;
      setMessages(prev => [...prev, { role: 'system', content: msg }]);
      if (data.success) message.success(msg);
      else message.error(msg);
    } catch { message.error('执行失败'); }
    setProcessedCards(prev => new Set([...prev, card.card_id]));
    setLoading(false);
    scrollDown();
  };

  const rejectCard = (card) => {
    setMessages(prev => [...prev, { role: 'system', content: `[x] 已拒绝: ${card.transition_name}` }]);
    setProcessedCards(prev => new Set([...prev, card.card_id]));
    scrollDown();
  };

  const approveAll = async () => {
    for (const card of pendingCards) {
      if (!processedCards.has(card.card_id)) await approveCard(card);
    }
  };
  const rejectAll = () => {
    pendingCards.forEach(card => {
      if (!processedCards.has(card.card_id)) rejectCard(card);
    });
  };

  /* ---- 渲染 ---- */
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
      <h2 style={{ fontSize: 20, fontWeight: 600, color: '#1a1a2e', marginBottom: 12 }}>Agent 助手</h2>

      <Card style={{ flex: 1, borderRadius: 12, overflow: 'auto', marginBottom: 12 }} styles={{ body: { padding: 16 } }}>
        {/* 空态 */}
        {messages.length === 0 && !loading && (
          <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
            <RobotOutlined style={{ fontSize: 48, marginBottom: 16 }} />
            <p>输入问题开始对话</p>
            <p style={{ fontSize: 12 }}>
              查询: "Intel销售情况" / 操作: "提交腾讯的订单审批" / 多步: "把所有草稿订单都提交审批"
            </p>
          </div>
        )}

        {/* 消息列表 */}
        {messages.map((m, i) => (
          <div key={i} style={{
            display: 'flex', marginBottom: 12,
            justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
          }}>
            <div style={{
              maxWidth: '80%', padding: '10px 14px', borderRadius: 12,
              background: m.role === 'user' ? '#1a1a2e' : m.role === 'system' ? '#f0f5ff' : '#f5f5f5',
              color: m.role === 'user' ? '#fff' : '#333',
            }}>
              {m.role === 'user' ? (
                <div style={{ whiteSpace: 'pre-wrap', fontSize: 14 }}>{m.content}</div>
              ) : (
                <div className="agent-md" style={{ fontSize: 14 }}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                    {m.content}
                  </ReactMarkdown>
                </div>
              )}
              {m.tools?.length > 0 && (
                <div style={{ marginTop: 6, fontSize: 11, color: '#999' }}>
                  工具: {m.tools.map(t => t.tool).join(', ')}
                  {m.tokens > 0 && ` / ${m.tokens} tokens`}
                  {m.duration > 0 && ` / ${(m.duration / 1000).toFixed(1)}s`}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* 思维链面板 */}
        {loading && thinkingSteps.length > 0 && (
          <ThinkingPanel steps={thinkingSteps} />
        )}
        {/* 兜底：SSE 还没开始时显示简单加载 */}
        {loading && thinkingSteps.length === 0 && (
          <div style={{ textAlign: 'center', padding: 12, color: '#999' }}>
            <LoadingOutlined style={{ marginRight: 8 }} />连接中...
          </div>
        )}

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
          placeholder={hasPending ? '请先处理上方的修改申请...' : '输入问题...'}
          disabled={hasPending} />
        <Button type="primary" size="large" icon={<SendOutlined />}
          onClick={send} loading={loading} disabled={hasPending}
          style={{ borderRadius: 8 }}>发送</Button>
      </div>
    </div>
  );
}


/* ---- 思维链面板 ---- */
function ThinkingPanel({ steps }) {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  useEffect(() => {
    startRef.current = Date.now();
    const timer = setInterval(() => setElapsed(Date.now() - startRef.current), 100);
    return () => clearInterval(timer);
  }, []);

  return (
    <div style={{
      background: '#fafafa', border: '1px solid #e8e8e8', borderRadius: 10,
      padding: '12px 16px', marginBottom: 8,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 13, color: '#1a1a2e' }}>
          <LoadingOutlined style={{ marginRight: 6 }} />Agent 正在处理...
        </span>
        <Tag color="blue" style={{ margin: 0 }}>{(elapsed / 1000).toFixed(1)}s</Tag>
      </div>
      <div style={{ fontSize: 12, color: '#666' }}>
        {steps.map((s, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '3px 0', opacity: s.isDone ? 0.65 : 1,
          }}>
            <StepIcon type={s.type} isDone={s.isDone} />
            <span>{s.type === 'tool_call' ? s.summary : s.content}</span>
            {s.isDone && s.resultSummary && (
              <span style={{ color: '#52c41a' }}>- {s.resultSummary}</span>
            )}
            <span style={{ marginLeft: 'auto', color: '#bbb', fontSize: 11 }}>
              {(s.elapsed_ms / 1000).toFixed(1)}s
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
