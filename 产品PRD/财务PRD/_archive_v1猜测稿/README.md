# 财务PRD · 总览 README（PHOTONTECK 自研财务ERP·完全替代金蝶）

> 主编 PM 收口文档 · v1 · 2026-06-17 · 仅本文件为新建，不改任何已有 .md
> 战略前提（甲方拍板）：**自研出全部法定报表+申报数据 → 金蝶下线**；上线先期初导入 + 与金蝶并行对账验证期，验平后金蝶退场。
> 引擎事实（已 grep 核实）：FastAPI + SQLAlchemy2 async + PostgreSQL；React19 + Vite + AntD Pro。引擎核心三件 `core/registry.py`、`services/workflow.py(execute_transition)`、`services/commands.py(execute_command)` **字节级零 diff**；财务全靠注册扩展点（`@register_command`/`@register_transition_effect`/`@register_transition_validator` + `__doc_types__` + `WorkflowDefinition.states` JSONB）+ 审计四本（CommandLog/WorkflowLog/AgentLog/WorkflowDefAuditLog）实现，**纯扩展不改核心**。

---

## 一、PRD 总览（14 个文件）

| 文件 | 标题 | 层 | 主对象 | 核心建造量一句话 |
|---|---|---|---|---|
| `00-编写规范与对象范式.md` | 编写宪法·8列对象范式·5分类·8件套·UI惯例·14决策·全对象索引 | — | — | 所有模块写作前必读的协作宪法 |
| `01-基石.md` | Layer0 地基（科目/期间/币种/★凭证内核/★科目映射框架/角色+SoD） | **L0** | Account / FiscalYear / AccountingPeriod / ExchangeRate / **Voucher内核** / **AccountMappingRule** / 角色 | 状态机已 seed，**过账 effect/映射框架/蓝冲红冲逆向边/3新角色全 ❌需新建**——基石主建造量 |
| `02-总账与凭证.md` | 总账与凭证（核心·全财务写入心脏） | L1 | VOUCHER / VOUCHER_ADJUSTMENT / AccountBalance / 账簿视图 | `finance.post_voucher`/`unpost_voucher`/`red_reversal`/反过账反审核边/SoD validator |
| `03-应收管理.md` | 应收（AR + 票据 + 核销 + 账龄 + 坏账） | L1 | ACCOUNTS_RECEIVABLE / NotesReceivable / ARSettlement / CustomerCredit / aging_analysis | 收款过账+坏账计提 effect；票据状态机；账龄补坏账取数 |
| `04-应付管理.md` | 应付（进项发票+暂估转实+付款+预付+信用） | L1 | PURCHASE_INVOICE / ACCOUNTS_PAYABLE / PAYMENT_REQUEST / ADVANCE_PAYMENT / SupplierCredit / 暂估凭证 | 暂估应付 effect、发票冲回转实、付款过账、AP账龄、APSettlement(gap) |
| `05-出纳与资金.md` | 出纳资金（日记账+银行对账+调拨+票据） | L1 | BankAccount / CashJournal / BankJournal / BankReconciliation / FundTransfer / NotesPayable | 6 个新模型 + 全套日记账/对账/调拨 effect（本模块新建量最大之一） |
| `06-存货核算与成本.md` | 存货核算与成本（移动加权+暂估+差异+平销返利） | L1 | InventoryValuation / InventoryTransaction / 暂估应付 / InventoryCostAdjustment | WMS 数量价值已实现，**补通向总账的过账桥 + 暂估/差异/红冲三套会计政策** |
| `07-固定资产与折旧.md` | 固定资产与折旧（购置/月折旧/减值/处置） | L1 | FixedAssetCategory / FixedAsset / DepreciationRun / 折旧明细 / 固资台账 | 全模块 ❌新建；折旧批手动触发+提醒；**1603/1606 科目缺口阻断** |
| `08-薪酬与费用报销.md` | 薪酬+费用报销（人力成本+期间费用→利润表大头） | L1 | PAYROLL_RUN / EXPENSE_CLAIM / Employee（+子表） | 全模型 ❌新建；计提/发放/报销/付款 effect；部门辅助核算锚点 |
| `09-税务与收入确认.md` | 税务+收入确认（★CAS14 五步法+增值税+所得税+HK利得税） | L1 | RevenueRecognition / VatAssessment / IncomeTaxProvision / ContractBalance / 税率主数据 | 收入与开票解耦（合同资产1231/合同负债2205）；增值税/所得税/利得税计提 |
| `10-期末结账.md` | 期末（调汇/结转损益/结账向导/反结账/期初建账） | **L2** | FX调汇批 / 结转损益批 / AccountingPeriod结账 / 期初建账批 | 4 个期末 effect + 校验清单 validator + 期初导入 command |
| `11-财务报表与账簿.md` | 三大报表 + 四账簿 + 试算表 | **L2** | ReportLineDef / BALANCE_SHEET / INCOME_STATEMENT / CASH_FLOW / 三账簿 / 试算+科目余额 | 报表项目↔科目映射框架 + 取数引擎 + 下钻；**零 effect 零 command 纯读** |
| `12-业财一体化映射矩阵.md` | 业财一体化映射矩阵（自动凭证发动机） | L1核心 | AccountMappingRule / 自动 Voucher / 业务红冲广播 + **全量取数矩阵§4** | 所有 L1 模块的"公共发动机"，全量业务单→分录映射汇编 |
| `13-多组织账套与权限矩阵.md` | 多组织账套与权限矩阵 | L1横切 | Company(账套) / COA模板 / FiscalYear / NumberingRule / UserCompanyAccess / CrossCompanySummary | 6 账套行级隔离地基 + 5 角色×对象×动作×字段权限矩阵 + SoD 开关 |

