/**
 * AccountMasterPage —— 会计科目表维护（总账·配账主数据 wave-3，前端A·科目+期初 PM）
 *
 * 落 UX 律 14（台账→详情抽屉不跳页→动作按钮），但科目本质是**树**（五大类 + parent_id 自引用层级），
 * MasterDataPage 的扁平 ProTable 不便表达层级，故本页基于 query('account') 自建科目树 + 抽屉表单，
 * 提交照搬 MasterDataPage.onFinish 范式走引擎唯一写入路径 /api/transition（doc_type=ACCOUNT）：
 *   - 建档：doc_id=null + field_updates（code/name/account_type/balance_direction/parent_id/currency/...）
 *   - 改档：doc_id=该科目 id + field_updates
 * 绝不伪造成功、绝不调非 transition 写端点。引擎 ACCOUNT 单态 ACTIVE 自环编辑状态机由
 * scripts/seed_master_gl.py 种（is_published+is_active），无活跃流程时引擎如实报错、本页弹出不掩盖。
 *
 * 树构建：
 *   - 优先按 parent_id 建真实层级树；顶层（parent_id 空）的科目挂到其 account_type 的分类组节点下。
 *   - account_type 五大类（资产/负债/权益/收入/费用/成本）作为根分组节点（虚拟节点，不可编辑）。
 *   - 「新增子科目」从某科目派生：带出 parent_id + 继承 account_type/balance_direction/currency。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Drawer, Form, Input, Select, Switch, Space, Table, Tag, Tooltip } from 'antd';
import { PlusOutlined, EditOutlined, ReloadOutlined, HistoryOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { query, transition } from '../../../api';
import { MONO, ACCOUNT_TYPE_LABEL, clearAccountCache } from '../financeHelpers';

const DOC_TYPE = 'ACCOUNT';

// 五大类（含成本）分类组顺序与中文标签（对齐 Account.account_type / financeHelpers.ACCOUNT_TYPE_LABEL）。
const ACCOUNT_TYPES = ['ASSET', 'LIABILITY', 'EQUITY', 'COGS', 'EXPENSE', 'REVENUE'];
const ACCOUNT_TYPE_OPTIONS = ACCOUNT_TYPES.map((v) => ({ label: `${ACCOUNT_TYPE_LABEL[v]}（${v}）`, value: v }));
// 五大类默认余额方向（建档时按类别预填，可改）。
const TYPE_DEFAULT_DIR = {
  ASSET: 'DEBIT', EXPENSE: 'DEBIT', COGS: 'DEBIT',
  LIABILITY: 'CREDIT', EQUITY: 'CREDIT', REVENUE: 'CREDIT',
};
const DIR_OPTIONS = [
  { label: '借方（DEBIT）', value: 'DEBIT' },
  { label: '贷方（CREDIT）', value: 'CREDIT' },
];
const CURRENCY_OPTIONS = ['CNY', 'HKD', 'USD', 'EUR'].map((c) => ({ label: c, value: c }));

function DirTag({ value }) {
  if (!value) return <span style={{ color: '#bfbbb5' }}>—</span>;
  return <Tag color={value === 'DEBIT' ? 'blue' : 'gold'}>{value === 'DEBIT' ? '借' : '贷'}</Tag>;
}

/** 把扁平科目行 → 树（account_type 分组根 + parent_id 真实层级）。 */
function buildTree(rows) {
  const byId = new Map();
  rows.forEach((r) => byId.set(r.id, { ...r, children: [] }));
  // 分类组虚拟根（key 形如 grp:ASSET）
  const groups = new Map();
  ACCOUNT_TYPES.forEach((t) => {
    groups.set(t, { key: `grp:${t}`, _group: t, name: ACCOUNT_TYPE_LABEL[t], children: [] });
  });

  byId.forEach((node) => {
    if (node.parent_id != null && byId.has(node.parent_id)) {
      byId.get(node.parent_id).children.push(node);
    } else {
      const grp = groups.get(node.account_type);
      (grp ? grp.children : (groups.get('ASSET').children)).push(node);
    }
  });

  // 组内 + 层级内按 code 排序
  const sortRec = (arr) => {
    arr.sort((a, b) => String(a.code ?? '').localeCompare(String(b.code ?? '')));
    arr.forEach((n) => n.children && sortRec(n.children));
  };
  const tree = ACCOUNT_TYPES
    .map((t) => groups.get(t))
    .filter((g) => g.children.length > 0);
  tree.forEach((g) => sortRec(g.children));
  // 清掉空 children 数组让叶子不显示展开箭头
  const prune = (arr) => arr.forEach((n) => {
    if (n.children && n.children.length === 0) delete n.children;
    else if (n.children) prune(n.children);
  });
  prune(tree);
  return tree;
}

