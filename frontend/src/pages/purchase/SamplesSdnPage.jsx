/**
 * SamplesSdnPage —— 样品 SDN（申请 / 回签 / 超期 / 转正，PRD 04b-3）⭐
 *
 * PA 登记 / 跟进每一批样品：申请 → 原厂发货 → 入样品仓（其他入库[样品]）→ 寄客户 → 跟回签 →
 *   算超期 → 跟测试结果 → 测试通过转正（可下正式单）。一张 SDN 可含多型号多行 → 头 + 子表
 *   sample_sdn_line（型号 / 描述 / 数量 / SN-LOT）。
 *
 * 复用积木：PurchaseDocPage（台账 → 右抽屉 → 顶部动作按钮，全 schema 驱动；动作一律
 *   /api/transitions 按当前状态过滤真实边 → /api/transition 唯一写入路径，不写死状态码）。
 *   子表网格 PurchaseLineGrid（Excel 粘贴建行 + 扫码顺序锁 + FK cell 选择器，录单增强 14 律 §3）。
 *
 * ➕ 超期天数前端计算（PRD 04b-3 §5 / 蓝图「超期天数(计算值)」）：引擎无原生计算列 →
 *   按「今天 − 寄客户日(gap-5 默认基准)」即时算，未回签且超期标红 ⚠。基准日字段后端可能命名不同，
 *   取 sent_to_customer_at / sent_at / sdn_date / created_at 中首个可用者，缺失则不渲假数。
 *
 * 🔒 字段防火墙（§00-8）：目标价 target_price 等价格列对 SALES 由后端遮蔽（schema 不返回即不渲）。
 *   本页纯 schema 驱动，不写死价格列。
 *
 * ★引擎实况：SAMPLE_SDN doc_type / sample_sdn 表 / sample_sdn_line 子表 / 流程由后端段2d 注册。
 *   未注册时 PurchaseDocPage 显示「功能已就绪 · 待后端开通」占位（14 律 §8），注册后自动点亮。
 */
import { useMemo } from 'react';
import { Tag } from 'antd';
import PurchaseDocPage from './PurchaseDocPage';

const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';

// gap-5（默认）：超期基准日 = 寄客户日；后端字段命名候选（取首个可用），缺失则不算。
const OVERDUE_BASE_FIELDS = ['sent_to_customer_at', 'sent_at', 'sdn_date', 'created_at'];

// 回签未完成（未签收/未归还）才提示超期；已回签/已归还/转正不再催。
const SIGNED_DONE = new Set(['Y', '已签收', '已回签', '已归还']);

// 状态药丸候选（仅台账筛选提示；真实可走边以 /api/transitions 为准，不写死状态码推进）
const STATUS_ENUM = [
  { text: '已申请 REQUESTED', value: 'REQUESTED' },
  { text: '原厂已发货 VENDOR_SHIPPED', value: 'VENDOR_SHIPPED' },
  { text: '入样品仓 STOCKED_SAMPLE', value: 'STOCKED_SAMPLE' },
  { text: '已寄客户 SENT_TO_CUSTOMER', value: 'SENT_TO_CUSTOMER' },
  { text: '已回签 SIGNED', value: 'SIGNED' },
  { text: '测试中 TESTING', value: 'TESTING' },
  { text: '已转正 CONVERTED', value: 'CONVERTED' },
  { text: '已归还 RETURNED', value: 'RETURNED' },
  { text: '已关闭 CLOSED', value: 'CLOSED' },
];

// —— 超期派生（引擎无原生计算列，前端按行算；后端字段缺时安全返回 null）——

function overdueBaseOf(row) {
  for (const k of OVERDUE_BASE_FIELDS) {
    if (row?.[k]) return String(row[k]);
  }
  return null;
}

// 超期天数 = 今天 − 寄客户日；尚未寄出或基准缺失则 null（不渲假数）
function overdueDaysOf(row) {
  const raw = overdueBaseOf(row);
  if (!raw) return null;
  const base = new Date(raw.replace(' ', 'T'));
  if (Number.isNaN(base.getTime())) return null;
  const d = Math.floor((Date.now() - base.getTime()) / 86400000);
  return Math.max(0, d);
}

// 未回签/未归还 且 已超期（>0 天）→ 标红催归还
function isOverdue(row) {
  const signed = row?.signed_return;
  if (signed != null && SIGNED_DONE.has(String(signed))) return false;
  const d = overdueDaysOf(row);
  return d != null && d > 0;
}