---

## 二、阅读顺序（建议）

```
00 编写规范（先读，理解 8 列范式 + 5 分类 + 14 决策）
 └─ 01 基石（必读，所有科目码/状态码/角色/取数格式的唯一源）
     └─ 12 业财一体化映射矩阵（理解"自动凭证发动机"机制——全 L1 模块的公共底座）
         └─ 13 多组织账套与权限（账套隔离+权限地基，跨所有模块）
             └─ L1 交易模块（02→03→04→05→06→07→08→09，可任意序，互不依赖）
                 └─ L2 收口（10 期末结账 → 11 报表账簿，最后读）
```

凡需快速定位"某业务单怎么变凭证"：直接看 **12-§4 全量取数矩阵**；凡需"某对象字段/状态机/验收"：看对应模块的 §3/§状态机/§验收。

---

## 三、★分层依赖图（Layer0 → Layer1 → Layer2）

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Layer0 基石（串行·先封板·digest 下发后 L1 才能并行开工）   [01-基石]          │
│  ① 科目表 CAS/HKFRS 双模板 + 备抵方向独立标                                   │
│  ② 会计年度/期间（默认27号截止/12月分割）+ 期间锁 hard_rule                   │
│  ③ 币种/本位币（公司级）+ 汇率表（入账即时/期末调汇）                         │
│  ④ ★凭证内核 VOUCHER（录入→审核→过账 + 蓝冲/红冲逆向边）                      │
│  ⑤ ★AccountMappingRule 科目映射框架 + map_to_voucher_entries（业财翻译规则库）│
│  ⑥ 财务角色 CASHIER/ACCOUNTANT/FINANCE_MANAGER + 职责分离可配开关             │
│  ⑦ finance.post_voucher / unpost_voucher / red_reversal（唯一过账写入路径）   │
│       └────────── 封板（核心契约冻结 + digest 下发）──────────┐               │
└──────────────────────────────────────────────────────────────┼──────────────┘
                                                                 ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Layer1 交易模块（并行·各自只依赖 L0 契约·共享 12 发动机+post_voucher）        │
│  02 总账手工凭证   03 应收 AR   04 应付 AP   05 出纳资金/票据/对账            │
│  06 存货成本(移动加权+暂估)   07 固定资产折旧   08 薪酬+费用报销              │
│  09 税务(增值税/所得税/HK利得税)+收入确认 CAS14                              │
│  12 业财一体化映射矩阵（自动凭证发动机=全 L1 的公共底座，与基石⑤⑦同源）       │
│  13 多组织账套+权限（横切·账套隔离+权限地基，覆盖所有模块）                    │
│       └─ 各模块过账 effect 统一写 AccountBalance（同一契约，不变量5）          │
└────────────────────────────────────────────────────────────┼────────────────┘
                                                               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Layer2 收口（依赖 L1 全部已过账·报表最后出）                                  │
