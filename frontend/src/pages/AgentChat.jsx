/**
 * Agent 助手 - LLM 对话页面
 * - Markdown 渲染（表格、粗体、代码块等）
 * - SSE 流式思维链（实时显示 Agent 在做什么 + 耗时）
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Card, Input, Button, Space, message } from 'antd';
import {
  SendOutlined, RobotOutlined, CheckCircleOutlined,
  LoadingOutlined, CheckOutlined, ToolOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { commitTransition } from '../api';
import ChangeCard from '../components/ChangeCard';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

/* markdown 在聊天气泡里的样式 —— 克制的表格线、暖石代码底 */
const mdComponents = {
  table: ({ children }) => (
    <table style={{
      borderCollapse: 'collapse', width: '100%', margin: '8px 0', fontSize: 13,
    }}>{children}</table>
  ),
  th: ({ children }) => (
    <th style={{
      border: '1px solid rgba(0,0,0,0.08)',
      padding: '6px 10px',
      background: '#f5f2ef',
      textAlign: 'left', fontWeight: 500,
      letterSpacing: '0.02em',
      color: '#000',
    }}>{children}</th>
  ),
  td: ({ children }) => (
    <td style={{
      border: '1px solid rgba(0,0,0,0.08)',
      padding: '6px 10px',
    }}>{children}</td>
  ),
  code: ({ inline, children }) => inline
    ? <code style={{
        background: '#f5f2ef',
        padding: '1px 6px',
        borderRadius: 4,
        fontSize: 12.5,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
        color: '#000',
      }}>{children}</code>
    : <pre style={{
        background: '#f5f2ef',
        padding: 12,
        borderRadius: 10,
        overflow: 'auto',
        fontSize: 12.5,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
        border: '1px solid rgba(0,0,0,0.05)',
      }}><code>{children}</code></pre>,
  p: ({ children }) => <p style={{ margin: '4px 0' }}>{children}</p>,
};

