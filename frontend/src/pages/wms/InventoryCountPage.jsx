/**
 * InventoryCountPage —— 盘点单（月度 27 号，实物 vs 系统，PRD 03b 页面 6）⭐
 *
 * 落 UX 律 14：台账(BizTable) → 详情抽屉(BizDrawerForm，不跳页) → 动作按钮。
 *   - 台账：BizTable over WMS counts API（getWmsCounts；冻结 盘点单号/状态；status 药丸 DRAFT/IN_PROGRESS/SUBMITTED/ADJUSTED）
 *   - 抽屉：盘点明细网格 —— 扫码盘点（入仓编号扫码带出系统数量），录实际数 → 自动算「差异=实际−系统」，
 *           差异行标红 + 调查备注必填（差异行未填备注无法提交，前端硬拦 + 后端校验）。
 *   - 分性质同页视图：走流程/待處理/貨/樣品/帶貨/RMA/NG Tab（aggregate 不拆页；goods_nature 从 inventory join 带出）。
 *   - 动作：录入(逐行 updateWmsCountLine) / 提交(submitWmsCount) / 生成调整单(adjustWmsCount) / 关闭。
 *
 * ⚠️ 引擎实况(已勘 + 遵 quirk)：INVENTORY_COUNT doc_type 误声明在 Inventory 模型上(__doc_types__)，
 *    但盘点单据真相落在独立 inventory_count / inventory_count_line 表，且已有专用命令
 *    create_inventory_count / update_inventory_count_line / submit_inventory_count / adjust_inventory_count
 *    经 /api/wms/counts* 暴露。本页**走这条现有命令路径**(唯一写入路径 Command→Workflow→Domain)，
 *    绝不对 INVENTORY_COUNT doc_type 发 /api/transition(会误写 Inventory 行)。保守不改映射层。
 *    建单按现有 create_inventory_count(建盘点单+按库存生成行)，无需新 doc_type/状态机。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Empty, Input, Tabs, Tag, Tooltip } from 'antd';
import { PlusOutlined, ScanOutlined } from '@ant-design/icons';
import { ProFormSelect, ProFormText } from '@ant-design/pro-components';
import { BizTable, BizDrawerForm } from '../../components/biz';
import {
  query, getWmsCounts, createWmsCount, getWmsCountDetail,
  updateWmsCountLine, submitWmsCount, generateAdjustmentFromCount,
} from '../../api';
import { StatusPillInline } from './StatusPill';

const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';

// 盘点单状态过滤候选（WMS counts 命令真实 code）
const STATUS_ENUM = [
  { text: 'DRAFT 草稿', value: 'DRAFT' },
  { text: 'IN_PROGRESS 录入中', value: 'IN_PROGRESS' },
  { text: 'SUBMITTED 已提交', value: 'SUBMITTED' },
  { text: 'ADJUSTED 已调整', value: 'ADJUSTED' },
];
const EDITABLE_STATES = new Set(['DRAFT', 'IN_PROGRESS']);

// 分性质 Tab（PRD 盘点表 7 sheet；goods_nature 从 inventory join 带出）
const NATURE_TABS = [
  { key: 'all', label: '盘点表(全部)' },
  { key: '走流程', label: '走流程' },
  { key: '待處理', label: '待處理' },
  { key: '貨', label: '貨' },
  { key: '樣品', label: '樣品' },
  { key: '帶貨', label: '帶貨' },
  { key: 'RMA', label: 'RMA' },
  { key: 'NG', label: 'NG' },
];

export default function InventoryCountPage() {
  const { message } = App.useApp();
  const [detail, setDetail] = useState(null);       // 当前盘点单头
  const [lines, setLines] = useState([]);           // 盘点明细行（含 _goods_nature 带出）
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [natureTab, setNatureTab] = useState('all');
  const [scanMode, setScanMode] = useState(false);
  const [scanText, setScanText] = useState('');
  const [whOptions, setWhOptions] = useState([]);

  // 仓库候选（建盘点单选范围）
  useEffect(() => {
    query('warehouse', { limit: 100 }).then(({ data }) => {
      setWhOptions((data?.data || []).map((w) => ({ label: w.name || w.code || `#${w.id}`, value: w.id })));
    }).catch(() => setWhOptions([]));
  }, []);

  // 台账：WMS counts API（盘点单为低频月度小表，全量拉回，状态走列头客户端筛选）
  const tableRequest = useCallback(async () => {
    try {
      const { data } = await getWmsCounts();
      const rows = data?.data || [];
      return { data: rows, success: true, total: rows.length };
    } catch (e) {
      message.error(e.response?.data?.detail || '加载盘点单失败');
      return { data: [], success: false, total: 0 };
    }
  }, [message]);

  // 打开盘点单：拉明细 + join goods_nature
  const loadDetail = useCallback(async (countId) => {
    if (!countId) { setDetail(null); setLines([]); return; }
    try {
      const { data } = await getWmsCountDetail(countId);
      // join goods_nature：本公司 inventory 批量带出建 id→性质 映射（/api/query 行级隔离 + 仅标量过滤，
      // 故一次拉本公司库存做映射，不传 list 过滤）。分性质视图用。
      let natureById = {};
      try {
        const { data: invData } = await query('inventory', { order_by: '-id', limit: 500 });
        for (const inv of (invData?.data || [])) natureById[inv.id] = inv.goods_nature;
      } catch { natureById = {}; }
      setDetail({
        id: data.id, count_number: data.count_number, warehouse: data.warehouse,
        warehouse_id: data.warehouse_id, planned_date: data.planned_date,
        status: data.status, notes: data.notes,
      });
      setLines((data.lines || []).map((l) => ({
        ...l,
        _goods_nature: natureById[l.inventory_id] || '',
        _counted_input: l.counted_quantity,
        _notes_input: l.notes || '',
      })));
    } catch (e) {
      message.error(e.response?.data?.detail || '加载盘点明细失败');
    }
  }, [message]);

  const openDetail = useCallback(async (row) => {
    setNatureTab('all');
    setDrawerOpen(true);
    await loadDetail(row.id);
  }, [loadDetail]);

  // 建盘点单（create_inventory_count：按库存生成盘点行）
  const onCreate = useCallback(async (values) => {
    try {
      const { data } = await createWmsCount({
        warehouse_id: values.warehouse_id || null,
        planned_date: values.planned_date || null,
        notes: values.notes || '',
      });
      message.success(`已建盘点单 ${data.count_number}，生成 ${data.line_count} 盘点行`);
      setReloadKey((k) => k + 1);
      await openDetail({ id: data.id });
      return true;
    } catch (e) {
      message.error(e.response?.data?.detail || '建盘点单失败（当前范围可能没有可盘点库存）');
      return false;
    }
  }, [message, openDetail]);

  // 录一行实际数（updateWmsCountLine：后端自动算差异 + 置 MATCH/DIFF）
  const saveLine = useCallback(async (line) => {
    if (!detail?.id) return;
    if (line._counted_input == null || line._counted_input === '') {
      message.warning('请先录入实际数'); return;
    }
    const isDiff = Number(line._counted_input) !== Number(line.system_quantity || 0);
    if (isDiff && !String(line._notes_input || '').trim()) {
      message.warning('差异行调查备注必填（实际≠系统）'); return;
    }
    setBusy(true);
    try {
      await updateWmsCountLine(detail.id, line.id, {
        counted_quantity: line._counted_input,
        notes: line._notes_input || '',
      });
      message.success(`第 ${line.id} 行已录入`);
      await loadDetail(detail.id);
    } catch (e) {
      message.error(e.response?.data?.detail || '录入失败');
    } finally {
      setBusy(false);
    }
  }, [detail, loadDetail, message]);

  // 扫码盘点：扫入仓编号 → 定位明细行（带出系统数量），聚焦录实际数
  const onScan = useCallback((raw) => {
    const inbound = (raw || '').trim();
    if (!inbound) return;
    setScanText('');
    const hit = lines.find((l) => l.inbound_number === inbound);
    if (!hit) {
      message.warning(`入仓编号「${inbound}」不在本盘点单明细中`);
      return;
    }
    // 实际数 +1（扫一件计一件，累加；可在格内改写为精确数）
    setLines((prev) => prev.map((l) => (l.id === hit.id
      ? { ...l, _counted_input: Number(l._counted_input || 0) + 1 }
      : l)));
    message.success(`已计数 ${inbound}（系统数 ${hit.system_quantity}）`);
  }, [lines, message]);

  // 提交盘点（submitWmsCount：校验全部录入）
  const onSubmit = useCallback(async () => {
    if (!detail?.id) return;
    // 前端先拦差异行缺备注
    const diffNoNote = lines.filter((l) => (
      l.counted_quantity != null
      && Number(l.counted_quantity) !== Number(l.system_quantity || 0)
      && !String(l.notes || '').trim()
    ));
    if (diffNoNote.length) {
      message.error(`有 ${diffNoNote.length} 个差异行未填调查备注，请先逐行录入备注再提交`);
      return;
    }
    setBusy(true);
    try {
      await submitWmsCount(detail.id);
      message.success('盘点单已提交');
      setReloadKey((k) => k + 1);
      await loadDetail(detail.id);
    } catch (e) {
      message.error(e.response?.data?.detail || '提交失败');
    } finally {
      setBusy(false);
    }
  }, [detail, lines, loadDetail, message]);

  // 生成库存调整单草稿（决策⑧：盘点差异→STOCK_ADJUSTMENT 草稿，财务核原因后 confirm→post
  // 才调结存+推金蝶；本步不直接改库存，避免运营绕过财务复核闸）。一盘一调幂等。
  const onAdjust = useCallback(async () => {
    if (!detail?.id) return;
    setBusy(true);
    try {
      const { data } = await generateAdjustmentFromCount(detail.id);
      message.success(data.generated === false
        ? `该盘点已生成过库存调整单 ${data.adjustment_number}，请到「库存调整单」页财务核原因后过账`
        : `已生成库存调整单草稿 ${data.adjustment_number}，请到「库存调整单」页由财务核差异原因后过账推金蝶`);
      setReloadKey((k) => k + 1);
      await loadDetail(detail.id);
    } catch (e) {
      message.error(e.response?.data?.detail || '生成调整单失败（仅已提交盘点、且有差异可生成）');
    } finally {
      setBusy(false);
    }
  }, [detail, loadDetail, message]);

  // 台账列
  const columns = useMemo(() => [
    { title: '盘点单号', dataIndex: 'count_number', width: 200, fixed: 'left',
      render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
    { title: '状态', dataIndex: 'status', width: 140,
      filters: STATUS_ENUM.map((o) => ({ text: o.text, value: o.value })),
      onFilter: (val, row) => row.status === val,
      render: (_, row) => <StatusPillInline value={row.status} /> },
    { title: '仓库', dataIndex: 'warehouse', width: 160, search: false },
    { title: '计划日期', dataIndex: 'planned_date', width: 120, search: false },
    { title: '盘点行数', dataIndex: 'line_count', width: 100, align: 'right', search: false,
      render: (v) => <span style={{ fontFamily: MONO }}>{v ?? 0}</span> },
    { title: '差异行数', dataIndex: 'diff_count', width: 100, align: 'right', search: false,
      render: (v) => (v
        ? <span style={{ fontFamily: MONO, color: '#b42318', fontWeight: 600 }}>{v}</span>
        : <span style={{ fontFamily: MONO, color: '#1f8f3a' }}>0</span>) },
    { title: '备注', dataIndex: 'notes', ellipsis: true, search: false },
    { title: '操作', dataIndex: '_action', width: 100, fixed: 'right', search: false, hideInSetting: true,
      render: (_, row) => (
        <Button type="link" size="small"
          onClick={(e) => { e.stopPropagation(); openDetail(row); }}>盘点录入</Button>
      ) },
  ], [openDetail]);

  const editable = detail && EDITABLE_STATES.has(detail.status);

  // 分性质过滤后的明细
  const filteredLines = useMemo(() => {
    if (natureTab === 'all') return lines;
    return lines.filter((l) => (l._goods_nature || '') === natureTab);
  }, [lines, natureTab]);

  const diffCount = useMemo(
    () => lines.filter((l) => l.counted_quantity != null
      && Number(l.counted_quantity) !== Number(l.system_quantity || 0)).length,
    [lines]
  );
  const pendingCount = useMemo(
    () => lines.filter((l) => l.counted_quantity == null).length,
    [lines]
  );

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          盘点单
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          仓储 WMS · 月度 27 号实物 vs 系统 · 差异 → 库存调整推金蝶
        </span>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="一张盘点单 = 一次全仓盘点；扫码录实际数 → 自动算差异(实际−系统)，差异行调查备注必填"
        description="建盘点单按当前库存生成盘点行；盘点员扫码计数或手填实际数，差异行标红、须填调查备注(先查出库登记再查入库登记)；全部录入后提交，差异生成库存调整(按差异落库+写流水+推金蝶)。分性质 Tab 同页切走流程/待處理/貨/樣品/帶貨/RMA/NG，不拆页。"
      />

      <BizTable
        key={reloadKey}
        headerTitle="盘点单台账"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        search={false}
        toolBarRender={() => [
          <CreateCountButton key="new" whOptions={whOptions} onCreate={onCreate} />,
        ]}
        onRow={(row) => ({ onClick: () => openDetail(row), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      />

      {/* 盘点录入抽屉（不跳页） */}
      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`盘点单 · ${detail?.count_number || ''}`}
        width={1180}
        submitter={false}
      >
        {detail && (
          <>
            {/* 顶部动作按钮 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
              <StatusPillInline value={detail.status} />
              <Tag color={pendingCount ? 'warning' : 'success'}>待录入 {pendingCount}</Tag>
              <Tag color={diffCount ? 'error' : 'success'}>差异 {diffCount}</Tag>
              <span style={{ flex: 1 }} />
              {editable && (
                <Button size="small" type="primary" loading={busy}
                  disabled={pendingCount > 0}
                  title={pendingCount > 0 ? '还有行未录入实际数' : ''}
                  onClick={onSubmit}>提交盘点</Button>
              )}
              {detail.status === 'SUBMITTED' && (
                <Button size="small" type="primary" loading={busy} onClick={onAdjust}>
                  生成库存调整单草稿（财务核原因后过账推金蝶）
                </Button>
              )}
              {detail.status === 'ADJUSTED' && (
                <Tag color="success">已调整 · 盘点闭环完成</Tag>
              )}
            </div>

            {/* 扫码盘点工具条 */}
            {editable && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                <Button size="small" type={scanMode ? 'primary' : 'default'} icon={<ScanOutlined />}
                  onClick={() => setScanMode((s) => !s)}>
                  {scanMode ? '扫码模式·开' : '扫码盘点（计数）'}
                </Button>
                {scanMode && (
                  <Input
                    size="small" style={{ width: 260 }} autoFocus allowClear
                    value={scanText}
                    placeholder="扫入仓编号 → 该行实际数 +1（可格内改精确数）"
                    prefix={<ScanOutlined />}
                    onChange={(e) => setScanText(e.target.value)}
                    onPressEnter={(e) => onScan(e.target.value)}
                  />
                )}
                <Tooltip title="差异行(实际≠系统)调查备注必填，否则无法提交">
                  <Tag color="processing">明细 {lines.length} 行</Tag>
                </Tooltip>
              </div>
            )}

            {/* 分性质 Tab（同页视图，不拆页） */}
            <Tabs
              size="small"
              activeKey={natureTab}
              onChange={setNatureTab}
              items={NATURE_TABS.map((t) => ({
                key: t.key,
                label: t.key === 'all'
                  ? `${t.label}(${lines.length})`
                  : `${t.label}(${lines.filter((l) => (l._goods_nature || '') === t.key).length})`,
              }))}
            />

            <CountLineGrid
              lines={filteredLines}
              editable={editable}
              busy={busy}
              onChangeLine={(id, patch) => setLines((prev) => prev.map((l) => (l.id === id ? { ...l, ...patch } : l)))}
              onSaveLine={saveLine}
            />
          </>
        )}
        {!detail && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="加载中…" />}
      </BizDrawerForm>
    </div>
  );
}