│  10 期末：调汇 → 结转损益 → 结账向导 → 反结账 → 期初建账                       │
│  11 报表：资产负债表 / 利润表 / 现金流量表(间接法) + 四账簿 + 试算/科目余额    │
│  （管理看板轻量复用 reports 壳；合并报表仅占位不做）                           │
└────────────────────────────────────────────────────────────────────────────┘
```

**铁律**：
1. **L0 必须先封板**——L1 任何模块不得提前定义自己的科目码/状态码/过账口径，一律引用 L0 契约（digest），冲突即停。
2. L1 各模块**并行**，唯一共享 = L0 科目集 + 过账 effect 契约 + AccountBalance 写法 + 12 发动机的 `map_to_voucher_entries`。
3. **报表（D 类）排最后**——口径在 L1 全部落地后才能定稿。
4. 期末过程（E 类）依赖全部 L1 凭证已过账，归 L2。

---

## 四、全财务对象总索引（按 5 类分组）

> 标注：✅引擎已有 / ➕扩展现有 / ❌需新建（已 grep 核实 2026-06-17）。

### A 主数据（长期存在·被引用·不冲销只停用/版本化）
| 对象 | model | 状态 | 模块 |
|---|---|---|---|
| 会计科目 | Account | ✅ | 01/13 |
| 科目表模板 | ChartOfAccountsTemplate | ❌新建（CAS/HKFRS 双套） | 13 |
| 会计年度/期间 | FiscalYear / AccountingPeriod | ✅ | 01/13 |
| 币种/本位币 | Company.currency + home_currency | ✅/➕ | 01/13 |
| 汇率表 | ExchangeRate | ✅ | 01 |
| ★科目映射规则 | AccountMappingRule | ❌新建 | 01(框架)/12(全量) |
| 公司/账套 | Company（➕6列） | ➕ | 13 |
| 凭证序列 | NumberingRule | ✅ | 13 |
| 用户×公司授权 | UserAccount / UserCompanyAccess（+3角色常量） | ✅/➕ | 13 |
| 客户信用 | CustomerCredit | ✅ | 03 |
| 供应商信用 | SupplierCredit | ✅（缺 upsert 命令） | 04 |
| 银行账户 | BankAccount | ❌新建 | 05 |
| 固资类别 | FixedAssetCategory | ❌新建 | 07 |
| 员工 | Employee | ❌新建 | 08 |
| 纳税人身份/物料默认税率/TaxRateConfig | Company.taxpayer_type / Material.default_tax_rate / TaxRateConfig | ➕/❌ | 09 |
| 报表项目映射 | ReportLineDef + ReportLineFormula | ❌新建 | 11 |

### B 交易凭证单据（完整状态机·可过账·强审计·核心冲销对象）
| 对象 | model / doc_type | 状态 | 模块 |
|---|---|---|---|
| ★记账凭证 | Voucher/VoucherEntry · VOUCHER | ✅状态机·❌过账 effect | 01/02/12 |
| 调整期凭证 | VOUCHER_ADJUSTMENT（第13期） | ✅ | 02/10 |
| 应收单 | AccountsReceivable · ACCOUNTS_RECEIVABLE | ✅（缺过账层） | 03 |
| 应收票据 | NotesReceivable | ✅（➕状态机+voucher_id） | 03/05 |
| 应付票据 | NotesPayable | ❌新建 | 05 |
| 核销明细 | ARSettlement / APSettlement | ✅ / ❌新建 | 03/04 |
| 进项发票 | PurchaseInvoice · PURCHASE_INVOICE | ✅（缺凭证） | 04 |
| 付款申请 | PaymentRequest · PAYMENT_REQUEST | ✅（缺凭证） | 04 |
| 预收/预付 | AdvanceReceipt / AdvancePayment | ✅（缺凭证） | 03/04/05 |
| 现金/银行日记账 | CashJournal / BankJournal | ❌新建 | 05 |
| 银行对账 | BankReconciliation + BankStatementLine | ❌新建 | 05 |
| 资金调拨 | FundTransfer | ❌新建 | 05 |
| 暂估应付凭证 | Voucher(auto) | ❌新建 effect | 04/06 |
| 固资卡片 | FixedAsset · FIXED_ASSET | ❌新建 | 07 |
| 工资计提单 | PayrollRun · PAYROLL_RUN | ❌新建 | 08 |
| 费用报销单 | ExpenseClaim · EXPENSE_CLAIM | ❌新建 | 08 |
| 收入确认单 | RevenueRecognition · REVENUE_RECOGNITION | ❌新建 | 09 |
| ★红冲凭证 | 红字 Voucher（顺 source_doc 回链） | ❌新建 command/effect | 01/12+各业务 |

### C 台账/余额派生只读（不可手工写·由 B 过账派生·随过账自动重算）
| 对象 | model | 状态 | 模块 |
|---|---|---|---|
| 科目余额 | AccountBalance | ✅（待过账 effect 写） | 01/02 |
| 应付台账 | AccountsPayable | ✅ | 04 |
| 存货计价台账 | InventoryValuation | ✅ | 06 |
| 存货流水 | InventoryTransaction | ✅（voucher_id 恒空=缺口） | 06 |
| 折旧明细/固资台账 | FixedAssetDepreciationLine / fixed_asset_ledger | ❌新建 | 07 |
| 合同资产/负债台账 | ContractBalance | ❌新建 | 09 |
| 跨公司汇总 | CrossCompanySummary | ❌新建薄路由 | 13 |

### D 报表派生定期（口径固定·可反复出·只读·改源重出）
| 对象 | 现状 | 模块 |
|---|---|---|
| 试算平衡表 / 科目余额表 | ✅ reports.trial_balance/account_balance（➕补范围+下钻+导出） | 11 |
| 账龄分析（AR/AP） | ✅ AR 版 / ❌ AP 版 | 03/04 |
| 总分类账/明细分类账/多栏账 | ❌新建（seed 节点占位） | 02/11 |
| 资产负债表/利润表/现金流量表(间接法) | ❌新建 | 11 |
| 增值税/所得税申报数据 | ❌新建 | 09 |
| 管理看板 | ➕轻量复用 reports 壳 | 11/13 |

### E 期末过程批处理（一次性向导式·前置校验清单·UX律14唯一向导例外）
| 对象/动作 | 状态机落点 | 状态 | 模块 |
|---|---|---|---|
| 期末调汇 | VOUCHER POSTED→FX_ADJUSTED | ✅状态 ❌effect | 10 |
| 结转损益 | VOUCHER FX_ADJUSTED→PL_TRANSFERRED | ✅状态 ❌effect | 10 |
| 期末结账 | VOUCHER PL_TRANSFERRED→CLOSED + AccountingPeriod | ✅状态 ❌校验+effect | 10 |
| 反结账 | AccountingPeriod CLOSED→OPEN | ❌新建 | 10 |
| 期初建账 | command finance.import_opening_balance | ❌新建 | 10 |
| 坏账计提 | E 批处理 | ❌新建 | 03 |
| 暂估转实/成本差异冲回 | InventoryCostAdjustment | ❌新建 | 06 |
| 折旧计提 | DepreciationRun | ❌新建 | 07 |
| 增值税/所得税/利得税计提 | VatAssessment / IncomeTaxProvision | ❌新建 | 09 |

---

## 五、全局不变量（每模块逐条遵守·已逐文核对一致）

1. **借贷平衡**：过账前 `Σ借=Σ贷`（hard_rule），不平禁过账，精确提示差额。
2. **过账不可改**：`Voucher.status=POSTED` 只能蓝冲/红冲；AccountBalance/账簿/报表/科目余额是**只读派生**。
3. **期间锁**：已结账期（`AccountingPeriod.status=CLOSED`）不可过账；跨期用调整凭证（VOUCHER_ADJUSTMENT 第13期）。
4. **业财同源**：业务单与凭证**同事务原子生成**，任一失败整体回滚。
5. **财务唯一写入路径 = 凭证过账**：任何科目余额变动必经 Voucher→VoucherEntry→AccountBalance（**唯一例外=期初建账写 opening 列，建账期一次性**）。
6. **审计四本**：CommandLog/WorkflowLog/AgentLog/WorkflowDefAuditLog 全程留痕。
7. **字段防火墙**：成本/买价对 SALES + SALES_ASSISTANT 隐藏（字段级 mask）。
8. **公司行级隔离**：`company_id` NOT NULL，所有查询走 `_company_filter(user)`，**绝不合账**（合并报表仅占位）。
9. **冲销不留脏数**：未结账蓝冲不留负数（直接改/删原蓝字）；已结账红冲留红字+蓝字配对（发生额净额=0，余额不受影响）；跨年损益错账经 **6901 以前年度损益调整**。
10. **业务红冲必广播**：退货/退款/采购退货自动生成红字冲销凭证草稿 + **站内通知全部财务**（`Notification.recipient_role`）。

**蓝冲 vs 红冲术语（决策12·已 WebSearch 核实金蝶 K3 标准术语）**：
- **反审核**=AUDITED→DRAFT（撤销审核回可改，本期未过账）。
- **反过账**=POSTED→AUDITED（撤销过账+回退 AccountBalance，蓝冲核心，仅 OPEN 期）。
- **反结账**=CLOSED 期重新打开（期末结账模块；反结账后才能反过账）。
- **蓝冲**（未结账）=反过账→反审核→改/删→重过账，凭证始终蓝字（正数），账上不留负数。
- **红冲**（已结账）=原凭证不动，新建红字（负数）冲销凭证 + 蓝字重做，红蓝配对净额=0，留痕审计。

---

## 六、★所有待甲方/财务确认 gap 汇总表（按主题归并·逐模块出处）

> 全部 gap 均为「会计政策/口径/科目码/默认值」需财务拍板，**不阻塞引擎建造（机制可先建，政策值后填）**，但标★者为开工前必须先签。

### 6.1 ★科目码缺口（基石封板前必补，否则映射无目标科目）
| # | gap | 出处 | 现状 / 默认建议 |
|---|---|---|---|
| G-COA-1 | ★**1603 固定资产减值准备 / 1606 固定资产清理** 未进 01-基石 §1.5 种子科目集（§1.4 仅列 1603 于备抵清单、seed 实测无 1603/1606）——减值/处置分录硬依赖 | 07/01 | 须 CAS/HKFRS 模板补 1603(ASSET,CREDIT) + 1606(ASSET,DEBIT) 并回灌基石 §1.5 |
| G-COA-2 | ★**6801 所得税费用** 未在基石科目集列出（基石列到 6711/6901） | 09/01 | 须补 6801(EXPENSE,DEBIT)；HK 用 HKFRS Profits tax 科目 |
| G-COA-3 | **222103 应交税费-应交个人所得税** 未在基石种子集列出（08/09 均用此码代扣个税） | 08/09/01 | 须补 222103 明细；HK 无强制个税科目按 region 切换 |
| G-COA-4 | **1221 其他应收款** 未在基石列出——员工借款/备用金核销需用 | 08/01 | 借款核销本期占位，若上线须补 1221 |
| G-COA-5 | **未交增值税 22210x / 应交城建税·教育附加 22210x** 二级明细码未定 | 09/01 | 增值税计提+附加税分科目挂账须财务给明细码 |
| G-COA-6 | **2202xx 暂估应付** 具体子目码未定 | 04/06/12 | 暂估应付明细码须财务给 |

### 6.2 ★收入确认 / CAS14（决策6）
| # | gap | 出处 | 默认建议 |
|---|---|---|---|
| G-REV-1 | ★控制权转移时点默认值（SHIPMENT 发货 vs CUSTOMER_RECEIVED 客户签收），逐公司/逐客户缺省 | 09/03/06/12 | 决策6 已定可配，缺省值待逐家签 |
| G-REV-2 | 开票与收入解耦的凭证拆分粒度（开票即全额挂 1231 合同资产 vs 控制权转移点确认；是否对所有商品线一致） | 09/12 | 默认控制权转移确认、开票仅生应收+销项 |
| G-REV-3 | 单项履约义务拆分粒度（一单一义务 vs 按行/按批次） | 09 | 贸易单多为单一履约义务，复杂分摊待定 |
| G-REV-4 | COGS 结转时点是否与 CAS14 收入确认同步（配比）；货已发未确认收入时是否先挂"发出商品"过渡科目 | 06/09 | 待财务确认配比口径 |

### 6.3 ★成本与暂估（决策4/5）
| # | gap | 出处 | 默认建议 |
|---|---|---|---|
| G-COST-1 | 暂估估价单价优先级（PO价→合同价→上次移动加权→手工估）；无价时是否禁 0 暂估 | 06/04 | 建议禁 0 暂估强制手工 |
| G-COST-2 | 暂估冲回差异去向（已售进 6401 vs 在库调 1405；按数量还是金额拆）；容差%与超容差处理 | 04/06/12 | 默认调 1405（影响移动加权） |
| G-COST-3 | ★**平销返利会计政策（金蝶坑核心）**：分摊基准=购进数量比例 vs 销售额比例；返利含税进项税转出红字；确认时点；区分销量挂钩返利(冲成本)vs现金折扣(冲财务费用) | 06 | 待财务逐条定 |
| G-COST-4 | 盘亏去向（6701 资产减值 vs 6602 管理费用 vs 1901 待处理财产损溢）；盘盈（冲管理费用 vs 6711/6051） | 06/12 | 待定 |
| G-COST-5 | 存货跌价准备 1471 是否本期做（可变现净值测试）；粒度单物料 vs 类别 | 06 | 默认期末做 |
| G-COST-6 | 暂估冲回时点：发票审核时冲回（默认）vs 保留月末暂估+次月初自动红冲可选模式 | 04/06 | 默认审核时冲回 |
| G-COST-7 | cost_method 文案纠正：labels.py 现 `WEIGHTED_AVG="全月加权平均"`，本项目锁**移动加权 MOVING_AVG（逐笔即时）**，展示文案须纠为"移动加权平均" | 06 | 已确认纠正（labels 已有 MOVING_AVG 项） |

### 6.4 ★税务（决策7）
| # | gap | 出处 | 默认建议 |
|---|---|---|---|
| G-TAX-1 | 出口/保税免抵退税（ZERO 税率码+退税率） | 09 | 默认不做 |
| G-TAX-2 | 增值税申报后错账口径（红冲下期调 vs 更正申报）+《申报表》2025/2版字段映射 | 09 | 待定 |
| G-TAX-3 | CN 小微企业所得税优惠（应纳税所得额≤300万分段减按） | 09 | 默认 25% 全额 |
| G-TAX-4 | 递延所得税（暂时性差异/税会折旧差异 CAS18） | 09/07 | 默认不做，仅手录纳税调整额 |
| G-TAX-5 | 附加税地区差异（城建7/5/1%+教育附加） | 09 | 默认 7%+3%+2% 公司可配 |
| G-TAX-6 | HK 利得税两级制集团仅一家享优惠——3 家 HK 是否同集团 | 09/13 | 待定优惠归属 |
| G-TAX-7 | 固资进项税可抵扣判定（一次性抵扣 vs 计入成本，按 tax_type+用途）；处置销项税率（13% vs 简易3%减按2%） | 07 | 待财务给类别/物料级判定规则 |
| G-TAX-8 | 小规模纳税人简易计税/不可抵扣进项科目码（不走 222101/222102） | 09/12 | 待财务给科目码 |
| G-TAX-9 | 销项税额拆分口径（AR 本模块拆 tax_amount vs 统一从凭证 222102 取，避免双源） | 03/09 | 建议统一从凭证取 |

### 6.5 坏账 / 往来 / 信用（决策13）
| # | gap | 出处 | 默认建议 |
|---|---|---|---|
| G-AR-1 | 坏账计提比例/方法（账龄比例 current0/1-30%1/31-60%5/61-90%20/90+50% vs 单独认定 vs CAS8/HKFRS ECL 三阶段），CN/HK 各公司比例表 | 03 | 默认账龄比例，待定 |
| G-AR-2 | 坏账转销审批链（一律 BOSS vs 按金额阈值分级） | 03 | 待定 |
| G-AR-3 | 信用超额处置（硬拦禁开票 vs 仅预警放行；是否做公司级硬拦开关） | 03/04 | 现状不硬拦 |
| G-AR-4 | 一收多销/一付多票默认分配规则（FIFO按到期日 vs 按发票号 vs 全手工）；是否允许跨客户核销 | 03/04 | 待定 |
| G-AR-5 | 账龄桶阈值/基准日（30/60/90 四桶；期末日 vs today；外币桶按期末汇率折算） | 03 | 默认四桶 |
| G-AR-6 | 预收冲抵时点（发货即冲 vs 收入确认即冲 vs 手工），须与 G-REV-1 对齐 | 03 | 待定 |
| G-AR-7 | APSettlement 一付多票核销明细模型是否纳入本期（AP 侧缺对称模型） | 04 | 待定 |
| G-AR-8 | 供应商信用占用口径（used_amount 是否计暂估、在途预付/PO） | 04 | 待定 |
| G-AR-9 | 业务红冲通知范围（决策13"所有财务"是否含 BOSS/FINANCE_DIRECTOR 还是仅财务三角色） | 03/04/06/08 | 待定 |

### 6.6 出纳资金 / 票据
| # | gap | 出处 | 默认建议 |
|---|---|---|---|
| G-CASH-1 | 银行利息收入口径（冲减 6603 财务费用 vs 计 6051 其他业务收入） | 05 | 待定 |
| G-CASH-2 | 票据贴现息公式（天数基准 360 vs 365；贴现息是否含增值税）；商票是否计提坏账 | 05/03 | 待定 |
| G-CASH-3 | 现金收付对方科目随来源单类型变（杂收入/费用报销具体科目）须完整 AccountMappingRule 清单 | 05 | 待定 |
| G-CASH-4 | 现金库存上限预警（WARN vs 硬拦；各公司是否不同） | 05 | 默认 WARN |
| G-CASH-5 | 资金调拨大额会签阈值（是否需 FINANCE_DIRECTOR/BOSS、金额线） | 05 | 待定 |
| G-CASH-6 | 外币银行户逐笔即时汇率取数源 vs 月末统一调汇（660301）的衔接 | 05 | 决策8 已定月末调汇货币性 |
| G-CASH-7 | NotesReceivable 是否同意加 voucher_id/discount_* 列；NotesPayable 是否纳入本期 | 05 | 建议加列 |
| G-CASH-8 | 银行对账单导入方式（Excel 模板字段；银企直连排后） | 05 | 本期 Excel 导入 |
| G-CASH-9 | BankReceipt（已有银行收款流水）与新建 BankJournal 关系（作来源 vs 合并，防双重记账） | 05 | 推荐作来源 |

### 6.7 固资 / 折旧
| # | gap | 出处 | 默认建议 |
|---|---|---|---|
| G-FA-1 | 折旧费用科目归集（自用 6602 默认；销售/研发用类别级 vs 卡片级覆盖） | 07 | 待财务给规则 |
| G-FA-2 | 外币固资不调汇（非货币性期末不调汇，累计折旧锁入账汇率） | 07 | 已按决策8 处理，待确认无异议 |
| G-FA-3 | 折旧批触发（引擎无 cron，手动+到期 Notification+外部 Cron 调 fa.run_depreciation）；月末跑批责任人与提醒时点 | 07 | 默认 ACCOUNTANT 月末手动 |
| G-FA-4 | 减值不可转回（CAS8）已锁死，请确认 | 07 | 已确认 |

### 6.8 薪酬 / 费用报销
| # | gap | 出处 | 默认建议 |
|---|---|---|---|
| G-HR-1 | 单位社保公积金贷方科目（2211 子目 vs 2241/2221）；个人社保代扣科目（2241 vs 2211 子目） | 08 | 默认 2211 子目/2241 |
| G-HR-2 | 费用类别→费用科目映射表 + 各类别默认税率 + 是否进项可抵扣，逐条填 AccountMappingRule | 08 | 待定 |
| G-HR-3 | 报销审批阈值与会签规则（>X 需 BOSS 会签；阈值；是否按部门分流） | 08 | 待定 |
| G-HR-4 | 部门主数据（dept 用受控 String 字典 vs 独立 DepartmentMaster 层级辅助核算） | 08 | 本期 String 字典 |
| G-HR-5 | HR 角色（员工/薪资制单独立 HR 角色 vs 并入 ACCOUNTANT/FINANCE_MANAGER） | 08 | 本期并入财务 |
| G-HR-6 | 薪资明细可见性（CASHIER 发放需见实发，是否见个税/社保明细的隐私边界） | 08 | 待定 |
| G-HR-7 | 员工借款/备用金核销（ADVANCE_OFFSET）是否本期上线（涉 1221） | 08 | 本期占位 |
| G-HR-8 | 是否计提职工福利费/工会经费/教育经费（CAS 附加计提） | 08 | 本 PRD 未含，待定 |

### 6.9 期末结账 / 报表 / 账套（结构/口径）
| # | gap | 出处 | 默认建议 |
|---|---|---|---|
| G-CLOSE-1 | 结转损益目标=4103 本年利润（非 4104）；seed 旧 RULE 文本写 4104 需修正；4103→4104 仅年末结转 | 10 | 已定 4103，seed 须修正 |
| G-CLOSE-2 | 期末调汇科目范围（货币性界定）——是否在 Account 加 is_fx_revalued 列 vs 调汇科目常量清单，逐科目确认 | 10/05 | 待定 |
| G-CLOSE-3 | 调汇账面汇率口径（期初/上次调汇后/按笔加权） | 10 | 建议科目级期末账面 vs 重估 |
| G-CLOSE-4 | 结转损益范围（是否含营业外 6301/6711、税金附加 6403、减值 6701、所得税；全部纳入 vs 分步） | 10 | 待定 |
| G-CLOSE-5 | 结账前校验清单硬软划分（无未过账/试算平衡/调汇/损益结转/前序期已结=硬；成本核硬度依存货模块；银行对/往来核=软+留痕） | 10 | 待定硬软清单 |
| G-CLOSE-6 | 反结账权限与会签（FINANCE_MANAGER+FINANCE_DIRECTOR+BOSS 会签是否强制；限反结次数/时间窗） | 10/02/13 | 待定 |
| G-CLOSE-7 | 年度切换（FiscalYear 结账是否自动开下年度+12期；4103→4104 年末结转时点） | 10 | 待定 |
| G-CLOSE-8 | 期初导入是否生成"期初余额建账凭证" vs 仅写 opening 列（建账期专属例外） | 10 | 默认仅写 opening 列 |
| G-CLOSE-9 | 金蝶并行对账验平口径（并行期长度/对账维度/容差阈值/下线触发条件/谁判定） | 10/13 | 待定（见切换路线） |
| G-RPT-1 | 现金流量表投资/筹资活动（接受 MVP 经营全自动+投资筹资占位手工微调 vs VoucherEntry 加 cashflow_item 辅助核算标记） | 11 | 建议 MVP |
| G-RPT-2 | ★辅助核算维度（VoucherEntry 加 department_id/project_id/customer_id 列 vs 经 source_doc 间接还原）——影响多栏账/核算项目账/往来报表，**建议 Layer0 统一加列后封板** | 02/11/12 | 建议加列（跨模块共识） |
| G-RPT-3 | 报表口径实时 vs 快照（期末结账后是否冻结 ReportSnapshot 存档） | 11 | 待定 |
| G-RPT-4 | 调整期(13期)凭证是否计入年报三大表 | 11 | 默认计入 |
| G-RPT-5 | 资产负债表年初数口径（本年首期 opening vs 上年末期 closing） | 11 | 待定 |
| G-RPT-6 | 未分配利润构成 BS_RETAINED（4104+4103 是否含 6901） | 11 | 待定 |
| G-RPT-7 | HKFRS 报表模板项目清单（CAS↔HKFRS 分类/列报差异） | 11/13 | 待财务提供 |
| G-RPT-8 | SY 期末方向净额取数口径（与金蝶 JY/DY 拆分一致性）；应收贷余/应付借余异常方向重分类规则 | 11 | 待定 |
| G-ORG-1 | ★HK 公司本位币=HKD 还是 USD（seed 现 HK currency=HKD；决策8 海外默认 USD；home_currency 与展示币 currency 分离） | 13/01/05 | 逐家签字 |
| G-ORG-2 | 凭证号格式（建议 `{prefix}-记-{YYMM}-{seq3}`；是否分记/收/付/转字号各自连号） | 02/13 | 待定 |
| G-ORG-3 | 6 公司逐家准则×税制（占位 HK3=HKFRS/NONE、内地3=CAS/VAT）是否有例外 | 13 | 逐家确认 |
| G-ORG-4 | BOSS/FINANCE_DIRECTOR 跨公司写边界（须先切 active vs 允许不切直接跨司过账，不建议） | 13 | 须先切 active |
| G-ORG-5 | 职责分离默认值（默认 ON；哪几家小公司放宽；放宽到制单=审核可放 vs 全放） | 02/12/13/各模块 | 默认 ON，逐家初值 |
| G-ORG-6 | 临时代管角色继承（用代管人自身 role vs 承接目标账套角色） | 13 | 用代管人自身 role |
| G-ORG-7 | 公司全称/抬头/金蝶组织码（seed 全占位，6 家逐字签字） | 13 | 逐家签字 |
| G-ORG-8 | 附单据张数是否强制录入并作过账前置校验；红冲是否需二次审批（完整审核过账 vs 主管一步生成即过账） | 02 | 待定 |

---

## 七、待修订（本次一致性交叉校验发现的不一致——不改已有文件，列此供修订）

> 见下方「八、实施分期」与结构化返回的 inconsistencies。核心 6 项：①基石种子科目集补 1603/1606/6801/222103/1221/未交增值税明细（否则 07/08/09 映射无目标科目）；②05-出纳"购结汇/手续费"用 660303，其余全用 660301，须统一汇兑损益/手续费科目码；③labels.py `WEIGHTED_AVG="全月加权平均"` 与本项目锁定的移动加权语义冲突（用 MOVING_AVG）；④seed 结转损益 RULE 文本写 4104，应为 4103；⑤辅助核算列（VoucherEntry +dept/project/customer）多模块各自标"建议加"，须基石统一拍板后封板，否则多栏账/核算项目账/往来报表口径不一；⑥`map_to_voucher_entries`/`finance.post_voucher` 等基石件被 02/03/04/05/06/07/08/09/12 共九处声明"❌新建"，须明确"由 01 基石唯一新建、各模块仅引用"，避免重复造。

---

## 八、实施分期建议（P1-P9）

> 原则：先 L0 封板（含 6 项待修订归并），再 L1 按"业务量大+利润表大头"优先，最后 L2 报表收口。每期末有可验收交付物。

| 期 | 名称 | 内容 | 依赖 | 交付物 |
|---|---|---|---|---|
| **P1** | ★L0 基石封板 | 科目双模板(补 G-COA-1~6)+期间锁+币种汇率+**凭证内核过账层**(post_voucher/unpost_voucher/red_reversal+反过账反审核边)+**AccountMappingRule 框架+map_to_voucher_entries**+3 角色+SoD validator+**辅助核算列定夺(G-RPT-2)** | — | 手工凭证可录-审-过账写 AccountBalance；试算平衡；蓝冲/红冲跑通；digest 下发 |
| **P2** | 总账 + 业财发动机骨架 | 02 总账凭证录入屏(密集网格键盘流)+12 发动机机制(业务 effect 串接 map+post)+业务红冲广播 | P1 | 凭证录入页可用；自动凭证机制就位 |
| **P3** | 应收 AR + 应付 AP | 03 收款过账/坏账/账龄/票据+04 暂估应付/发票冲回转实/付款/AP账龄/信用占用 | P1/P2 | 往来全闭环过账；账龄报表；暂估转实 |
| **P4** | 出纳资金 | 05 日记账(现金/银行)+银行对账+资金调拨+票据生命周期 | P1/P3 | 出纳台账与 1001/1002 勾稽；对账平衡表 |
| **P5** | 存货成本 | 06 移动加权过账桥+暂估/差异/红冲三套政策+收发存明细账+★平销返利(G-COST-3) | P1/P3 | 发货当下看利润；存货账与 1405 勾稽 |
| **P6** | 收入确认 + 税务 | 09 CAS14 五步法收入确认(合同资产/负债)+行级税率+增值税计提+所得税/HK利得税 | P1/P2/P5 | 开票收入解耦；增值税申报数据 |
| **P7** | 固资 + 薪酬费用 | 07 固资卡片+月折旧批+减值处置；08 工资计提发放+费用报销 | P1/P2 | 折旧凭证自动；人力成本+期间费用入利润表 |
| **P8** | ★L2 期末收口 | 10 调汇+结转损益(目标 4103,修正 G-CLOSE-1)+结账向导+反结账+期初建账 | P1-P7 全过账 | 可结账；期初导入；当期账干净结转下期 |
| **P9** | ★L2 报表 + 切换 | 11 三大表+四账簿+现金流量(间接法 MVP)+ReportLineDef 映射；13 跨公司汇总看板；金蝶并行对账验平→下线 | P8 | 法定三大报表+四账簿；金蝶下线 |

> 13 多组织账套与权限：贯穿 P1（账套配置+角色+SoD+科目模板）始终，不单列一期。

---

## 九、与"完全替代金蝶"切换路线（期初导入 + 并行对账验平 → 金蝶下线）

```
①账套配置就位(13: 准则/本位币/期间/科目模板/序列/角色)  COMPANY_BOOK: DRAFT→CONFIGURED→COA_LOADED→PERIODS_READY
        ▼