export default function AccountMasterPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState(null);   // 当前编辑/查看的科目（null=新建）
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();
  const [writeBlocked, setWriteBlocked] = useState(false);  // 引擎无活跃 ACCOUNT 流程时置真 → 横幅提示

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await query('account', { order_by: 'code', limit: 2000 });
      setRows(data?.data || []);
    } catch (e) {
      message.error(e.response?.data?.detail || '加载科目表失败');
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  const tree = useMemo(() => buildTree(rows), [rows]);

  // 科目映射（id→行）供「新增子科目」继承父属性。
  const byId = useMemo(() => {
    const m = new Map();
    rows.forEach((r) => m.set(r.id, r));
    return m;
  }, [rows]);
  // parent 选择器候选（全部科目，code+name；建档时排除自身/子孙避免成环——交由后端兜底，前端仅排自身）
  const parentOptions = useMemo(
    () => rows.map((r) => ({ label: `${r.code} ${r.name}`, value: r.id })),
    [rows]
  );

  const openNew = useCallback((parent) => {
    setEditing(null);
    const init = parent
      ? {
          account_type: parent.account_type,
          balance_direction: parent.balance_direction,
          currency: parent.currency || 'CNY',
          parent_id: parent.id,
          level: (parent.level || 1) + 1,
          is_leaf: true,
          is_active: true,
        }
      : { account_type: 'ASSET', balance_direction: 'DEBIT', currency: 'CNY', level: 1, is_leaf: true, is_active: true };
    form.resetFields();
    form.setFieldsValue(init);
    setDrawerOpen(true);
  }, [form]);

  const openEdit = useCallback((row) => {
    setEditing(row);
    form.resetFields();
    form.setFieldsValue({
      code: row.code, name: row.name, account_type: row.account_type,
      balance_direction: row.balance_direction, parent_id: row.parent_id ?? undefined,
      currency: row.currency || 'CNY', level: row.level, is_leaf: row.is_leaf,
      is_active: row.is_active,
    });
    setDrawerOpen(true);
  }, [form]);

  // 类别变化时联动默认余额方向（仅新建/未手改时给个合理默认）。
  const onTypeChange = (t) => {
    if (!editing) form.setFieldValue('balance_direction', TYPE_DEFAULT_DIR[t] || 'DEBIT');
  };

  // 提交 → 引擎唯一写入路径 /api/transition（照 MasterDataPage.onFinish 范式）。
  const onSubmit = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const field_updates = {};
    for (const [k, v] of Object.entries(values)) {
      if (v === undefined || v === '') continue;
      field_updates[k] = v;
    }
    setSubmitting(true);
    try {
      const { data } = await transition({
        doc_type: DOC_TYPE,
        doc_id: editing?.id ?? null,
        to_state: 'ACTIVE',
        field_updates,
        comment: editing?.id ? '科目改档' : '科目建档',
      });
      if (data?.success === false) {
        const err = data.error || data.detail || '保存失败（引擎拒绝）';
        message.error(err);
        if (/没有活跃的流程定义|no active|流程定义/.test(err)) setWriteBlocked(true);
        return;
      }
      message.success(editing?.id ? '科目已更新' : '科目已建档');
      clearAccountCache();          // 让凭证录入 F7 等共享缓存重取
      setDrawerOpen(false);
      load();
    } catch (e) {
      const err = e.response?.data?.detail || '保存失败（引擎写路径未就绪）';
      message.error(err);
      if (/没有活跃的流程定义|no active|流程定义/.test(err)) setWriteBlocked(true);
    } finally {
      setSubmitting(false);
    }
  };

  const columns = [
    {
      title: '科目编码 / 名称', dataIndex: 'name', key: 'name',
      render: (_, r) => {
        if (r._group) {
          return <span style={{ fontWeight: 600, color: '#000' }}>{r.name}<span style={{ color: '#bfbbb5', fontWeight: 400, marginLeft: 8 }}>{r._group}</span></span>;
        }
        return (
          <span>
            <span style={{ fontFamily: MONO, color: '#1f4e79', marginRight: 8 }}>{r.code}</span>
            <span style={{ color: '#000' }}>{r.name}</span>
            {r.is_leaf === false && <Tag style={{ marginLeft: 8 }} color="default">非叶</Tag>}
          </span>
        );
      },
    },
    {
      title: '类别', dataIndex: 'account_type', width: 110,
      render: (v, r) => (r._group ? null : (ACCOUNT_TYPE_LABEL[v] || v)),
    },
    {
      title: '余额方向', dataIndex: 'balance_direction', width: 100,
      render: (v, r) => (r._group ? null : <DirTag value={v} />),
    },
    { title: '币别', dataIndex: 'currency', width: 80, render: (v, r) => (r._group ? null : (v || '—')) },
    {
      title: '启用', dataIndex: 'is_active', width: 70,
      render: (v, r) => {
        if (r._group) return null;
        return v
          ? <Tag color="green">启用</Tag>
          : <Tag color="default">停用</Tag>;
      },
    },
    {
      title: '操作', key: '_action', width: 200,
      render: (_, r) => {
        if (r._group) {
          return (
            <Button type="link" size="small" icon={<PlusOutlined />} onClick={() => openNew({ account_type: r._group, balance_direction: TYPE_DEFAULT_DIR[r._group], currency: 'CNY', level: 0 })}>
              新增一级科目
            </Button>
          );
        }
        return (
          <Space size={2}>
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
            <Tooltip title="新增下级科目（继承类别/方向/币别）">
              <Button type="link" size="small" icon={<PlusOutlined />} onClick={() => openNew(byId.get(r.id))}>子科目</Button>
            </Tooltip>
            <Button type="link" size="small" icon={<HistoryOutlined />}
              onClick={() => navigate(`/history/${DOC_TYPE}/${r.id}`)}>历史</Button>
          </Space>
        );
      },
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
            科目表
          </h2>
          <span style={{ color: '#777169', fontSize: 13 }}>财务 / 总账 · 配账主数据 · 引擎表 <code>account</code>（五大类 + parent 层级，按当前账簿公司隔离）</span>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openNew(null)}>新增科目</Button>
        </Space>
      </div>

      <Alert
        type={writeBlocked ? 'warning' : 'info'} showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        message={writeBlocked ? '科目写路径未就绪（引擎无活跃 ACCOUNT 流程）' : '科目建档/改档走引擎唯一写入路径 /api/transition（ACCOUNT 单态 ACTIVE 状态机）'}
        description={
          writeBlocked
            ? '引擎返回「没有活跃的流程定义」。需后端确保 scripts/seed_master_gl.py 已种 ACCOUNT 的 WorkflowDefinition（is_published+is_active）。本页不伪造成功。'
            : '树按五大类分组 + parent_id 层级展示；建档/改档由引擎 execute_transition 写入，无活跃流程时引擎如实报错、本页弹出不掩盖。非叶科目（含明细的父科目）不可挂分录。'
        }
      />

      <Table
        rowKey={(r) => r._group ? r.key : r.id}
        loading={loading}
        columns={columns}
        dataSource={tree}
        pagination={false}
        size="small"
        expandable={{ defaultExpandAllRows: false }}
        scroll={{ y: 'calc(100vh - 340px)' }}
      />

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={520}
        title={editing?.id ? `编辑科目 · ${editing.code} ${editing.name}` : '新增科目'}
        extra={
          <Space>
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button type="primary" loading={submitting} onClick={onSubmit}>保存</Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item name="code" label="科目编码" rules={[{ required: true, message: '请填写科目编码' }]}>
            <Input placeholder="如 1001 / 100101" disabled={!!editing?.id} />
          </Form.Item>
          <Form.Item name="name" label="科目名称" rules={[{ required: true, message: '请填写科目名称' }]}>
            <Input placeholder="如 库存现金" />
          </Form.Item>
          <Form.Item name="account_type" label="科目类别（五大类）" rules={[{ required: true, message: '请选择科目类别' }]}>
            <Select options={ACCOUNT_TYPE_OPTIONS} onChange={onTypeChange} />
          </Form.Item>
          <Form.Item name="balance_direction" label="余额方向" rules={[{ required: true, message: '请选择余额方向' }]}>
            <Select options={DIR_OPTIONS} />
          </Form.Item>
          <Form.Item name="parent_id" label="上级科目（parent_id，留空=一级科目）">
            <Select
              allowClear showSearch optionFilterProp="label"
              placeholder="选择上级科目"
              options={parentOptions.filter((o) => o.value !== editing?.id)}
            />
          </Form.Item>
          <Form.Item name="currency" label="核算币别">
            <Select options={CURRENCY_OPTIONS} />
          </Form.Item>
          <Form.Item name="level" label="级次（level）" tooltip="一般由编码层级决定；新增子科目自动按父级 +1 预填">
            <Input type="number" min={1} />
          </Form.Item>
          <Form.Item name="is_leaf" label="叶子科目（可挂分录）" valuePropName="checked" tooltip="非叶科目为含明细的父科目，凭证不可直接挂分录">
            <Switch checkedChildren="叶子" unCheckedChildren="非叶" />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
          <Alert
            type="info" showIcon style={{ borderRadius: 8 }}
            message="辅助核算"
            description="科目级辅助核算（往来对象/部门/项目）维度在「辅助核算维度」与「核算维度数据」页维护；本页录入科目主属性，分录辅助核算在凭证录入屏按维度落 VoucherEntry.aux_*。"
          />
        </Form>
      </Drawer>
    </div>
  );
}
