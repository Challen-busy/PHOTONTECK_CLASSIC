/**
 * OutboundSummary —— 出库汇总同页视图（PRD 03b 页面 2 决策⑦ + 页面 3）
 *
 *  - mode="model"   基本出库：按 型号(material_id)/性质(goods_nature) 聚合出库数量（同页 Tab 视图，不拆页）
 *  - mode="inbound" 入仓编号·出库总数量透视：按 入仓编号 聚合出库总量（反查消单口径，访谈 05 L793-826）
 *
 * 纯前端从拣货明细行聚合（明细=真相源，汇总=投影；与页面 2 同一份 lineRows）。
 * 不写死成本列：本视图只聚合数量，成本/单价不在此出现（防火墙无关）。红线：无斑马纹、无跳页。
 */
import { useMemo } from 'react';
import { Empty } from 'antd';

const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';

const HEAD = {
  model: [['_key', '型号 · 性质'], ['nature', '性质'], ['count', '行数'], ['qty', '出库总数量']],
  inbound: [['inbound', '入仓编号'], ['nature', '性质'], ['count', '行数'], ['qty', '出库总数量']],
};

function aggregate(rows, mode) {
  const map = new Map();
  for (const r of rows) {
    const qty = Number(r.quantity || 0);
    let key;
    let base;
    if (mode === 'inbound') {
      key = r.inbound_number || '（未指定）';
      base = { inbound: key, nature: r.goods_nature || '—' };
    } else {
      const model = r._material != null ? `#${r._material}` : (r.serial_lot_number || '（未带出型号）');
      key = `${model}|${r.goods_nature || ''}`;
      base = { _key: model, nature: r.goods_nature || '—' };
    }
    const cur = map.get(key) || { ...base, count: 0, qty: 0 };
    cur.count += 1;
    cur.qty += qty;
    map.set(key, cur);
  }
  return Array.from(map.values()).sort((a, b) => b.qty - a.qty);
}

export default function OutboundSummary({ rows = [], mode = 'model' }) {
  const data = useMemo(() => aggregate(rows, mode), [rows, mode]);
  const head = HEAD[mode] || HEAD.model;
  const total = useMemo(() => data.reduce((s, r) => s + (r.qty || 0), 0), [data]);

  if (!rows.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无拣货明细，暂无可汇总数据" />;
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'rgba(245,242,239,0.6)' }}>
            {head.map(([, label]) => (
              <th key={label} style={{
                textAlign: label.includes('数量') || label === '行数' ? 'right' : 'left',
                padding: '8px 12px', color: '#777169', fontWeight: 500, whiteSpace: 'nowrap',
              }}>{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i} style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
              {head.map(([k, label]) => {
                const isNum = label.includes('数量') || label === '行数';
                return (
                  <td key={k} style={{
                    padding: '8px 12px', whiteSpace: 'nowrap',
                    textAlign: isNum ? 'right' : 'left',
                    fontFamily: isNum ? MONO : undefined,
                  }}>
                    {r[k] == null || r[k] === '' ? <span style={{ color: '#bfbbb5' }}>—</span> : String(r[k])}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr style={{ borderTop: '2px solid rgba(0,0,0,0.1)', fontWeight: 600 }}>
            <td style={{ padding: '8px 12px' }} colSpan={head.length - 1}>合计</td>
            <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: MONO }}>{total}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
