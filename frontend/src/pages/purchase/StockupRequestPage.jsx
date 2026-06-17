/**
 * StockupRequestPage —— 备货申请 + 消单跟踪台账（PRD 04b-1 / 04b-2）⭐
 *
 * 销售/PM 主动提议囤货：填型号 / 备货数量 / 意向客户 / 签单公司 / 原因 / 风险点 / 金额；
 * 系统建单 effect 拍下「当时库存 stock_on_hand / 当时在途 in_transit_qty」只读快照（03 库存投影 + 04a 在途投影）。
 * 提交按金额自动分流（DRAFT 两条出边带边级 hard_rule：amount<200000→PENDING_PM 单批；>=200000→PENDING_REVIEW 会审）。
 * 会审多签（PM/PD + FINANCE 都签才放行）= 串行会签子状态（节点级 allowed_roles，PRD 推荐方案①），
 * 在审批中心（list_user_todos）由对应角色推进。批准后 PA 关联 draft_po→正式 PO，进 TRACKING 消单跟踪。
 *
 * 两 Tab（决策⑦：消单台账 = 同库 TRACKING 单的视图，不是另一张表）：
 *   ① 备货申请：PurchaseDocPage 薄包装（noLines，头 schema 驱动；动作一律 /api/transitions→/api/transition）。
 *   ② 消单跟踪台账：只读 BizTable over TRACKING 单（原始 vs 已消，剩余=原始-已消，已挂天数；挂太久行标红）→点行下钻抽屉。
 *
 * 🔒 字段防火墙（§00-8）：备货金额 amount 按含税报价口径对 SALES 呈现；采购成本/买价/利润点对 SALES 由后端
 *   遮蔽（/api/schema + /api/query 两路）——本页纯 schema 驱动，不写死成本列。
 *
 * ★引擎实况：STOCK_UP_REQUEST doc_type / stock_up_request 表 / 流程由后端段2d 注册。未注册时 /api/schema 失败
 *   → PurchaseDocPage 显示「功能已就绪·待后端开通」占位（14 律 §8），注册后自动点亮，不写死状态码。
 */
import { useCallback, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Tabs, Tag } from 'antd';
import PurchaseDocPage from './PurchaseDocPage';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema } from '../../api';
import { schemaToColumns, renderCellByField } from '../wms/wmsHelpers';
import { StatusPill } from '../wms/wmsShared';

const TABLE = 'stock_up_request';
const NUMBER_FIELD = 'request_number';
const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';

// gap-4（默认）：备货挂满 30 天仍有剩余 → 「挂太久」标红提醒（待甲方确认阈值/对象）。
const AGING_ALERT_DAYS = 30;

// 状态药丸候选（仅台账筛选提示；真实可走边以 /api/transitions 为准，不写死状态码推进）
const STATUS_ENUM = [
  { text: '草稿 DRAFT', value: 'DRAFT' },
  { text: 'PM 单批 PENDING_PM', value: 'PENDING_PM' },
  { text: '★会审 PENDING_REVIEW', value: 'PENDING_REVIEW' },
  { text: '★PM 会签 REVIEW_PM', value: 'REVIEW_PM' },
  { text: '★财务会签 REVIEW_FINANCE', value: 'REVIEW_FINANCE' },
  { text: '已批准 APPROVED', value: 'APPROVED' },
  { text: '消单跟踪 TRACKING', value: 'TRACKING' },
  { text: '已关闭 CLOSED', value: 'CLOSED' },
  { text: '已驳回 REJECTED', value: 'REJECTED' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

export default function StockupRequestPage() {
  const [tab, setTab] = useState('request');

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          备货申请
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          采购 / 供应链 · 引擎单据 <code>STOCK_UP_REQUEST</code> · 谁提议谁担风险、谁买谁跟到底（含会审多签 + 消单跟踪）
        </span>
      </div>

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'request',
            label: '备货申请',
            children: (
              <PurchaseDocPage
                docType="STOCK_UP_REQUEST"
                table={TABLE}
                noLines
                title="备货申请"
                subtitle="销售/PM 发起 → 按金额自动分流（<20万 PM 单批 / ★≥20万会审多签）→ PA 下单进消单跟踪"
                numberField={NUMBER_FIELD}
                statusEnum={STATUS_ENUM}
                editableStates={['DRAFT']}
                newLabel="新建备货申请"
                primaryToStates={['PENDING_PM', 'PENDING_REVIEW', 'REVIEW_PM', 'REVIEW_FINANCE', 'APPROVED', 'TRACKING']}
                intro={{
                  title: '备货申请 = 销售/PM 提议为某（意向）客户囤货：填型号 / 备货数量 / 意向客户 / 签单公司 / 原因 / 风险点 / 金额；建单自动带出「当时库存 + 在途」只读快照',
                  description: '提交按金额自动分流（边级 hard_rule：amount<20万→PM 单批 PENDING_PM；≥20万→会审 PENDING_REVIEW，PM/PD 与财务都签才放行，会审节点在审批中心由对应角色推进）。批准后 PA 关联 draft_po→正式 PO，进 TRACKING 消单跟踪（见「消单跟踪台账」Tab）。备货金额按含税报价口径呈现给 SALES；采购成本/买价/利润点对 SALES 由后端字段防火墙遮蔽，本页纯 schema 渲染。动作一律走 /api/transitions（按当前状态过滤真实边）→ /api/transition（唯一写入路径），不写死状态码。',
                }}
                todoNote="备货为 ➕ 新增 STOCK_UP_REQUEST doc_type（引擎 02 §2.9 明确排除「备货」业务）。需后端段2d 建 stock_up_request 表（含 stock_on_hand/in_transit_qty 只读快照、consumed_quantity 派生列、risk_notes、amount/currency 等）+ WorkflowDefinition（DRAFT 两条出边带边级 hard_rule 按 20万分流；会审走串行会签子状态 REVIEW_PM→REVIEW_FINANCE→APPROVED，节点级 allowed_roles 规避 D-02e 边级角色坑）+ 建单取号 effect（request_number 月度连号）+ 建单库存/在途快照 effect。注册后本页自动点亮。"
              />
            ),
          },
          {
            key: 'ledger',
            label: '消单跟踪台账',
            children: <StockupLedger statusEnum={STATUS_ENUM} />,
          },
        ]}
      />
    </div>
  );
}

