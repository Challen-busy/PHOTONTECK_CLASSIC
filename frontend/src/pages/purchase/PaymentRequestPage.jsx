/**
 * PaymentRequestPage —— 付款申请（发起在采购、执行在财务，决策④，PRD 04a-8）
 *
 * 决策④：付款申请**发起在本采购模块、执行在财务**；本系统只记「到账/付款确认 + 台账」，做账在金蝶。
 * 两种来源（PRD 04a-8 两 Tab，各为一张 PurchaseDocPage 薄包装，无子表 noLines）：
 *   ① 预付 ADVANCE_PAYMENT（✅引擎已 seed）：PO requires_advance_payment → PA 发起 → ★财务审核付款 → 已付款。
 *      流程权威 seed_phase1：START → DRAFT(PA 发起) → FINANCE_REVIEW(★FINANCE 审核付款) → PAID(终态) / CANCELLED。
 *   ② 货后付款 payment_request（➕ 决策④货后付款，预付模型无「关联进项发票/付款到期日/到账确认」列）：
 *      后端段2c ➕ payment_request doc_type + 货后流程后本 Tab 自动点亮；未注册时显示「待后端开通」占位。
 *
 * 动作一律走 /api/transitions（按 doc_type+当前状态过滤真实边）+ /api/transition（唯一写入路径），不写死状态码。
 * 🔒 Q18 字段防火墙：付款金额 amount（采购成本/应付）对销售端（SALES + SA）隐藏——后端遮蔽，本页按 schema 渲染。
 */
import { useState } from 'react';
import { Tabs } from 'antd';
import PurchaseDocPage from './PurchaseDocPage';

const ADVANCE_STATUS = [
  { text: 'DRAFT 录入预付申请', value: 'DRAFT' },
  { text: '★财务审核付款 FINANCE_REVIEW', value: 'FINANCE_REVIEW' },
  { text: '已付款 PAID', value: 'PAID' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

const POST_STATUS = [
  { text: 'DRAFT 发起付款申请', value: 'DRAFT' },
  { text: '待财务执行 PENDING_FINANCE', value: 'PENDING_FINANCE' },
  { text: '★已付款 PAID', value: 'PAID' },
  { text: '已确认到账 CONFIRMED', value: 'CONFIRMED' },
  { text: '驳回 REJECTED', value: 'REJECTED' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

export default function PaymentRequestPage() {
  const [tab, setTab] = useState('advance');

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          付款申请
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          采购 / 供应链 · 决策④：发起在采购、执行在财务；本系统只记到账确认 + 台账，做账在金蝶
        </span>
      </div>

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'advance',
            label: '预付申请',
            children: (
              <PurchaseDocPage
                docType="ADVANCE_PAYMENT"
                table="advance_payment"
                noLines
                title="预付申请"
                subtitle="PO 需预付 → PA 发起 → ★财务审核付款"
                numberField="payment_number"
                statusEnum={ADVANCE_STATUS}
                editableStates={['DRAFT']}
                newLabel="新建预付申请"
                primaryToStates={['FINANCE_REVIEW', 'PAID']}
                intro={{
                  title: '预付（ADVANCE_PAYMENT）= PO requires_advance_payment 时下单即付：PA 发起预付申请（关联 PO + 供应商 + 金额），★财务审核确认付款',
                  description: '付款发起在采购（PA），执行在财务（决策④）：DRAFT 态 PA 可改头；提交进入财务审核付款，财务「确认付款」打付款日期 → 已付款（做账/付款执行在金蝶，本系统只记状态 + 台账）。付款金额对销售端（SALES + SA）由后端字段防火墙遮蔽，本页按 schema 渲染。',
                }}
                todoNote="预付申请复用引擎已 seed 的 ADVANCE_PAYMENT doc_type（START→DRAFT→FINANCE_REVIEW→PAID→CANCELLED，FINANCE_REVIEW 的 allowed_roles 含 FINANCE 为★财务执行节点）。若 /api/schema 失败需后端确认该流程与 payment_number 编号规则已注册；注册后本 Tab 自动点亮。"
              />
            ),
          },
          {
            key: 'post',
            label: '货后付款',
            children: (
              <PurchaseDocPage
                docType="PAYMENT_REQUEST"
                table="payment_request"
                noLines
                title="货后付款"
                subtitle="进项发票审核形成应付 → 到期 → PA 发起 → ★财务执行 → 到账确认"
                numberField="payment_number"
                statusEnum={POST_STATUS}
                editableStates={['DRAFT']}
                newLabel="新建货后付款"
                primaryToStates={['PENDING_FINANCE', 'PAID', 'CONFIRMED']}
                intro={{
                  title: '货后付款（payment_request）= 进项发票审核通过形成应付 → 到付款到期日 → PA 发起付款申请（关联已审发票/PO）→ ★财务执行 → 到账确认（应付余额递减）',
                  description: '货后付款须关联已审进项发票、金额≤应付余额；DRAFT 态 PA 可改头；提交待财务执行，财务执行后打「到账确认标记」+ 台账应付递减（对应 Shipping total 付款日1·2·3 + 付款状态，做账在金蝶）。付款金额对销售端遮蔽，本页按 schema 渲染。',
                }}
                todoNote="货后付款为 ➕ 新增 payment_request doc_type（决策④：预付模型无「关联进项发票/付款到期日/到账确认」列）。需后端段2c ➕ 新建 payment_request 表 + 货后流程（DRAFT→待财务执行→★已付款→已确认到账，★执行节点 allowed_roles=[FINANCE]，到账确认 + 应付递减 + 推金蝶 effect）+ payment_number 编号规则；注册后本 Tab 自动点亮。"
              />
            ),
          },
        ]}
      />
    </div>
  );
}