export default function SamplesSdnPage() {
  // ➕ 超期天数前端派生列（PurchaseDocPage 在操作列前注入）
  const derivedColumns = useMemo(() => [
    {
      title: '超期天数', dataIndex: '_overdue_days', width: 110, align: 'right',
      search: false, hideInSetting: true,
      render: (_, row) => {
        const d = overdueDaysOf(row);
        if (d == null) return <span style={{ color: '#bfbbb5' }}>—</span>;
        const overdue = isOverdue(row);
        return (
          <span style={{ fontFamily: MONO, color: overdue ? '#b42318' : '#000', fontWeight: overdue ? 600 : 400 }}>
            {d}{overdue ? ' ⚠' : ''}
          </span>
        );
      },
    },
    {
      title: '回签', dataIndex: '_signed', width: 96, search: false, hideInSetting: true,
      render: (_, row) => {
        const v = row?.signed_return;
        if (v == null || v === '') return <span style={{ color: '#bfbbb5' }}>—</span>;
        const done = SIGNED_DONE.has(String(v));
        return <Tag color={done ? 'green' : 'gold'}>{String(v)}</Tag>;
      },
    },
  ], []);

  return (
    <PurchaseDocPage
      docType="SAMPLE_SDN"
      table="sample_sdn"
      lineTable="sample_sdn_line"
      lineFk="sample_sdn_id"
      title="样品 SDN"
      subtitle="申请 → 原厂发货 → 入样品仓 → 寄客户 → 跟回签 / 算超期 → 测试 → 转正可下正式单"
      numberField="sdn_number"
      statusEnum={STATUS_ENUM}
      editableStates={['REQUESTED', 'VENDOR_SHIPPED', 'STOCKED_SAMPLE', 'SENT_TO_CUSTOMER']}
      lineTitle="样品明细（型号 / 描述 / 数量 / SN-LOT · 网格录入）"
      scanSequence={['material_id', 'serial_lot_number', 'quantity']}
      newLabel="新建样品 SDN"
      primaryToStates={['VENDOR_SHIPPED', 'STOCKED_SAMPLE', 'SENT_TO_CUSTOMER', 'SIGNED', 'TESTING', 'CONVERTED']}
      derivedColumns={derivedColumns}
      intro={{
        title: '一张样品 SDN = 一批向原厂申请的样品（通常免费、量少不符 MOQ）：销售发起 → 产品部定用哪个客户身份 → PA 向原厂申请；走「其他入库[样品]」进样品仓（库存状态 SAMPLE），寄客户后跟回签 / 算超期 / 跟测试，测试通过转正可下正式单',
        description: 'SDN 号 SDN-{C/L}-{YYMM}-{NNN}（中间字母 = 供应商线，月度连号，后端取号 effect 生成）。超期天数 = 今天 − 寄客户日（前端即时算，未回签且超期标红 ⚠ 催归还；gap-5 基准默认寄客户日，待甲方）。一张 SDN 可含多型号多行（明细网格 Excel 粘贴建行 + 扫码录 SN/LOT）。目标价 target_price 等价格列对 SALES 由后端字段防火墙遮蔽——本页按 schema 渲染，销售登录时该列不出现。转正（CONVERTED）后由后端 effect 将该批库存 SAMPLE→AVAILABLE（§5.4）。动作一律走 /api/transitions（按当前状态过滤真实边）→ /api/transition（唯一写入路径），不写死状态码。',
      }}
      todoNote="样品 SDN 为 ➕ 新增 SAMPLE_SDN doc_type（引擎 02 §2.9 明确排除「样品」业务）。需后端段2d 建 sample_sdn 表（含 supplier_id/customer_id/sales_id/sample_nature/signed_return/project_status/target_price/sent_to_customer_at 等 + sample_sdn_line 子表：material_id/description/quantity/serial_lot_number）+ WorkflowDefinition（REQUESTED→VENDOR_SHIPPED→STOCKED_SAMPLE→SENT_TO_CUSTOMER→SIGNED→TESTING→CONVERTED/RETURNED/CLOSED，节点级 allowed_roles）+ 建单取号 effect（sdn_number 供应商线字母 + 月度连号）+ 入样品仓 effect（inbound_type=其他入库[样品]，库存 SAMPLE）+ 转正 effect（CONVERTED→库存 SAMPLE→AVAILABLE）；并把 target_price 加入字段防火墙对 SALES 遮蔽。注册后本页自动点亮，价格列对 SALES 自动隐藏。"
    />
  );
}