/**
 * 消单跟踪台账（PRD 04b-2）—— 只读 TRACKING 单视图 + 提醒 + 下钻。
 * 决策⑩：大台账 = 只读网格 + cell 下钻详情抽屉（不在大表内联编辑跨单据，不跳页）。
 * 剩余 / 已挂天数 = 前端派生列（引擎无原生计算列）；挂满阈值天仍有剩余 → 行标红 + Tag 提醒。
 */
function StockupLedger({ statusEnum }) {
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [schemaReady, setSchemaReady] = useState(null); // null=未知 true=就绪 false=未注册
  const [detail, setDetail] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const tableRequest = useCallback(async (params = {}) => {
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(TABLE); sc = data; setSchema(data); setSchemaReady(true); }
      catch { setSchemaReady(false); return { data: [], success: true, total: 0 }; }
    }
    const { current: _c, pageSize, keyword, ...rest } = params;
    // 消单台账只看 TRACKING 单（决策⑦：消单台账 = TRACKING 单的同库视图）
    const filters = { status: 'TRACKING' };
    for (const [k, v] of Object.entries(rest)) {
      if (v == null || v === '' || k === '_timestamp') continue;
      filters[k] = v;
    }
    try {
      const { data } = await query(TABLE, {
        filters, search: keyword || '', order_by: '-id',
        limit: Math.min(pageSize || 20, 100),
      });
      return { data: data.data || [], success: true, total: data.total ?? (data.data || []).length };
    } catch (e) {
      message.error(e.response?.data?.detail || '加载消单台账失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, message]);

  const openDetail = useCallback((row) => { setDetail(row); setDrawerOpen(true); }, []);

  const columns = useMemo(() => {
    const base = schemaToColumns(schema?.fields || [], {
      frozen: [NUMBER_FIELD, 'status'],
      statusFilter: ['status'],
      statusEnum: { status: statusEnum },
    });
    // 隐藏快照列里在消单视图意义不大的「当时库存/在途」（在下钻抽屉仍可见，保持台账聚焦消单）
    const SHELF = new Set(['stock_on_hand', 'in_transit_qty', 'customer_arrears', 'reason']);
    const trimmed = base.filter((c) => !SHELF.has(c.dataIndex));
    // ➕ 派生列：剩余=原始-已消、已挂天数；引擎无原生计算列 → 前端按行计算（与样品超期天数同机制）。
    const derived = [
      {
        title: '剩余', dataIndex: '_remaining', width: 90, align: 'right', search: false, hideInSetting: true,
        render: (_, row) => {
          const rem = remainingOf(row);
          if (rem == null) return <span style={{ color: '#bfbbb5' }}>—</span>;
          return <span style={{ fontFamily: MONO, color: rem <= 0 ? '#1f8f3a' : '#000' }}>{rem.toLocaleString()}</span>;
        },
      },
      {
        title: '已挂天数', dataIndex: '_aging_days', width: 110, align: 'right', search: false, hideInSetting: true,
        render: (_, row) => {
          const d = agingDaysOf(row);
          if (d == null) return <span style={{ color: '#bfbbb5' }}>—</span>;
          const overdue = isStale(row);
          return (
            <span style={{ fontFamily: MONO, color: overdue ? '#b42318' : '#000', fontWeight: overdue ? 600 : 400 }}>
              {d}{overdue ? ' ⚠' : ''}
            </span>
          );
        },
      },
    ];
    const actionCol = {
      title: '操作', dataIndex: '_action', width: 80, fixed: 'right', search: false, hideInSetting: true,
      render: (_, row) => (
        <Button type="link" size="small"
          onClick={(e) => { e.stopPropagation(); openDetail(row); }}>详情</Button>
      ),
    };
    return [...trimmed, ...derived, actionCol];
  }, [schema, statusEnum, openDetail]);

  const detailFields = useMemo(
    () => (schema?.fields || []).filter((f) => f.name !== 'id'),
    [schema]
  );

  if (schemaReady === false) {
    return (
      <Alert
        type="warning" showIcon style={{ borderRadius: 12 }}
        title="消单跟踪台账已就绪 · 待后端开通"
        description="STOCK_UP_REQUEST 模型 / 流程尚未在后端注册；段2d 注册后本台账自动点亮（只读 TRACKING 单 + 剩余/已挂天数派生列 + 挂太久标红，schema 驱动不写死列）。"
      />
    );
  }

  const detailRem = detail ? remainingOf(detail) : null;
  const detailAging = detail ? agingDaysOf(detail) : null;

  return (
    <div>
      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="消单跟踪台账 = TRACKING 态备货单的只读视图（原始备货数量 vs 已消，剩余 = 原始 − 已消）；客户真下单消化时由消单 effect 累加已消，消完自动关闭"
        description={`原始备货数量永不改；已消由销售订单成交触发的消单 effect 累加（段3 SALES_ORDER 自动派生）。备货挂满 ${AGING_ALERT_DAYS} 天仍有剩余的单标红 ⚠ 提醒「一直挂在备货没人卖」（gap-4：阈值/提醒对象待甲方）。点行下钻详情（只读，不在大表内联编辑，决策⑩）。金额对 SALES 按含税报价口径，成本/买价由后端遮蔽即不出列。`}
      />

      <BizTable
        headerTitle="消单跟踪台账（TRACKING）"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        onRow={(row) => ({
          onClick: () => openDetail(row),
          style: { cursor: 'pointer', background: isStale(row) ? 'rgba(253,236,234,0.45)' : undefined },
        })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 460px)' }}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`备货消单详情${detail?.[NUMBER_FIELD] ? ` · ${detail[NUMBER_FIELD]}` : ''}`}
        width={920}
        submitter={false}
      >
        {detail && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <StatusPill value={detail.status} />
            {detailRem != null && (
              <Tag color={detailRem <= 0 ? 'green' : 'gold'}>
                剩余 {detailRem.toLocaleString()} / 原始 {Number(detail.stockup_quantity || 0).toLocaleString()}
              </Tag>
            )}
            {isStale(detail) && <Tag color="red">已挂 {detailAging} 天 · 久未消单</Tag>}
            <span style={{ color: '#bfbbb5', fontSize: 12 }}>消单由销售订单成交自动累加，台账只读（决策⑩）</span>
          </div>
        )}

        <Descriptions column={2} size="small" bordered
          styles={{ label: { width: 130, color: '#777169' } }}>
          {detailFields.map((f) => (
            <Descriptions.Item key={f.name} label={f.label || f.name}>
              {f.name === 'status'
                ? <StatusPill value={detail?.[f.name]} />
                : renderCellByField(f, detail?.[f.name])}
            </Descriptions.Item>
          ))}
        </Descriptions>
      </BizDrawerForm>
    </div>
  );
}

// —— 派生计算（引擎无原生计算列，前端按行算；后端字段缺时安全返回 null/0）——

// 剩余 = 原始备货数量 − 已消；原始缺失则 null（不渲染假数）
function remainingOf(row) {
  if (row?.stockup_quantity == null) return null;
  const orig = Number(row.stockup_quantity) || 0;
  const used = Number(row.consumed_quantity || 0);
  return orig - used;
}

// 已挂天数 = 今天 − 进入跟踪/下单日期（取 approved_at / ordered_at / updated_at / created_at 中可用者）
function agingDaysOf(row) {
  const raw = row?.tracking_since || row?.approved_at || row?.ordered_at || row?.updated_at || row?.created_at;
  if (!raw) return null;
  const start = new Date(String(raw).replace(' ', 'T'));
  if (Number.isNaN(start.getTime())) return null;
  const ms = Date.now() - start.getTime();
  return Math.max(0, Math.floor(ms / 86400000));
}

// 「挂太久」= 仍有剩余 且 已挂 ≥ 阈值天（gap-4 默认 30 天）
function isStale(row) {
  const rem = remainingOf(row);
  const d = agingDaysOf(row);
  return rem != null && rem > 0 && d != null && d >= AGING_ALERT_DAYS;
}
