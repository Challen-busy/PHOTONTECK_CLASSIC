/**
 * AccountPicker —— 会计科目 F7 选择器（凭证录入分录网格用，owns by C·前端 PM）
 *
 * 录单惯例（对齐金蝶/用友 F7）：分录「会计科目」格里输入编码/名称即过滤，下拉选定；也可点放大镜开弹层全表搜。
 * 数据源 = 引擎可查表 account（__queryable__，后端按 _company_filter 隔离当前账簿公司），不写死科目表。
 * 默认只列叶子科目（is_leaf，可下挂分录）；非叶子（含明细的父科目）不可挂分录，灰显。
 *
 * 受控：value=account_id，onChange(account_id, accountObj) 回传完整科目对象（供网格带出方向/名称/币别）。
 */
import { useEffect, useMemo, useState } from 'react';
import { Select, Modal, Input, Table, Button, Tag } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { MONO, ACCOUNT_TYPE_LABEL, loadAccounts, getCachedAccounts } from './financeHelpers';

export default function AccountPicker({ value, onChange, disabled }) {
  const [accounts, setAccounts] = useState(getCachedAccounts() || []);
  const [modalOpen, setModalOpen] = useState(false);
  const [kw, setKw] = useState('');

  useEffect(() => {
    let alive = true;
    loadAccounts().then((rows) => { if (alive) setAccounts(rows); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  const options = useMemo(() => accounts.map((a) => ({
    value: a.id,
    label: `${a.code} ${a.name}`,
    disabled: a.is_leaf === false,
    raw: a,
  })), [accounts]);

  const filtered = useMemo(() => {
    const q = kw.trim().toLowerCase();
    if (!q) return accounts;
    return accounts.filter((a) =>
      String(a.code).toLowerCase().includes(q) || String(a.name).toLowerCase().includes(q));
  }, [accounts, kw]);

  const pick = (a) => {
    if (a.is_leaf === false) return; // 非叶不可挂分录
    onChange?.(a.id, a);
    setModalOpen(false);
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <Select
        showSearch
        size="small"
        style={{ flex: 1, minWidth: 120 }}
        value={value ?? undefined}
        placeholder="编码/名称 F7"
        disabled={disabled}
        options={options}
        optionFilterProp="label"
        filterOption={(input, opt) => (opt?.label || '').toLowerCase().includes(input.toLowerCase())}
        onChange={(v, opt) => onChange?.(v, opt?.raw)}
        allowClear
        onClear={() => onChange?.(null, null)}
        popupMatchSelectWidth={280}
      />
      <Button
        size="small" type="text" icon={<SearchOutlined />}
        disabled={disabled}
        onClick={() => setModalOpen(true)}
        title="打开科目表搜索（F7）"
      />
      <Modal
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        title="会计科目（F7）"
        footer={null}
        width={640}
      >
        <Input
          autoFocus
          allowClear
          prefix={<SearchOutlined style={{ color: '#bfbbb5' }} />}
          placeholder="按科目编码 / 名称搜索"
          value={kw}
          onChange={(e) => setKw(e.target.value)}
          style={{ marginBottom: 12 }}
        />
        <Table
          size="small"
          rowKey="id"
          dataSource={filtered}
          pagination={{ pageSize: 12, size: 'small' }}
          onRow={(r) => ({
            onClick: () => pick(r),
            style: { cursor: r.is_leaf === false ? 'not-allowed' : 'pointer', opacity: r.is_leaf === false ? 0.45 : 1 },
          })}
          columns={[
            { title: '编码', dataIndex: 'code', width: 110, render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
            { title: '科目名称', dataIndex: 'name' },
            { title: '类别', dataIndex: 'account_type', width: 80, render: (v) => ACCOUNT_TYPE_LABEL[v] || v },
            {
              title: '方向', dataIndex: 'balance_direction', width: 64,
              render: (v) => <Tag color={v === 'DEBIT' ? 'blue' : 'gold'}>{v === 'DEBIT' ? '借' : '贷'}</Tag>,
            },
            { title: '币别', dataIndex: 'currency', width: 64 },
          ]}
        />
      </Modal>
    </div>
  );
}
