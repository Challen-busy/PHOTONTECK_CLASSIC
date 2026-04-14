import { useEffect, useRef, useState } from 'react';
import { Card, Tabs, Table, Tag, Button, Modal, Form, Input, Select, Space, message, Descriptions, Spin } from 'antd';
import { PlusOutlined, EditOutlined, SendOutlined, RobotOutlined } from '@ant-design/icons';
import api from '../api';

// === 用户管理 ===
function UsersTab() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(false);
  const [form] = Form.useForm();

  const load = () => { api.get('/admin/users').then(r => { setUsers(r.data); setLoading(false); }); };
  useEffect(load, []);

  const create = async () => {
    const v = await form.validateFields();
    await api.post('/admin/users', v);
    message.success('用户已创建');
    setModal(false); form.resetFields(); load();
  };

  return (<>
    <Button type="primary" icon={<PlusOutlined />} onClick={() => setModal(true)} style={{ marginBottom: 12 }}>新增用户</Button>
    <Table dataSource={users} rowKey="id" size="small" loading={loading} columns={[
      { title: 'ID', dataIndex: 'id', width: 50 },
      { title: '用户名', dataIndex: 'username' },
      { title: '姓名', dataIndex: 'full_name' },
      { title: '角色', dataIndex: 'role', render: v => <Tag>{v}</Tag> },
      { title: '公司ID', dataIndex: 'company_id', width: 80 },
      { title: '管理员', dataIndex: 'is_admin', width: 70, render: v => v ? <Tag color="red">是</Tag> : null },
      { title: '状态', dataIndex: 'is_active', width: 60, render: v => v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag> },
    ]} />
    <Modal title="新增用户" open={modal} onCancel={() => setModal(false)} onOk={create}>
      <Form form={form} layout="vertical">
        <Form.Item name="username" label="用户名" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password /></Form.Item>
        <Form.Item name="full_name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="role" label="角色" rules={[{ required: true }]}>
          <Select options={['BOSS','OPERATIONS','FINANCE','SALES_ENGINEER','SALES_ASSISTANT','PRODUCT_MANAGER','PRODUCT_ASSISTANT','LOGISTICS','ADMIN'].map(r => ({ value: r, label: r }))} />
        </Form.Item>
        <Form.Item name="company_id" label="公司ID" rules={[{ required: true }]}><Input type="number" /></Form.Item>
        <Form.Item name="is_admin" label="超级管理员" valuePropName="checked"><input type="checkbox" /></Form.Item>
      </Form>
    </Modal>
  </>);
}

