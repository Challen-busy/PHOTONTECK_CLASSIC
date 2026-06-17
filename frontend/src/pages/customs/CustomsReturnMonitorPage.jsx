/**
 * CustomsReturnMonitorPage —— 退运 180 天监控（PRD 06-2）
 *
 * 退运不是独立单据，而是报关单 direction=RE_EXPORT 的方向 + 一块倒计时监控。物流主任天天扫
 * 「退运临期」：盯哪票货快到 180 天大限。系统只飘红预警、不自动拦、不替办（SOP §四-5）。
 * 本页为可读视图为主：台账过滤 direction=RE_EXPORT，前端按 return_deadline 实时算 remaining_days
 * 并着色（<30 天高亮红预警 / 30~90 金 / >90 绿 / 已放行绿 / 超期红）。
 *
 * ★真值（已勘 /api/schema 2026-06-17）：
 *   - 头表 customs_declaration，direction=RE_EXPORT（退运出口；无「退关进口」，SOP §四-1）。
 *   - return_deadline(退运截止日，默认原进口放行日+180) / import_release_date(原进口放行日)
 *     / origin_declaration_id(原进口报关单自引用，限本公司已放行=香港退香港物理保证) / status。
 *   - remaining_days 非持久列：前端按 return_deadline − today 实时算（引擎无 cron，工作台轮询）。
 *
 * 写入一律仍走报关单页（CustomsDeclarationPage）→ /api/transition；本页只读监控、不推进。
 */
import { useCallback, useMemo, useState } from 'react';
import { Alert, App, Descriptions, Empty, Tag } from 'antd';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema } from '../../api';
import { schemaToColumns, renderCellByField } from '../wms/wmsHelpers';
import { StatusPill } from '../wms/wmsShared';

const TABLE = 'customs_declaration';
const LINE_TABLE = 'customs_declaration_line';
const LINE_FK = 'customs_declaration_id';
const NUMBER_FIELD = 'declaration_number';
const DEADLINE_FIELD = 'return_deadline';

// 退运截止日 − today → 剩余天数（不入库，查询时算）
function daysUntil(deadline) {
  if (!deadline) return null;
  const d = new Date(String(deadline).slice(0, 10));
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - today.getTime()) / 86400000);
}

// 颜色预警（SOP §四-5）：已放行绿 / 超期红 / <30 红 / 30~90 金 / >90 绿
function remainingTag(row) {
  if (row.status === 'RELEASED' || row.status === 'CLOSED') {
    return <Tag style={{ background: '#ebf5ee', color: '#1f8f3a', border: 'none' }}>已办妥</Tag>;
  }
  const n = daysUntil(row[DEADLINE_FIELD]);
  if (n == null) return <span style={{ color: '#bfbbb5' }}>未设限期</span>;
  if (n < 0) {
    return <Tag style={{ background: '#fdecea', color: '#b42318', border: 'none', fontWeight: 600 }}>已超期 {-n} 天</Tag>;
  }
  if (n < 30) {
    return <Tag style={{ background: '#fdecea', color: '#b42318', border: 'none', fontWeight: 600 }}>剩 {n} 天 · 临期</Tag>;
  }
  if (n <= 90) {
    return <Tag style={{ background: '#fbf5e4', color: '#b8860b', border: 'none' }}>剩 {n} 天</Tag>;
  }
  return <Tag style={{ background: '#ebf5ee', color: '#1f8f3a', border: 'none' }}>剩 {n} 天</Tag>;
}

const SUB_SKIP = new Set(['id', 'company_id', 'created_at', 'updated_at', 'created_by_id', 'updated_by_id']);