②期初建账一刀切(10: finance.import_opening_balance)        启用日对齐期间起点，写 AccountBalance.opening + 未结 AR/AP + 存货成本，Σ借=Σ贷
        ▼
③系统启用 GO_LIVE(13)，业务+财务双轨：本系统正式记账，金蝶并行(kingdee_outbox 仍推送对账)
        ▼
④并行对账验平期(G-CLOSE-9/G-ORG-3)：连续 N 个会计期，逐期比对
   维度：科目余额表逐科目 → 试算平衡 → 三大报表 → 抽样凭证级
   阈值：差额 ≤ 容差（建议 0.01 / 逐科目零差异，待财务定）
        ▼
⑤验平判定(BOSS/FINANCE_DIRECTOR 会签)：达标 → 标金蝶下线
        ▼
⑥金蝶下线 KINGDEE_RETIRED(13: book.retire_kingdee + kingdee.disable_push)
   置 Company.kingdee_retired=true → 停 kingdee_outbox.enqueue_push；本系统成为唯一财务真相源
```

**关键守门**：
- 期初冻结：启用确认后期初余额不可改，错账走调整期凭证（建账期专属例外，G-CLOSE-8）。
- 逐家独立切换：6 公司各自 COMPANY_BOOK 状态机推进，可不同步下线（绝不合账）。
- 待签：并行期长度 N、对账维度、验平阈值、下线触发与判定人（G-CLOSE-9）；HK 本位币（G-ORG-1）；6 家准则×税制例外（G-ORG-3）；公司抬头/组织码（G-ORG-7）。

---

> 本 README 仅做总览索引与一致性收口，**不改任何已有 .md 内容**。发现的不一致见 §七待修订与结构化返回 inconsistencies；任何与 01-基石.md 冲突的下游定义=停下讨论，禁止静默偏离。