// === 流程管理（节点编辑器，states JSONB 直接编辑）===
function WorkflowsTab() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);  // {wf, state, index}
  const [form] = Form.useForm();

  const load = () => { api.get('/admin/workflows').then(r => { setData(r.data); setLoading(false); }); };
  useEffect(load, []);

  const saveState = async () => {
    const v = await form.validateFields();
    const newState = {
      ...editing.state,
      name: v.name,
      allowed_roles: v.allowed_roles ? v.allowed_roles.split(',').map(s => s.trim()).filter(Boolean) : [],
      editable_fields: v.editable_fields ? v.editable_fields.split(',').map(s => s.trim()).filter(Boolean) : [],
      description: v.description || '',
      hard_rules: v.hard_rules ? v.hard_rules.split('\n').map(s => s.trim()).filter(Boolean) : [],
      custom_html: v.custom_html || '',
    };
    const newStates = [...editing.wf.states];
    newStates[editing.index] = newState;
    await api.patch(`/admin/workflows/${editing.wf.id}/states`, { states: newStates });
    message.success('节点已保存');
    setEditing(null); load();
  };

  return (<>
    {data.map(wf => {
      // 状态码 → 中文名
      const codeToName = Object.fromEntries((wf.states || []).map(s => [s.code, s.name]));
      return (
      <Card key={wf.id} title={<><Tag color="blue">{wf.doc_type}</Tag> {wf.name} v{wf.version} {wf.is_frozen && <Tag color="red">冻结</Tag>}</>}
        size="small" style={{ marginBottom: 16, borderRadius: 12 }}>
        <p style={{ color: '#666', marginBottom: 12 }}>{wf.description}</p>
        <Table dataSource={(wf.states || []).map((s, i) => ({ ...s, _idx: i }))} rowKey="code" size="small" pagination={false} columns={[
          { title: '节点', dataIndex: 'name', render: (v, r) => <><strong>{v}</strong>{r.is_initial && <Tag color="gold" style={{ marginLeft: 4 }}>起</Tag>}{r.is_terminal && <Tag style={{ marginLeft: 4 }}>终</Tag>}</> },
          { title: '角色', dataIndex: 'allowed_roles', render: v => v?.join(', ') || '全部' },
          { title: '用户能填的项', dataIndex: 'editable_fields', render: v => v?.length ? v.join(', ') : <span style={{ color: '#ccc' }}>无（仅推进按钮）</span> },
          { title: '可推进到', dataIndex: 'next', render: v => v?.length ? v.map(n => `${n.label} → ${codeToName[n.to] || n.to}`).join('；') : <span style={{ color: '#ccc' }}>终止</span> },
          { title: '自动校验规则', dataIndex: 'hard_rules', render: v => v?.length ? <span style={{ fontSize: 11 }}>{v.join('；')}</span> : <span style={{ color: '#ccc' }}>无</span> },
          { title: '描述', dataIndex: 'description', ellipsis: true, width: 200, render: v => v || <span style={{ color: '#ccc' }}>无</span> },
          { title: '', key: 'edit', width: 60, render: (_, r) => <Button type="link" size="small" icon={<EditOutlined />} onClick={() => {
            setEditing({ wf, state: r, index: r._idx });
            form.setFieldsValue({
              name: r.name,
              allowed_roles: r.allowed_roles?.join(', ') || '',
              editable_fields: r.editable_fields?.join(', ') || '',
              description: r.description || '',
              hard_rules: (r.hard_rules || []).join('\n'),
              custom_html: r.custom_html || '',
            });
          }}>编辑</Button> },
        ]} />
      </Card>
      );
    })}
    <Modal title={`编辑节点: ${editing?.state?.name || ''}`} open={!!editing} onCancel={() => setEditing(null)} onOk={saveState} width={700}>
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="节点中文名" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="allowed_roles" label="允许角色(逗号分隔，如 FINANCE,BOSS)"><Input /></Form.Item>
        <Form.Item name="editable_fields" label="可编辑字段(逗号分隔)"><Input /></Form.Item>
        <Form.Item name="description" label="节点描述（给Agent看的中文，写业务规则在这）">
          <Input.TextArea rows={6} />
        </Form.Item>
        <Form.Item name="hard_rules" label="自动校验规则（判定式 DSL，每行一条）"
          help={<span style={{ fontSize: 11, lineHeight: 1.6 }}>
            只能读，不能写。可用：doc.字段、entries[i]、lines[i]、sum/len/all/any、lookup/query/count/sum_field。<br/>
            示例：<br/>
            <code>sum(e.debit for e in entries) == sum(e.credit for e in entries)</code><br/>
            <code>len(entries) &gt;= 2</code><br/>
            <code>doc.total_amount &gt; 0</code><br/>
            <code>lookup("accounting_period", id=doc.period_id).status == "OPEN"</code>
          </span>}>
          <Input.TextArea rows={5} placeholder="一行一条表达式。留空 = 没有自动校验，靠 Agent 看描述判断" style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12 }} />
        </Form.Item>
        <Form.Item name="custom_html" label="自定义HTML（留空用通用组件）"><Input.TextArea rows={4} /></Form.Item>
      </Form>
    </Modal>
  </>);
}