/** 建盘点单触发器（抽屉内 ProForm；选仓库范围 + 计划日期） */
function CreateCountButton({ whOptions, onCreate }) {
  const [open, setOpen] = useState(false);
  return (
    <BizDrawerForm
      open={open}
      onOpenChange={setOpen}
      title="新建盘点单"
      width={520}
      trigger={<Button type="primary" icon={<PlusOutlined />}>新建盘点单</Button>}
      submitter={{ searchConfig: { submitText: '生成盘点单' } }}
      onFinish={async (v) => {
        const ok = await onCreate(v);
        if (ok) setOpen(false);
        return ok;
      }}
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 10 }}
        title="按当前库存生成盘点行"
        description="留空仓库 = 盘全公司可盘点库存；选仓库 = 仅盘该仓。生成后逐行录实际数。"
      />
      <ProFormSelect
        name="warehouse_id" label="盘点仓库（范围）" options={whOptions} showSearch
        fieldProps={{ optionFilterProp: 'label' }}
        placeholder="留空 = 全公司"
      />
      <ProFormText
        name="planned_date" label="计划盘点日期"
        fieldProps={{ type: 'date' }}
        tooltip="留空默认今日"
      />
    </BizDrawerForm>
  );
}

/**
 * CountLineGrid —— 盘点明细网格（HTML table，逐行录实际数 + 自动差异 + 标红 + 备注必填 + 逐行保存）
 * 用轻量受控 table 而非 EditableProTable：逐行 saveLine 走 updateWmsCountLine 命令路径（一行一命令），
 * 录实际数即就地算差异、差异标红、备注必填提示，乐观 UI、失败弹错不静默。
 */
