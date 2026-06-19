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

// ============================================================================
// 枚举码 → 中文字典（A 方案：集中枚举字典）。与后端同源（穷举结果），只改显示不碰存储码。
// 规范存储码不可改；自定义财务页（自建列渲染枚举）统一查这里，避免各页各写一份。
// 通用 MasterDataPage 壳不 import 本字典（解耦）——它优先用后端 schema 附带的 field.value_labels。
// ============================================================================

// 非状态类枚举：列名 → { 码: 中文 }。
export const ENUM_LABELS = {
  account_type: { ASSET: '资产', LIABILITY: '负债', EQUITY: '权益', REVENUE: '收入', EXPENSE: '费用', COGS: '成本' },
  balance_direction: { DEBIT: '借方', CREDIT: '贷方' },
  dr_cr: { DR: '借', CR: '贷' },
  voucher_type: { GENERAL: '普通凭证', RECEIPT: '收款凭证', PAYMENT: '付款凭证', TRANSFER: '转账凭证' },
  reversal_type: { NORMAL: '普通(蓝字)', RED: '红字反向' },
  source_type: { CUSTOMER: '客户', SUPPLIER: '供应商', EMPLOYEE: '员工', DEPT: '部门', PROJECT: '项目' },
  direction: { IN: '流入', OUT: '流出' },
  cash_direction: { IN: '现金流入', OUT: '现金流出', BOTH: '不限方向' },
  method_type: { CASH: '现金', TRANSFER: '转账', NOTE: '票据', WIRE: '电汇' },
  account_source: { FIXED: '固定科目', CUSTOMER: '客户对应科目', SUPPLIER: '供应商对应科目', MATERIAL_DEFAULT: '物料默认科目' },
  tax_handling: { NONE: '不涉税', INCLUSIVE: '价税合计', EXCLUSIVE: '价外不含税', TAX_ONLY: '仅税额' },
  date_source: { CREATE: '建单日', BIZ: '业务日' },
  standard: { CAS: '企业会计准则(内地)', HKFRS: '香港财务报告准则' },
  measurement_basis: { HISTORICAL_COST: '历史成本', FAIR_VALUE: '公允价值' },
  depreciation_method: { STRAIGHT_LINE: '直线法', DOUBLE_DECLINING: '双倍余额递减法' },
  inventory_valuation: { WEIGHTED_AVG: '加权平均', FIFO: '先进先出' },
  cost_method: { WEIGHTED_AVG: '加权平均', FIFO: '先进先出' },
  bad_debt_method: { ALLOWANCE: '备抵法', DIRECT: '直接转销法' },
  scheme_type: { TRANSFER: '自动转账', AMORTIZATION: '摊销', ACCRUAL: '预提' },
  statement: { BS: '资产负债表', IS: '利润表' },
  note_type: { COMMERCIAL: '商业承兑汇票', BANK: '银行承兑汇票' },
  payment_type: { ADVANCE: '预付', POST_DELIVERY: '货后付款' },
  track_status: {
    PENDING_ACCEPT: '待接单', ACCEPTED: '已接单待货期', ETA_GIVEN: '已给货期',
    SHIPPED: '已发货', PARTIAL: '部分到货', RECEIVED: '已到货',
  },
  transaction_type: { IN: '入库', OUT: '出库', ADJUST: '调整' },
};

// 状态码 → 中文（跨表通用兜底，含各单据 status 全集）。
export const STATUS_LABELS = {
  DRAFT: '草稿/录入', AUDITED: '已审核', REVIEWED: '出纳已复核', POSTED: '已过账',
  ACTIVE: '启用', INACTIVE: '停用',
  OPEN: '未结账(开启)', LOCKED: '已锁定', CLOSED: '已结账',
  PENDING: '待处理/待付款', PARTIAL: '部分付款', PARTIAL_PAID: '部分付款', PAID: '已付清',
  OVERDUE: '逾期', SETTLED: '已结算', BAD_DEBT: '坏账', COLLECTING: '收款中',
  INVOICED: '已开票', CONTRACT_REGISTERED: '已登记合同', CREDIT_MANAGED: '信用已管理',
  VOUCHER_PROCESSED: '凭证已处理', NOTES_RECV: '应收票据', CONFIRMED: '已确认到账',
  CANCELLED: '已取消', FINANCE_REVIEW: '财务审核中', PENDING_REVIEW: '待财务审核',
  PENDING_FINANCE: '待财务执行', AP_CREATED: '已生成应付', AR_CREATED: '已生成应收',
  MATCHING: '勾稽中', HELD: '持有中', UNALLOCATED: '未核销', ALLOCATED: '已核销',
  START: '开始', VOID: '作废', REVERSED: '已红冲',
};

/**
 * 枚举码 → 中文。查不到原样返回 value 兜底，绝不显 undefined。
 * @param {string} field 列名（如 'account_type' / 'direction' / 'standard'）
 * @param {*} value 存储码（如 'ASSET' / 'IN' / 'HKFRS'）
 */
export function enumLabel(field, value) {
  if (value == null || value === '') return '';
  return ENUM_LABELS[field]?.[value] ?? STATUS_LABELS[value] ?? String(value);
}

/** 状态码 → 中文（StatusPill / status 列专用，查不到原样返回兜底）。 */
export function statusLabel(value) {
  if (value == null || value === '') return '';
  return STATUS_LABELS[value] ?? String(value);
}

// 五大类中文标签（对齐 Account.account_type）。沿用 ENUM_LABELS.account_type，保留具名导出向后兼容。
export const ACCOUNT_TYPE_LABEL = ENUM_LABELS.account_type;
