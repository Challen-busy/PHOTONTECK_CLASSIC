/**
 * ModelVoucherPickerModal —— 模式凭证（模板）选择弹窗（总账·wave-4，owns by B·前端 PM）
 *
 * 「新建凭证（从模板）」入口：列出本公司模式凭证（query('model_voucher')）→ 选一条 →
 * 点行展开看分录模板（query('model_voucher_line') join account）→ 选「凭证日期」（必填，落期间）→
 * 调 command finance.create_voucher_from_model 建一张 DRAFT 草稿 → 提示并回调跳转录入页填实际金额。
 *
 * 引擎对齐（已 Read models.py 确认）：
 *   ModelVoucher: id/code/name/voucher_word_id/default_description/notes/is_active（含 AuditMixin → company_id）。
 *   ModelVoucherLine: model_voucher_id(FK)/line_number/account_id/account_code/dr_cr(DR|CR)/description/amount(可空)。
 *   建草稿金额取模板默认（空=0），建完跳 /finance/voucher?id={voucher_id} 下钻编辑。
 *
 * 命令触发：经主 agent 接入 api.js 的 executeCommand(command, payload, idempotencyKey?) →
 *   POST /api/commands/execute。本组件只调该方法，不改 api.js。
 */
import { useCallback, useEffect, useState } from 'react';
import {
  App, Modal, Table, Tag, DatePicker, Space, Button, Empty, Input, Descriptions,
} from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { query, executeCommand } from '../../api';
import { MONO, fmtMoney } from './financeHelpers';

