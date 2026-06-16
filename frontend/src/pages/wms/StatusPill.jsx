/**
 * StatusPill —— WMS 状态药丸（淡底深字，沿用全局克制配色；引擎真实 state code）
 * 拆成独立文件以便 wmsHelpers（纯函数）与组件互不污染 HMR。
 */
import { WMS_STATUS_STYLE } from './wmsStatusStyle';

export function StatusPillInline({ value }) {
  if (value == null || value === '') return <span style={{ color: '#bfbbb5' }}>—</span>;
  const s = WMS_STATUS_STYLE[value] || { bg: '#f5f2ef', color: '#4e4e4e' };
  return (
    <span style={{
      display: 'inline-block', padding: '2px 10px', borderRadius: 4,
      background: s.bg, color: s.color, fontSize: 12, fontWeight: 500, letterSpacing: '0.02em',
    }}>{value}</span>
  );
}

export default StatusPillInline;