function ReadonlyLines({ rows = [] }) {
  if (!rows.length) return <span style={{ color: '#bfbbb5' }}>无明细</span>;
  const keys = Object.keys(rows[0]).filter((k) => !SUB_SKIP.has(k) && !k.startsWith('_'));
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'rgba(245,242,239,0.6)' }}>
            {keys.map((k) => (
              <th key={k} style={{ textAlign: 'left', padding: '6px 10px', color: '#777169', fontWeight: 500, whiteSpace: 'nowrap' }}>{k}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
              {keys.map((k) => (
                <td key={k} style={{ padding: '6px 10px', whiteSpace: 'nowrap' }}>
                  {r[k] == null || r[k] === '' ? <span style={{ color: '#bfbbb5' }}>—</span> : String(r[k])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function CustomsReturnMonitorPage() {
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [schemaReady, setSchemaReady] = useState(null);   // null=未知 true=就绪 false=后端未注册
  const [detail, setDetail] = useState(null);
  const [lineRows, setLineRows] = useState([]);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const STATUS_ENUM = useMemo(() => [
    { text: '草拟 DRAFT', value: 'DRAFT' },
    { text: '已申报 SUBMITTED', value: 'SUBMITTED' },
    { text: '已放行 RELEASED', value: 'RELEASED' },
    { text: '已退单 REJECTED', value: 'REJECTED' },
    { text: '已关闭 CLOSED', value: 'CLOSED' },
  ], []);

  // 台账 request：固定过滤 direction=RE_EXPORT（退运方向）
  const tableRequest = useCallback(async (params = {}) => {
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(TABLE); sc = data; setSchema(data); setSchemaReady(true); }
      catch { setSchemaReady(false); return { data: [], success: true, total: 0 }; }
    }
    const { current: _c, pageSize, keyword, status, ...rest } = params;
    const filters = { direction: 'RE_EXPORT' };
    if (status) filters.status = status;
    for (const [k, v] of Object.entries(rest)) {
      if (v == null || v === '' || k === '_timestamp') continue;
      filters[k] = v;
    }
    try {
      const { data } = await query(TABLE, {
        filters, search: keyword || '', order_by: DEADLINE_FIELD,
        limit: Math.min(pageSize || 20, 100),
      });
      return { data: data.data || [], success: true, total: data.total ?? (data.data || []).length };
    } catch (e) {
      message.error(e.response?.data?.detail || '加载退运监控失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, message]);

  const openDetail = useCallback(async (row) => {
    setDetail(row);
    setDrawerOpen(true);
    try {
      const { data } = await query(LINE_TABLE, { filters: { [LINE_FK]: row.id }, limit: 200 });
      setLineRows((data?.data || []).map((r) => ({ ...r })));
    } catch { setLineRows([]); }
  }, []);

  // schema 列 + 派生「剩余天数」列（插在操作列前）
  const columns = useMemo(() => {
    const base = schemaToColumns(schema?.fields || [], {
      frozen: [NUMBER_FIELD, 'status'].filter(Boolean),
      statusFilter: ['status'],
      statusEnum: { status: STATUS_ENUM },
      actionCol: {
        title: '退运限期', dataIndex: '_remaining', width: 130, fixed: 'right', search: false, hideInSetting: true,
        render: (_, row) => remainingTag(row),
      },
    });
    return base;
  }, [schema, STATUS_ENUM]);

  const detailFields = useMemo(
    () => (schema?.fields || []).filter((f) => f.name !== 'id'),
    [schema]
  );

  const Header = () => (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
        退运监控（180 天）
      </h2>
      <span style={{ color: '#777169', fontSize: 13 }}>
        报关 · 引擎单据 <code>CUSTOMS_DECLARATION</code> · direction=RE_EXPORT 退运方向 + 倒计时（可读视图）
      </span>
    </div>
  );

  if (schemaReady === false) {
    return (
      <div>
        <Header />
        <Alert
          type="warning" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
          title="功能已就绪 · 待后端开通"
          description="退运监控复用报关单 CUSTOMS_DECLARATION（direction=RE_EXPORT）+ return_deadline 倒排列。后端 customs_declaration 表 /api/schema 就绪后本页自动点亮（schema 驱动，remaining_days 前端按 return_deadline 实时算并着色）。"
        />
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="退运监控待后端开通" />
      </div>
    );
  }

  return (
    <div>
      <Header />
      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="退运 = 报关单 direction=RE_EXPORT + 180 天倒计时。退运截止日（默认原进口放行日 + 180）− today = 剩余天数：<30 天飘红临期预警 / 30~90 金 / >90 绿 / 已办妥绿 / 超期红。"
        description="★香港卖的退香港一致性：退运单「原进口报关单」（origin_declaration_id）下拉物理限本公司已放行进口单，跨公司物理选不到（_company_filter 天然限本公司 + 退运校验器双保险）→ 香港卖的东西退回香港公司，完全按物流线索走退关。系统只飘红预警、不自动拦、不替办（SOP §四-5「全靠你盯」）；超 180 天未放行单关闭须填超期原因，不允许静默关闭。退运单的建单 / 推进在「报关单」页操作（→ /api/transition），本页为可读监控视图。"
      />

      <BizTable
        headerTitle="退运报关单监控台账"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        search={{ filterType: 'light' }}
        onRow={(row) => ({ onClick: () => openDetail(row), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`退运报关单 · 详情${detail?.[NUMBER_FIELD] ? ` · ${detail[NUMBER_FIELD]}` : ''}`}
        width={1040}
        submitter={false}
      >
        {detail?.id && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
            <StatusPill value={detail.status} />
            {remainingTag(detail)}
            {detail[DEADLINE_FIELD] && (
              <span style={{ color: '#777169', fontSize: 13 }}>
                退运截止日 {String(detail[DEADLINE_FIELD]).slice(0, 10)}
              </span>
            )}
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

        <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '16px 0 8px' }}>
          商品明细 · {lineRows.length} 行
        </div>
        <ReadonlyLines rows={lineRows} />
      </BizDrawerForm>
    </div>
  );
}