/* 思维链单步图标 —— 中性色系 */
function StepIcon({ type, isDone }) {
  if (type === 'tool_call') return <ToolOutlined style={{ color: '#4e4e4e', fontSize: 12 }} />;
  if (type === 'tool_result') return <CheckOutlined style={{ color: '#1f8f3a', fontSize: 12 }} />;
  if (isDone) return <CheckOutlined style={{ color: '#1f8f3a', fontSize: 12 }} />;
  return <LoadingOutlined style={{ color: '#4e4e4e', fontSize: 12 }} />;
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
      <h2 style={{
        fontSize: 28,
        fontWeight: 300,
        letterSpacing: '-0.01em',
        color: '#000',
        margin: '0 0 16px',
        lineHeight: 1.15,
      }}>
        Agent 助手
      </h2>

      <Card
        style={{
          flex: 1, borderRadius: 16, overflow: 'auto', marginBottom: 12,
          boxShadow: CARD_SHADOW, border: 'none',
        }}
        styles={{ body: { padding: 20 } }}
      >
        {/* 空态 */}
        {messages.length === 0 && !loading && (
          <div style={{ textAlign: 'center', padding: 80, color: '#777169' }}>
            <div style={{
              width: 72, height: 72, margin: '0 auto 20px',
              borderRadius: 20,
              background: '#f5f2ef',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <RobotOutlined style={{ fontSize: 36, color: '#4e4e4e' }} />
            </div>
            <div style={{
              fontSize: 18, fontWeight: 300, color: '#000',
              letterSpacing: '-0.01em', marginBottom: 8,
            }}>
              输入问题开始对话
            </div>
            <p style={{ fontSize: 13, margin: 0, letterSpacing: '0.01em' }}>
              查询: "Intel销售情况" / 操作: "提交腾讯的订单审批" / 多步: "把所有草稿订单都提交审批"
            </p>
          </div>
        )}

        {/* 消息列表 */}
        {messages.map((m, i) => {
          const isUser = m.role === 'user';
          const isSystem = m.role === 'system';
          return (
            <div key={i} style={{
              display: 'flex', marginBottom: 14,
              justifyContent: isUser ? 'flex-end' : 'flex-start',
            }}>
              <div style={{
                maxWidth: '80%',
                padding: '12px 16px',
                borderRadius: 16,
                background: isUser
                  ? '#000000'
                  : isSystem
                    ? 'rgba(245, 242, 239, 0.6)'
                    : '#ffffff',
                color: isUser ? '#ffffff' : '#000000',
                boxShadow: isUser
                  ? 'none'
                  : isSystem
                    ? 'rgba(0,0,0,0.04) 0px 0px 0px 1px'
                    : CARD_SHADOW,
                letterSpacing: '0.01em',
                lineHeight: 1.5,
              }}>
                {isUser ? (
                  <div style={{ whiteSpace: 'pre-wrap', fontSize: 14 }}>{m.content}</div>
                ) : (
                  <div className="agent-md" style={{ fontSize: 14 }}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                      {m.content}
                    </ReactMarkdown>
                  </div>
                )}
                {m.tools?.length > 0 && (
                  <div style={{
                    marginTop: 8,
                    fontSize: 11,
                    color: '#777169',
                    borderTop: '1px solid rgba(0,0,0,0.05)',
                    paddingTop: 6,
                    letterSpacing: '0.02em',
                  }}>
                    工具: {m.tools.map(t => t.tool).join(', ')}
                    {m.tokens > 0 && ` / ${m.tokens} tokens`}
                    {m.duration > 0 && ` / ${(m.duration / 1000).toFixed(1)}s`}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* 思维链面板 */}
        {loading && thinkingSteps.length > 0 && (
          <ThinkingPanel steps={thinkingSteps} />
        )}
        {/* 兜底：SSE 还没开始时显示简单加载 */}
        {loading && thinkingSteps.length === 0 && (
          <div style={{ textAlign: 'center', padding: 16, color: '#777169', fontSize: 13 }}>
            <LoadingOutlined style={{ marginRight: 8 }} />连接中...
          </div>
        )}

        <div ref={bottomRef} />
      </Card>

      {/* 修改卡片区域 */}
      {pendingCards.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            marginBottom: 10,
          }}>
            <span style={{ fontWeight: 500, color: '#000', letterSpacing: '0.01em' }}>
              修改申请
              <span style={{ color: '#777169', marginLeft: 6 }}>
                ({processedCards.size}/{pendingCards.length} 已处理)
              </span>
              {processedCards.size >= pendingCards.length && (
                <CheckCircleOutlined style={{ color: '#1f8f3a', marginLeft: 8 }} />
              )}
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
      <div style={{ display: 'flex', gap: 10 }}>
        <Input
          value={input}
          onChange={e => setInput(e.target.value)}
          onPressEnter={send}
          size="large"
          style={{ borderRadius: 12, flex: 1 }}
          placeholder={hasPending ? '请先处理上方的修改申请...' : '输入问题...'}
          disabled={hasPending}
        />
        <Button
          type="primary"
          size="large"
          icon={<SendOutlined />}
          onClick={send}
          loading={loading}
          disabled={hasPending}
        >
          发送
        </Button>
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
      background: 'rgba(245, 242, 239, 0.5)',
      border: '1px solid rgba(0, 0, 0, 0.05)',
      borderRadius: 12,
      padding: '14px 16px',
      marginBottom: 12,
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 10,
      }}>
        <span style={{
          fontWeight: 500, fontSize: 13, color: '#000',
          letterSpacing: '0.01em',
        }}>
          <LoadingOutlined style={{ marginRight: 6, color: '#4e4e4e' }} />Agent 正在处理...
        </span>
        <span style={{
          fontFamily: 'ui-monospace, monospace',
          fontSize: 12, color: '#4e4e4e',
          background: '#ffffff', padding: '2px 8px',
          borderRadius: 4,
          boxShadow: 'rgba(0,0,0,0.04) 0px 0px 0px 1px',
        }}>
          {(elapsed / 1000).toFixed(1)}s
        </span>
      </div>
      <div style={{ fontSize: 12, color: '#4e4e4e', letterSpacing: '0.01em' }}>
        {steps.map((s, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '4px 0', opacity: s.isDone ? 0.6 : 1,
          }}>
            <StepIcon type={s.type} isDone={s.isDone} />
            <span>{s.type === 'tool_call' ? s.summary : s.content}</span>
            {s.isDone && s.resultSummary && (
              <span style={{ color: '#1f8f3a' }}>- {s.resultSummary}</span>
            )}
            <span style={{
              marginLeft: 'auto', color: '#bfbbb5', fontSize: 11,
              fontFamily: 'ui-monospace, monospace',
            }}>
              {(s.elapsed_ms / 1000).toFixed(1)}s
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