// === 知识库 ===
function KnowledgeTab() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(false);
  const [form] = Form.useForm();

  const load = () => { api.get('/knowledge').then(r => { setEntries(r.data); setLoading(false); }); };
  useEffect(load, []);

  const create = async () => {
    const v = await form.validateFields();
    v.applicable_doc_types = v.applicable_doc_types ? v.applicable_doc_types.split(',').map(s => s.trim()) : [];
    await api.post('/admin/knowledge', v);
    message.success('已创建');
    setModal(false); form.resetFields(); load();
  };

  const typeColors = { RULE: 'blue', ALERT: 'orange', GUIDE: 'green', FAQ: 'default' };

  return (<>
    <Button type="primary" icon={<PlusOutlined />} onClick={() => setModal(true)} style={{ marginBottom: 12 }}>新增条目</Button>
    <Table dataSource={entries} rowKey="id" size="small" loading={loading} columns={[
      { title: '类型', dataIndex: 'type', width: 80, render: v => <Tag color={typeColors[v]}>{v}</Tag> },
      { title: '标题', dataIndex: 'title' },
      { title: '内容', dataIndex: 'content', ellipsis: true },
    ]} />
    <Modal title="新增知识库条目" open={modal} onCancel={() => setModal(false)} onOk={create}>
      <Form form={form} layout="vertical">
        <Form.Item name="entry_type" label="类型" rules={[{ required: true }]}>
          <Select options={[{ value: 'RULE', label: '业务规则' }, { value: 'ALERT', label: '预警规则' }, { value: 'GUIDE', label: '操作指南' }, { value: 'FAQ', label: 'FAQ' }]} />
        </Form.Item>
        <Form.Item name="title" label="标题" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="content" label="内容" rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
        <Form.Item name="applicable_doc_types" label="适用单据类型(逗号分隔)"><Input placeholder="如: SALES_ORDER,PURCHASE_ORDER" /></Form.Item>
      </Form>
    </Modal>
  </>);
}

// === 预警 ===
function AlertsTab() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { api.get('/alerts').then(r => { setAlerts(r.data); setLoading(false); }).catch(() => setLoading(false)); }, []);

  const levelColors = { HIGH: 'red', MEDIUM: 'orange', LOW: 'blue' };

  return (
    <Table dataSource={alerts} rowKey={(_, i) => i} size="small" loading={loading}
      locale={{ emptyText: '暂无预警' }}
      columns={[
        { title: '级别', dataIndex: 'level', width: 80, render: v => <Tag color={levelColors[v]}>{v}</Tag> },
        { title: '类型', dataIndex: 'type', width: 150 },
        { title: '内容', dataIndex: 'message' },
      ]} />
  );
}

// === 流程创建Agent ===
function AdminAgentTab() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  const scrollDown = () => setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);

  const send = async () => {
    if (!input.trim()) return;
    const q = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: q }]);
    setLoading(true);
    scrollDown();
    try {
      const { data } = await api.post('/admin/agent/chat', { query: q });
      setMessages(prev => [...prev, {
        role: 'agent', content: data.response,
        tools: data.tools_called, tokens: data.tokens_used, duration: data.duration_ms,
      }]);
    } catch (e) {
      setMessages(prev => [...prev, { role: 'agent', content: '错误: ' + (e.response?.data?.detail || e.message) }]);
    }
    setLoading(false);
    scrollDown();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 260px)' }}>
      <Card style={{ flex: 1, overflow: 'auto', marginBottom: 12, borderRadius: 8 }} styles={{ body: { padding: 12 } }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
            <RobotOutlined style={{ fontSize: 36, marginBottom: 12 }} />
            <p>流程配置助手</p>
            <p style={{ fontSize: 12 }}>试试: "查看所有流程" / "给销售订单加一个总监审批节点" / "列出所有数据表"</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ display: 'flex', marginBottom: 12, justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{
              maxWidth: '85%', padding: '8px 12px', borderRadius: 10,
              background: m.role === 'user' ? '#1a1a2e' : '#f5f5f5',
              color: m.role === 'user' ? '#fff' : '#333', fontSize: 13,
            }}>
              <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
              {m.tools?.length > 0 && (
                <div style={{ marginTop: 6, fontSize: 10, color: '#999' }}>
                  工具: {m.tools.map(t => t.tool).join(', ')} · {m.tokens} tokens · {m.duration}ms
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && <div style={{ textAlign: 'center', padding: 12 }}><Spin /></div>}
        <div ref={bottomRef} />
      </Card>
      <div style={{ display: 'flex', gap: 8 }}>
        <Input value={input} onChange={e => setInput(e.target.value)}
          onPressEnter={send} placeholder="输入指令..." style={{ borderRadius: 6 }} />
        <Button type="primary" icon={<SendOutlined />} onClick={send} loading={loading}>发送</Button>
      </div>
    </div>
  );
}

// === 主页面 ===
export default function Admin() {
  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 600, color: '#1a1a2e', marginBottom: 16 }}>系统管理</h2>
      <Tabs items={[
        { key: 'users', label: '用户管理', children: <UsersTab /> },
        { key: 'knowledge', label: '知识库', children: <KnowledgeTab /> },
        { key: 'alerts', label: '预警检查', children: <AlertsTab /> },
      ]} />
    </div>
  );
}