export default function ModelVoucherPickerModal({ open, onCancel, onCreated }) {
  const { message } = App.useApp();

  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [kw, setKw] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [voucherDate, setVoucherDate] = useState(dayjs());
  // 展开行分录模板缓存：{ [modelId]: { loading, lines } }
  const [lineCache, setLineCache] = useState({});
  const [creating, setCreating] = useState(false);

  const loadModels = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await query('model_voucher', {
        filters: { is_active: true }, order_by: 'code', limit: 500,
      });
      setModels(data?.data || []);
    } catch (e) {
      message.error('模式凭证加载失败：' + (e.response?.data?.detail || e.message));
      setModels([]);
    } finally { setLoading(false); }
  }, [message]);

  useEffect(() => {
    if (open) {
      setSelectedId(null);
      setKw('');
      setVoucherDate(dayjs());
      loadModels();
    }
  }, [open, loadModels]);

  // 展开行 → 拉该模板的分录模板（join account 取科目码/名）。
  const loadLines = useCallback(async (modelId) => {
    setLineCache((c) => ({ ...c, [modelId]: { loading: true, lines: c[modelId]?.lines || [] } }));
    try {
      const { data } = await query('model_voucher_line', {
        filters: { model_voucher_id: modelId }, order_by: 'line_number', limit: 200,
      });
      const lines = data?.data || [];
      // 关联科目（account_id 优先；为空时回落 account_code 弱引用）。
      const ids = [...new Set(lines.map((l) => l.account_id).filter(Boolean))];
      let acctById = new Map();
      if (ids.length) {
        const { data: ad } = await query('account', { order_by: 'code', limit: 1000 });
        acctById = new Map((ad?.data || []).map((a) => [a.id, a]));
      }
      const joined = lines.map((l) => {
        const a = l.account_id ? acctById.get(l.account_id) : null;
        return {
          ...l,
          _account_code: a?.code || l.account_code || '',
          _account_name: a?.name || (l.account_code ? '（按码弱引用）' : '未指定科目'),
        };
      });
      setLineCache((c) => ({ ...c, [modelId]: { loading: false, lines: joined } }));
    } catch (e) {
      message.error('分录模板加载失败：' + (e.response?.data?.detail || e.message));
      setLineCache((c) => ({ ...c, [modelId]: { loading: false, lines: [] } }));
    }
  }, [message]);

  const onExpand = (expanded, record) => {
    if (expanded && !lineCache[record.id]) loadLines(record.id);
  };

  const filtered = models.filter((m) => {
    if (!kw.trim()) return true;
    const s = kw.trim().toLowerCase();
    return String(m.code || '').toLowerCase().includes(s) || String(m.name || '').toLowerCase().includes(s);
  });

  const doCreate = async () => {
    if (!selectedId) { message.warning('请先选择一个模式凭证模板'); return; }
    if (!voucherDate) { message.warning('请选择凭证日期'); return; }
    setCreating(true);
    try {
      const { data } = await executeCommand('finance.create_voucher_from_model', {
        model_voucher_id: selectedId,
        voucher_date: voucherDate.format('YYYY-MM-DD'),
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '从模板建单失败');
        return;
      }
      const vid = data?.voucher_id;
      message.success(`已按模板建草稿凭证（#${vid}，${data?.lines ?? 0} 条分录），请填实际金额`);
      onCreated?.(vid);
    } catch (e) {
      message.error('从模板建单失败：' + (e.response?.data?.detail || e.message));
    } finally { setCreating(false); }
  };

  const columns = [
    {
      title: '', dataIndex: '_sel', width: 36, align: 'center',
      render: (_, row) => (
        <input type="radio" checked={selectedId === row.id} readOnly
          style={{ cursor: 'pointer' }} onClick={() => setSelectedId(row.id)} />
      ),
    },
    { title: '模板码', dataIndex: 'code', width: 130, render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
    { title: '模板名称', dataIndex: 'name' },
    {
      title: '默认摘要', dataIndex: 'default_description', width: 220,
      render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span>,
    },
  ];

  const lineColumns = [
    { title: '行', dataIndex: 'line_number', width: 44 },
    { title: '科目码', dataIndex: '_account_code', width: 110, render: (v) => <span style={{ fontFamily: MONO }}>{v || '—'}</span> },
    { title: '科目名称', dataIndex: '_account_name', width: 180 },
    {
      title: '方向', dataIndex: 'dr_cr', width: 64,
      render: (v) => <Tag color={v === 'DR' ? 'blue' : 'gold'}>{v === 'DR' ? '借' : '贷'}</Tag>,
    },
    { title: '模板摘要', dataIndex: 'description', render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    {
      title: '默认金额', dataIndex: 'amount', width: 120, align: 'right',
      render: (v) => (v == null || v === '' ? <span style={{ color: '#bfbbb5' }}>录入时填</span> : <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span>),
    },
  ];

  return (
    <Modal
      open={open}
      onCancel={onCancel}
      width={860}
      title="新建凭证 · 选择模式凭证模板"
      footer={
        <Space>
          <span style={{ color: '#777169', fontSize: 12, marginRight: 8 }}>
            建成 DRAFT 草稿（金额取模板默认，空=0），随后跳录入页填实际金额
          </span>
          <Button onClick={onCancel}>取消</Button>
          <Button type="primary" loading={creating} disabled={!selectedId} onClick={doCreate}>
            按模板建草稿
          </Button>
        </Space>
      }
    >
      <Space style={{ marginBottom: 12 }} wrap size={12} align="center">
        <Input
          size="small" allowClear prefix={<SearchOutlined />} value={kw}
          onChange={(e) => setKw(e.target.value)} placeholder="搜索模板码 / 名称"
          style={{ width: 220 }}
        />
        <span style={{ fontSize: 12, color: '#777169' }}>凭证日期</span>
        <DatePicker size="small" value={voucherDate} allowClear={false}
          onChange={setVoucherDate} style={{ width: 150 }} />
      </Space>

      {selectedId && (
        <Descriptions size="small" column={2} style={{ marginBottom: 10 }}
          styles={{ label: { color: '#777169' } }}>
          <Descriptions.Item label="已选模板">
            {(() => { const mv = models.find((x) => x.id === selectedId); return mv ? `${mv.code} ${mv.name}` : '—'; })()}
          </Descriptions.Item>
          <Descriptions.Item label="将建于期间">按所选凭证日期落本公司会计期间</Descriptions.Item>
        </Descriptions>
      )}

      <Table
        size="small"
        rowKey="id"
        loading={loading}
        dataSource={filtered}
        columns={columns}
        pagination={{ pageSize: 8, hideOnSinglePage: true }}
        onRow={(row) => ({ onClick: () => setSelectedId(row.id), style: { cursor: 'pointer' } })}
        rowClassName={(row) => (row.id === selectedId ? 'mv-row-selected' : '')}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本公司暂无模式凭证模板（去「基础资料 / 模式凭证」维护）" /> }}
        expandable={{
          onExpand,
          expandedRowRender: (record) => {
            const cache = lineCache[record.id] || {};
            return (
              <Table
                size="small"
                rowKey="id"
                loading={cache.loading}
                dataSource={cache.lines || []}
                columns={lineColumns}
                pagination={false}
                locale={{ emptyText: '该模板无分录模板（建单将失败，请先维护分录模板）' }}
              />
            );
          },
        }}
      />
    </Modal>
  );
}