function CountLineGrid({ lines = [], editable, busy, onChangeLine, onSaveLine }) {
  if (!lines.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该性质暂无盘点行" style={{ margin: '24px 0' }} />;
  }
  return (
    <div style={{ overflowX: 'auto', marginTop: 8 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'rgba(245,242,239,0.6)' }}>
            {['入仓编号', '型号', 'SN/LOT', '库位', '性质', '系统数', '实际数', '差异', '调查备注', ''].map((h) => (
              <th key={h} style={{ textAlign: h === '系统数' || h === '实际数' || h === '差异' ? 'right' : 'left',
                padding: '6px 10px', color: '#777169', fontWeight: 500, whiteSpace: 'nowrap' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lines.map((l) => {
            const counted = l._counted_input;
            const diff = (counted == null || counted === '')
              ? (l.counted_quantity != null ? Number(l.counted_quantity) - Number(l.system_quantity || 0) : null)
              : Number(counted) - Number(l.system_quantity || 0);
            const isDiff = diff != null && diff !== 0;
            const needNote = isDiff && !String(l._notes_input || '').trim();
            return (
              <tr key={l.id} style={{
                borderBottom: '1px solid rgba(0,0,0,0.05)',
                background: isDiff ? 'rgba(180,35,24,0.04)' : undefined,
              }}>
                <td style={{ padding: '6px 10px', fontFamily: MONO, whiteSpace: 'nowrap' }}>{l.inbound_number || '—'}</td>
                <td style={{ padding: '6px 10px', whiteSpace: 'nowrap' }}>{l.material || '—'}</td>
                <td style={{ padding: '6px 10px', whiteSpace: 'nowrap' }}>{l.serial_lot_number || '—'}</td>
                <td style={{ padding: '6px 10px', whiteSpace: 'nowrap' }}>{l.location_code || '—'}</td>
                <td style={{ padding: '6px 10px', whiteSpace: 'nowrap' }}>{l._goods_nature || '—'}</td>
                <td style={{ padding: '6px 10px', textAlign: 'right', fontFamily: MONO }}>{l.system_quantity}</td>
                <td style={{ padding: '4px 10px', textAlign: 'right' }}>
                  {editable ? (
                    <Input
                      size="small" type="number" style={{ width: 90, fontFamily: MONO, textAlign: 'right' }}
                      value={l._counted_input ?? ''}
                      onChange={(e) => onChangeLine(l.id, { _counted_input: e.target.value === '' ? '' : Number(e.target.value) })}
                    />
                  ) : (
                    <span style={{ fontFamily: MONO }}>{l.counted_quantity ?? '—'}</span>
                  )}
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'right', fontFamily: MONO,
                  color: isDiff ? '#b42318' : '#1f8f3a', fontWeight: isDiff ? 600 : 400 }}>
                  {diff == null ? '—' : (diff > 0 ? `+${diff}` : diff)}
                </td>
                <td style={{ padding: '4px 10px' }}>
                  {editable ? (
                    <Input
                      size="small" style={{ width: 200 }}
                      status={needNote ? 'error' : undefined}
                      placeholder={isDiff ? '差异必填：先查出库再查入库' : '（无差异可不填）'}
                      value={l._notes_input ?? ''}
                      onChange={(e) => onChangeLine(l.id, { _notes_input: e.target.value })}
                    />
                  ) : (
                    <span>{l.notes || '—'}</span>
                  )}
                </td>
                <td style={{ padding: '4px 10px', whiteSpace: 'nowrap' }}>
                  {editable && (
                    <Button size="small" type="link" loading={busy}
                      disabled={needNote || l._counted_input == null || l._counted_input === ''}
                      onClick={() => onSaveLine(l)}>录入</Button>
                  )}
                  {!editable && <StatusPillInline value={l.status} />}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {editable && (
        <div style={{ color: '#777169', fontSize: 12, marginTop: 8 }}>
          逐行录实际数后点「录入」落库（自动算差异）；差异行(标红)须填调查备注；全部录入后顶部「提交盘点」。
        </div>
      )}
    </div>
  );
}
