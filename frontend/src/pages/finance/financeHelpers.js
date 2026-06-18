/**
 * financeHelpers —— 总账前端共享工具（owns by C·前端 PM，wave-1b）
 *
 * 纯函数，无副作用，无后端依赖：金额格式化 / 人民币大写 / 借贷合计 / 期间匹配 / 科目编码区间过滤。
 * 凭证录入屏与账表查询页共用，避免两处各写一遍。
 *
 * 口径对齐后端（finance_posting.py）：
 *   · 平衡只认本位币（base_debit/base_credit）；前端实时合计 + 差额同样用本位币判平。
 *   · 本位币 = 原币 × 汇率（exchange_rate），本币记账 rate=1 时 base==原币。
 */

import { query } from '../../api';

export const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';

// === 会计科目（F7）一次性缓存：同一公司科目表不频繁变；切公司由后端会话隔离，刷新页面即重取。===
let _accountCache = null;

export async function loadAccounts(force = false) {
  if (_accountCache && !force) return _accountCache;
  const { data } = await query('account', { filters: { is_active: true }, order_by: 'code', limit: 1000 });
  _accountCache = data?.data || [];
  return _accountCache;
}

export function getCachedAccounts() { return _accountCache; }
export function clearAccountCache() { _accountCache = null; }

// 金额千分位（2 位小数）；空/0 给占位破折号交由调用方决定，这里返回字符串。
export function fmtMoney(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return '0.00';
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// 安全转数字（空串/undefined/null → 0）。录入网格里用户清空格子时不抛 NaN。
export function num(v) {
  if (v === '' || v == null) return 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

// 本位币 = 原币 × 汇率，保留 2 位（与 Numeric(16,2) 对齐）。
export function toBase(amount, rate) {
  return Math.round(num(amount) * num(rate || 1) * 100) / 100;
}

const _CN_DIGITS = ['零', '壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖'];
const _CN_UNITS = ['', '拾', '佰', '仟', '万', '拾', '佰', '仟', '亿', '拾', '佰', '仟', '兆'];

/**
 * 人民币金额大写（会计惯例）。对齐金蝶/用友凭证底部「合计大写」。
 * 支持到「分」，整数位到「兆」（13 位，贸易场景足够）。负数前缀「负」（红字凭证可能为负）。
 *
 * 逐位法（自高位向低位，逐位带权位）：连续零折叠成一个「零」，整十/百/千逢节首补单位（万/亿）。
 */
export function digitToChinese(amount) {
  const n = num(amount);
  if (n === 0) return '零元整';
  const negative = n < 0;
  const money = Math.abs(Math.round(n * 100)); // 转「分」整数，规避浮点

  const fen = money % 10;
  const jiao = Math.floor(money / 10) % 10;
  const yuan = Math.floor(money / 100);

  let integerPart = '';
  if (yuan === 0) {
    integerPart = '零';
  } else {
    const s = String(yuan);
    const len = s.length;
    let zeroRun = false;
    for (let i = 0; i < len; i++) {
      const d = Number(s[i]);
      const unitIdx = len - 1 - i;           // 该位权位（个=0,拾=1,…）
      if (d === 0) {
        // 节单位（万/亿/兆，unitIdx 为 4/8/12）即使该位为 0 也要补节单位（若该节有非零位）
        if (unitIdx % 4 === 0 && unitIdx > 0) integerPart += _CN_UNITS[unitIdx];
        zeroRun = true;
      } else {
        if (zeroRun) integerPart += '零';
        integerPart += _CN_DIGITS[d] + _CN_UNITS[unitIdx];
        zeroRun = false;
      }
    }
    // 清理可能的尾部多余「万/亿」（如「壹万零亿」不会发生于本算法，但节单位重复时去重）
    integerPart = integerPart.replace(/零+$/, '');
  }

  let result = (negative ? '负' : '') + integerPart + '元';
  if (jiao === 0 && fen === 0) {
    result += '整';
  } else {
    if (jiao === 0 && fen !== 0) result += '零';        // 元后直接到分须补「零」
    if (jiao !== 0) result += _CN_DIGITS[jiao] + '角';
    if (fen !== 0) result += _CN_DIGITS[fen] + '分';
    else result += '整';
  }
  return result;
}

/**
 * 分录合计（本位币口径，与过账闸一致）+ 差额 + 是否平衡。
 * 返回 { totalDebit, totalCredit, diff, balanced }（均 number；balanced 容差 0.005）。
 * 原币合计供展示用（外币时与本位币不同），单独算。
 */
export function summarizeEntries(rows = []) {
  let totalDebit = 0, totalCredit = 0;
  let totalDebitBase = 0, totalCreditBase = 0;
  for (const r of rows) {
    if (r?._delete) continue;
    totalDebit += num(r.debit);
    totalCredit += num(r.credit);
    totalDebitBase += num(r.base_debit);
    totalCreditBase += num(r.base_credit);
  }
  const round2 = (x) => Math.round(x * 100) / 100;
  totalDebit = round2(totalDebit);
  totalCredit = round2(totalCredit);
  totalDebitBase = round2(totalDebitBase);
  totalCreditBase = round2(totalCreditBase);
  const diff = round2(totalDebitBase - totalCreditBase);
  return {
    totalDebit, totalCredit,
    totalDebitBase, totalCreditBase,
    diff,
    balanced: Math.abs(diff) < 0.005 && rows.filter((r) => !r?._delete).length > 0,
  };
}

// 据凭证日期（YYYY-MM-DD）在期间列表里找匹配期（start_date <= date <= end_date）。
export function findPeriodByDate(periods = [], dateStr) {
  if (!dateStr) return null;
  return periods.find((p) => dateStr >= p.start_date && dateStr <= p.end_date) || null;
}

// 科目编码区间过滤（前端做，后端无范围算子）：codeFrom/codeTo 闭区间，字符串比较（科目编码定长前缀友好）。
export function filterByCodeRange(rows = [], codeFrom, codeTo, codeKey = 'account_code') {
  return rows.filter((r) => {
    const c = r[codeKey] ?? '';
    if (codeFrom && c < codeFrom) return false;
    if (codeTo && c > codeTo) return false;
    return true;
  });
}

// 五大类中文标签（对齐 Account.account_type）。
export const ACCOUNT_TYPE_LABEL = {
  ASSET: '资产',
  LIABILITY: '负债',
  EQUITY: '权益',
  REVENUE: '收入',
  EXPENSE: '费用',
  COGS: '成本',
};
