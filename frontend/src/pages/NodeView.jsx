/**
 * 节点独立页面 - 左侧单据列表 + 右侧DocEditor通用编辑器
 * 如果该节点有custom_html → 优先渲染
 */

import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Tag, Button, Space, Empty, Spin, Input, message } from 'antd';
import { ArrowLeftOutlined, SendOutlined, RobotOutlined } from '@ant-design/icons';
import { query, getTransitions, agentChat } from '../api';
import api from '../api';
import DocEditor from '../components/DocEditor';

const tableMap = {
  SALES_ORDER: 'sales_order', PURCHASE_ORDER: 'purchase_order',
  SHIPMENT: 'shipment_request', VOUCHER: 'voucher', VOUCHER_ADJUSTMENT: 'voucher',
  GOODS_RECEIPT: 'goods_receipt', PROJECT: 'project',
  FRAMEWORK_CONTRACT: 'framework_contract',
  ACCOUNTS_RECEIVABLE: 'accounts_receivable', ACCOUNTS_PAYABLE: 'accounts_payable',
  INVENTORY: 'inventory', INVENTORY_VIRTUAL: 'inventory', INVENTORY_COUNT: 'inventory',
  INVENTORY_COSTING: 'inventory_transaction',
};

export default function NodeView() {
  const { workflowId, stateCode } = useParams();
  const navigate = useNavigate();

  const [workflow, setWorkflow] = useState(null);
  const [stateInfo, setStateInfo] = useState(null);
  const [actions, setActions] = useState([]);
  const [docs, setDocs] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [customHtml, setCustomHtml] = useState('');
  const [nodePrompt, setNodePrompt] = useState('');

  // Agent对话
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const chatRef = useRef(null);
  const htmlRef = useRef(null);

  const isInitial = stateInfo?.is_initial;

  const loadData = async () => {
    // 加载流程定义
    const { data: wfs } = await api.get('/workflows');
    const wf = wfs.find(w => w.id === Number(workflowId));
    if (!wf) { navigate('/actions'); return; }
    setWorkflow(wf);

    const state = wf.states?.find(s => s.code === stateCode);
    setStateInfo(state || { code: stateCode, name: stateCode });

    // 加载用户可用操作（当前 state 的 next 列表，按角色过滤）
    const { data: allActions } = await getTransitions();
    const nodeActions = allActions.filter(a => a.doc_type === wf.doc_type && a.from_state === stateCode);
    setActions(nodeActions);

    // 节点描述和自定义HTML 直接来自 state
    if (state) {
      if (state.custom_html) setCustomHtml(state.custom_html);
      if (state.description) setNodePrompt(state.description);
    }

    // 加载该状态的单据
    const table = tableMap[wf.doc_type];
    if (table) {
      try {
        const { data } = await query(table, { filters: { status: stateCode }, limit: 50 });
        setDocs(data.data || []);
        if (data.data?.length > 0) setSelectedDocId(data.data[0].id);
      } catch {}
    }

    setLoading(false);
  };

  useEffect(() => {
    setLoading(true);
    loadData();
  }, [workflowId, stateCode]);

  useEffect(() => {
    if (customHtml && htmlRef.current) {
      htmlRef.current.innerHTML = customHtml;
    }
  }, [customHtml]);

  // Agent对话
  const sendChat = async () => {
    if (!chatInput.trim()) return;
    const q = chatInput.trim();
    setChatInput('');
    setChatMessages(prev => [...prev, { role: 'user', content: q }]);
    setChatLoading(true);
    try {
      const { data } = await agentChat(q);
      setChatMessages(prev => [...prev, { role: 'agent', content: data.response }]);
    } catch (e) {
      setChatMessages(prev => [...prev, { role: 'agent', content: '错误: ' + e.message }]);
    }
    setChatLoading(false);
    setTimeout(() => chatRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  };

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />;

  // === 自定义HTML ===
  if (customHtml) {
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
            {stateInfo?.name} — {workflow?.name}
          </h2>
        </div>
        <Card style={{ borderRadius: 12 }}>
          <div ref={htmlRef} />
        </Card>
      </div>
    );
  }

  // === 通用页面 ===
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          {stateInfo?.name}
        </h2>
        <Tag color="blue">{workflow?.name}</Tag>
        <Tag>{docs.length} 条</Tag>
        {isInitial && <Tag color="gold">起始</Tag>}
      </div>

      {docs.length === 0 ? (
        <Card style={{ borderRadius: 12 }}>
          <Empty description={isInitial ? "当前无单据 — 请在流程页点击【发起新流程】" : "当前无单据在此节点"} />
        </Card>
      ) : (
        <div style={{ display: 'flex', gap: 12 }}>
          {/* 左侧：单据列表 */}
          <Card size="small" style={{ width: 220, flexShrink: 0, borderRadius: 12, height: 'fit-content' }}
            title="单据">
            <div style={{ maxHeight: 600, overflow: 'auto' }}>
              {docs.map(d => (
                <div key={d.id}
                  style={{
                    padding: '8px 10px', borderRadius: 6, marginBottom: 4, cursor: 'pointer',
                    background: selectedDocId === d.id ? '#1a1a2e' : '#fafafa',
                    color: selectedDocId === d.id ? '#fff' : '#333',
                  }}
                  onClick={() => setSelectedDocId(d.id)}>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>
                    #{d.id}
                    {(d.order_number || d.voucher_number || d.shipment_number || d.receipt_number || d.contract_number || d.invoice_number || d.name) &&
                      <span> · {(d.order_number || d.voucher_number || d.shipment_number || d.receipt_number || d.contract_number || d.invoice_number || d.name).slice(0, 15)}</span>
                    }
                  </div>
                  {(d.total_amount != null || d.amount != null) && (
                    <div style={{ fontSize: 11, opacity: 0.8 }}>
                      {Number(d.total_amount ?? d.amount).toLocaleString()} {d.currency || ''}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>

          {/* 中间：DocEditor */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {selectedDocId ? (
              <DocEditor
                docType={workflow.doc_type}
                docId={selectedDocId}
                currentState={stateCode}
                actions={actions}
                onRefresh={loadData}
                nodeDescription={nodePrompt}
              />
            ) : <Empty description="请选择单据" />}
          </div>

          {/* 右侧：Agent */}
          <Card size="small" style={{ width: 320, flexShrink: 0, borderRadius: 12, height: 'fit-content' }}
            title={<span><RobotOutlined /> 节点助手</span>}>
            <div style={{ height: 400, overflow: 'auto', marginBottom: 8 }}>
              {chatMessages.length === 0 && (
                <div style={{ textAlign: 'center', padding: 30, color: '#999', fontSize: 12 }}>
                  问我关于这个节点的问题
                </div>
              )}
              {chatMessages.map((m, i) => (
                <div key={i} style={{
                  padding: '6px 10px', margin: '4px 0', borderRadius: 8, fontSize: 13,
                  background: m.role === 'user' ? '#1a1a2e' : '#f5f5f5',
                  color: m.role === 'user' ? '#fff' : '#333',
                  maxWidth: '90%', marginLeft: m.role === 'user' ? 'auto' : 0,
                  whiteSpace: 'pre-wrap',
                }}>{m.content}</div>
              ))}
              {chatLoading && <Spin size="small" style={{ display: 'block', margin: '8px auto' }} />}
              <div ref={chatRef} />
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              <Input size="small" value={chatInput} onChange={e => setChatInput(e.target.value)}
                onPressEnter={sendChat} placeholder="输入问题..." />
              <Button size="small" type="primary" icon={<SendOutlined />}
                onClick={sendChat} loading={chatLoading} />
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
