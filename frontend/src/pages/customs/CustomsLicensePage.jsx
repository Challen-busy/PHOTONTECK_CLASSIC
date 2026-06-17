/**
 * CustomsLicensePage —— 进出口证（许可证）台账（PRD 06-4）
 *
 * 进出口许可证 / 战略物资证 / 两用物项许可证的台账。受管制（ECCN）产品报关行可挂证留痕
 * （customs_declaration_line.license_id）。效期预警：失效日 <60 天前端标。
 *
 * ★真值（已勘 /api/schema 2026-06-17）：
 *   - 表 customs_license，__queryable__ 主数据、无 doc_type（不挂 WorkflowDefinition）。
 *   - license_number(系统连号 LIC{YYMM}-{seq}) / license_no(官方原始证号，(company,license_no) 唯一)
 *     / license_type(证件类型) / issuer(签发机关) / broker_id(持证报关行 FK supplier)
 *     / scope(HS 范围文字) / valid_from(生效日) / valid_to(失效日，效期预警基准) / is_active(启用)。
 *
 * ⚠️ 唯一写入路径：customs_license 为纯 __queryable__ 字典、无 doc_type → 当前无 /api/transition
 *   写路径（同 hs_code / unit_of_measure 主数据壳）。本页为只读台账 + 效期预警；建档 / 改档 / 停用
 *   待后端 ➕ 写路径（EXT-02-W）。绝不在前端伪造成功 / 不调非 transition 写端点。
 */
import { useCallback, useMemo, useState } from 'react';
import { Alert, App, Descriptions, Tag } from 'antd';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema } from '../../api';
import { schemaToColumns, renderCellByField } from '../wms/wmsHelpers';

const TABLE = 'customs_license';
const NUMBER_FIELD = 'license_number';
const EXPIRY_FIELD = 'valid_to';

// 失效日 − today → 剩余天数
function daysUntil(d) {
  if (!d) return null;
  const dt = new Date(String(d).slice(0, 10));
  if (Number.isNaN(dt.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((dt.getTime() - today.getTime()) / 86400000);
}

// 效期预警标（<60 天红 / <90 金 / 有效绿 / 已失效红 / 停用灰）
function expiryTag(row) {
  if (row.is_active === false) {
    return <Tag style={{ background: '#f5f5f5', color: '#777169', border: 'none' }}>已停用</Tag>;
  }
  const n = daysUntil(row[EXPIRY_FIELD]);
  if (n == null) return <span style={{ color: '#bfbbb5' }}>无失效日</span>;
  if (n < 0) {
    return <Tag style={{ background: '#fdecea', color: '#b42318', border: 'none', fontWeight: 600 }}>已失效 {-n} 天</Tag>;
  }
  if (n < 60) {
    return <Tag style={{ background: '#fdecea', color: '#b42318', border: 'none', fontWeight: 600 }}>剩 {n} 天 · 临期</Tag>;
  }
  if (n < 90) {
    return <Tag style={{ background: '#fbf5e4', color: '#b8860b', border: 'none' }}>剩 {n} 天</Tag>;
  }
  return <Tag style={{ background: '#ebf5ee', color: '#1f8f3a', border: 'none' }}>有效（剩 {n} 天）</Tag>;
}

export default function CustomsLicensePage() {
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [schemaReady, setSchemaReady] = useState(null);
  const [detail, setDetail] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const tableRequest = useCallback(async (params = {}) => {
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(TABLE); sc = data; setSchema(data); setSchemaReady(true); }
      catch { setSchemaReady(false); return { data: [], success: true, total: 0 }; }
    }
    const { current: _c, pageSize, keyword, ...rest } = params;
    const filters = {};
    for (const [k, v] of Object.entries(rest)) {
      if (v == null || v === '' || k === '_timestamp') continue;
      filters[k] = v;
    }
    try {
      const { data } = await query(TABLE, {
        filters, search: keyword || '', order_by: EXPIRY_FIELD,
        limit: Math.min(pageSize || 20, 100),
      });
      return { data: data.data || [], success: true, total: data.total ?? (data.data || []).length };
    } catch (e) {
      message.error(e.response?.data?.detail || '加载进出口证台账失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, message]);

  const openDetail = useCallback((row) => {
    setDetail(row);
    setDrawerOpen(true);
  }, []);

  const columns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: [NUMBER_FIELD, 'license_no'].filter(Boolean),
    actionCol: {
      title: '效期预警', dataIndex: '_expiry', width: 150, fixed: 'right', search: false, hideInSetting: true,
      render: (_, row) => expiryTag(row),
    },
  }), [schema]);

  const detailFields = useMemo(
    () => (schema?.fields || []).filter((f) => f.name !== 'id'),
    [schema]
  );

  const Header = () => (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
        进出口证台账
      </h2>
      <span style={{ color: '#777169', fontSize: 13 }}>
        报关 · 引擎表 <code>customs_license</code> · 许可证主数据（效期预警 &lt;60 天标红）
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
          description="进出口证台账复用引擎表 customs_license（__queryable__ 主数据）。后端 /api/schema 就绪后本页自动点亮（schema 驱动，效期预警前端按 valid_to 算）。"
        />
      </div>
    );
  }

  return (
    <div>
      <Header />
      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="进出口证 / 战略物资证 / 两用物项许可证台账：证号（官方）+ 证件类型 + 报关行 + 生效 / 失效日。受管制（ECCN）产品报关时报关行挂证留痕（仅本公司、效期内）。失效日 <60 天标红临期、<90 金、按失效日升序排（临期排最上）。"
        description="进出口证为 __queryable__ 主数据、无 doc_type（同 HS 编码 / 计量单位字典壳）→ 当前无 /api/transition 写路径，本页为只读台账 + 效期预警。建档 / 改档 / 停用（已挂报关单的证不可删、只可改停用；证号本公司唯一；生效日不可晚于失效日）待后端 ➕ 主数据写路径（EXT-02-W）后开写；届时本页自动开放新建 / 编辑，不在前端伪造写入。"
      />

      <BizTable
        headerTitle="进出口证台账"
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
        title={`进出口证 · 详情${detail?.[NUMBER_FIELD] ? ` · ${detail[NUMBER_FIELD]}` : ''}`}
        width={720}
        submitter={false}
      >
        {detail?.id && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
            {expiryTag(detail)}
            {detail.license_no && (
              <span style={{ color: '#777169', fontSize: 13 }}>证号 {detail.license_no}</span>
            )}
          </div>
        )}
        <Descriptions column={1} size="small" bordered
          styles={{ label: { width: 150, color: '#777169' } }}>
          {detailFields.map((f) => (
            <Descriptions.Item key={f.name} label={f.label || f.name}>
              {renderCellByField(f, detail?.[f.name])}
            </Descriptions.Item>
          ))}
        </Descriptions>
        <Alert
          type="info" showIcon style={{ marginTop: 16, borderRadius: 10 }}
          title="只读详情"
          description="进出口证（customs_license）的建档 / 改档 / 停用写路径（引擎主数据写端点）尚未在后端注册，当前仅支持查看。开写需后端 ➕ queryable-CRUD 写路径（EXT-02-W）。"
        />
      </BizDrawerForm>
    </div>
  );
}
