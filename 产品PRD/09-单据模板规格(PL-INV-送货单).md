# 09 · 单据模板规格（PL 装箱单 / INV 商业发票 / 送货单）

> 本文是 PHOTONTECK（富泰）CRM+WMS **商业交付级业务 PRD** 的**单据模板实化册**，对应 IA 导航树「8 配置 / 模板 · 单据模板（PL / INV / 送货单，按客户 + 公司）」（见 `00-导航与参与者总览.md` §2）。它**实化** `09-配置与模板.md §9.2`「单据模板」从抽象的可配模板引擎（`doc_template` + `doc_template_field_line` + custom_html 渲染逃生舱）到**字段级真表**：把出库实际寄出的 **PL（Packing List 装箱单）/ INV（Commercial Invoice 商业发票）/ 送货单（客户送货单 / 货物托运单 / 快递面单）** 三类单据，按**客户 + 公司**整理成可配置的字段清单、客户差异矩阵、盖章/回签流转、特殊渲染要求（旭创/智禾 **数量列 + 外箱发货日期 渲染为条码**）。
>
> 本文与三处协同、不重复定义：①模板引擎机制（doc_type / 子表 / custom_html / XSS 约束）在 `09-配置与模板.md §9.2`，本文只**实化字段与差异**；②出库作业流程（拣货 / 分箱 / 贴标 / 拍照 / 互检★ / 财务放行★ / 盖章扫描 / 出庫登記）在 `03-仓储WMS-出库与盘点.md`，本文只**引用其触发点**；③标签模板（包装/外箱/公司外箱标签的字段映射与二维码拼接）在 `09-配置与模板.md §9.1`，本文仅在「数量列条码」处与标签册交叉引用（同一条码要求同时落标签与本文的渲染开关）。
>
> 一手源（权威，带出处）：补充材料 `potonteck补充材料/出库/往来邮件1·2/`——
> - PL 样本：`PL模板/PL-2606-005 Eoptolink成都 做PL用.xls`（多型号多批次大单，267 行，CARTON/SN-LOT 列）、`PL模板/PL-2606-080 HisenseQ（HL13B5CP12-L0）.xls`（汇总型 PL + 「批次信息」子 sheet）、`PL模板/260601-PL-2606-048 Innolight--TL.xls`（含 Part No./Rev./保理银行抬头块）；
> - INV 样本：`INV模板/I-2606-080 HisenseQ.xls`、`invoice模板/I-2606-048 Innolight--TL.xls`（UNIT PRICE/SUBTOTAL/Total AMT；保理银行块）；
> - 送货单样本：`送货单/3048912834.pdf`（DHL EXPRESS WORLDWIDE 快递面单 / WAYBILL）、`SA提供送货单/货物托运单-6.1铜陵.xls`（仓库货代托运单 SHIPPER'S INSTRUCTIONS）；
> - 盖章/回签样本：`PL+INV盖章版/I-2606-005 Eoptolink成都 INV&PL.pdf`（4 页扫描）、`盖章版PL+INV/260601-I-2606-048 Innolight--TL_CIPL.pdf`（扫描图，无文本层）；
> - 邮件流转与特殊要求：`RE I-2606-005 成都新易盛 发货.eml`（盖章回传 / 随货资料 / CARTON SIZE / 送货单字段清单 / DHL 账号更新）、`I-2606-048 Innolight--TL.eml` 与 `回复 RE …`（盖章版需 5 点前送到、先 PL 后 INV、客户给入仓号再约车、9 条标签/单据特殊要求）、`旭创&智禾标签，新增要求：标签上 数量（Quantity）这一栏增加条形码.eml`（数量列加条码，附实拍样张 `Catch71B1.jpg`）。
>
> 引擎源：`技术文档/01 元数据与注册引擎`（`__doc_types__`/`__queryable__`、`_line` 子表→SubTableEditor、字段防火墙、FK 标签解析）、`/02 流程与状态机引擎`（WorkflowDefinition.states、execute_transition、预览→ChangeCard→commit）、`/08 前端引擎外壳`（DocEditor / SubTableEditor / DataExplorer / **custom_html 逃生舱**）、`/05 权限会话多租户`（公司隔离 `_company_filter`、`is_admin` 超管闸）。以代码为准。
>
> 状态：待甲方评审。日期：2026-06-16。

---

## 模块定位

出库环节，富泰每发一票货都要随货 + 回传一组**对外单据**：给客户/海关用的 **PL（装箱单）+ INV（商业发票）**，以及**客户送货单 / 仓库货代托运单 / 快递面单**。现状（访谈 05 + 样本邮件）是仓库/SA 同事**打开上一单的 Excel 模板，手改成本单数据**，再打印盖章扫描成 PDF 回传——千客千面、易错、不可审计：

- **PL/INV 骨架按客户 + 公司不同**：抬头（Photonteck Company Limited 香港抬头 vs 内地公司抬头）、Bill-To/Ship-To、银行块（Eoptolink 用平安银行 OSA 账户、Innolight 用汇丰 GTRF **保理 assigned 账户块**）、列集（Hisense 多一列 `Material PN`/`Country of Diffusion`、Innolight 多 `Part No.`/`Rev.`/`NO.`、Eoptolink 用 `Production date`）、价格条款（FOB HK / FCA HK）、付款条款（NET 30 / AMS 30 / Factoring 30）各不相同。
- **同一单 INV 与 PL 配对**：INV 号 `I-2606-080` ↔ PL 号 `PL-2606-080`（**同尾号**，总览 §7），同一批货物明细但 PL 出**净重/毛重/SN-LOT/生产日期**、INV 出**单价/金额**（成本/单价对销售隐藏，见字段防火墙）。
- **盖章 + 回签是硬流转**：客户要「盖章版 INV+PL」随货且回传扫描件（`RE I-2606-005`「INV 和 PL 请帮盖章回传」、`I-2606-048`「提供盖章版 INV+PL 需五点前送到，请先提供 PL，客户收到 INV&PL 后提供入仓号再安排送货」）。
- **送货单分三类、来源不同**：①**客户送货单**（SA 在系统制作、出库时提取打印随货，旭创要求「SRM 送货单打印随货后必须有签字或公章」）；②**仓库货代托运单**（HONGBODA 等香港仓 `SHIPPER'S INSTRUCTIONS 货物托运单`，含进仓编号 `Q260601-102`、收发货人、箱数毛重、约车信息）；③**快递面单**（DHL/FedEx 等承运商系统出 WAYBILL，外部系统产物，系统只登记单号 + 附件）。
- **新特殊要求（2026-06-16 在办）**：旭创 & 智禾要求**标签上「数量（Quantity）」列增加条形码**，且 Innolight 邮件追加**「外箱发货日期需增加条形码」**「数量列加条码」「生产批次/生产日期要体现对应条码」。这一要求**同时落标签模板（`§9.1`）与本文 PL 渲染开关**（PL 数量列、外箱发货日期渲条码）。

> 设计基调：与 `§9.2` 一致——**单据 = 「模板（元数据） + 数据（出库单/发票/SO 拉取）」**。新增一个客户的 PL/INV 规格、切一列、加一个条码开关，都在配置中心点选完成，**零代码、零发版**。本文是这套引擎的「首批客户实化数据 + 字段字典」，每个「按客户差异」的具体取值都标**待甲方逐一确认**（蓝图 §6、总览 gap 2）。

### 边界（本模块不做）

- **不做出库作业流程**：拣货/分箱/贴标/拍照/互检★/财务放行★/出庫登記在 `03-仓储WMS-出库与盘点.md`。本文只规定「在出库单的哪个态、按哪个模板、灌哪些字段、渲染成什么单据」。
- **不做标签字段映射与二维码拼接全集**：包装/外箱/公司外箱标签在 `§9.1`。本文只承接其中与本文交叉的**条码渲染开关**（数量列条码、外箱发货日期条码）。
- **不实际打印/不出快递面单**：物理打印走仓库本地打印机（占位）；DHL/FedEx WAYBILL 由承运商系统生成（`3048912834.pdf` 即 DHL 产物），本系统**只登记运单号 + 挂面单 PDF 附件**，不渲染面单本体。顺丰 API 货物进度查询为占位（决策⑪、`06-报关.md`）。
- **不做财务做账**：INV 金额推金蝶作应收源（决策③），凭证/成本在金蝶；本文只管单据本体的字段与推送触发点。

---

## 参与者视角（角色 → 做什么 / 触发时机 / 数据范围 / 限制）

> 角色命名遵循总览 §3.1。本文区分**配置侧**（定义模板）与**使用侧**（出库时灌数据→渲染→盖章回传）。**采购成本/单价对销售（SALES）隐藏**：INV 的 `UNIT PRICE/SUBTOTAL/Total AMT` 是**卖价**（对客户开的发票，PM/财务/SA 可见，对纯 SALES 角色的可见性按总览 §8 待甲方细化）；但**采购进价/原厂报价/PO 单价/批次成本绝不出现在 PL/INV**（PL/INV 是对客户的对外单据，天然只含卖价与物流信息）。

| 角色 | JTBD（做什么） | 触发时机 | 数据范围 | 限制 |
|---|---|---|---|---|
| **系统管理员 ADMIN** | 维护 PL/INV/送货单模板本体：抬头/银行块/列集/区域差异/盖章标志/条码开关；新增客户规格 | 上线初始化、新增客户/公司、规格变更 | 全局（配置带 company_id 区分 6 租户 + 区域 HK/内地） | 写元数据须经 `is_admin` 闸；改已发布模板须审计（引擎 05 §5.4） |
| **物流主任 LOGISTICS_LEAD** | 维护 PL/INV/送货单模板（最懂客户单据字段来源 + 银行块 + 外箱尺寸约定）；确认客户列集差异 | 客户新增单据需求 / 字段来源澄清 | 本仓 / 本公司模板 | 仅模板配置；不碰编号规则/审批流/权限 |
| **SA 销售助理** | **制作客户送货单**（系统提取打印随货，旭创要求盖章/签字）；提供 INV# / 合同号 / 客户订单号给 PL/INV 灌数据；制作销项发票（INV 数据源，`05b` 页面 5） | 出库前、客户发货邮件后 | 本部门订单 | 不碰 PL/INV 抬头银行块（模板侧）；改单留痕 |
| **物流专员 LOGISTICS** | 出库时**选客户+公司模板**→灌数据→渲染 PL/INV→打印→**盖章**→扫描成 PDF→邮件回传；写实际分箱数/毛重净重/外箱尺寸；提取打印客户送货单；登记快递/托运单号 + 挂面单附件 | 出库 `picking`→`review` 段（`03b`） | 本仓 | 只用不改模板本体；条码渲染按模板开关自动出 |
| **FINANCE 财务** | INV 内容审核（vs 发货内容一致，货不能出仓★，`05b` 页面 4 / `03b`）；INV 推金蝶作应收 | 财务放行关卡 / INV 确认 | 本公司账套 | 不改单据模板；审内容一致性 |
| **管理层 / 财务总监** | 只读（跨公司单据样张/合规抽查，决策 A） | 抽查 | 只读（汇总） | 不写 |

> JTBD 出处：盖章回传 = `RE I-2606-005`「INV 和 PL 请帮盖章回传」；先 PL 后 INV、客户给入仓号再约车 = `I-2606-048`；SA 制作客户送货单系统提取打印 = `I-2606-048`「客户送货单随货，送货单晚点 SA 制作好后，请在系统上提取并打印」；旭创送货单须签字/公章 = 同邮件第 8 条；实际分箱/毛净重/外箱尺寸由仓库写 = 访谈 05 L444-481 + `RE I-2606-005` CARTON SIZE。

---

## 页面/单据清单（本模块新增屏，均挂 IA「8 配置 · 单据模板」+ 出库渲染入口）

> 配置屏在「8 配置 / 模板」域；渲染/导出在出库单（`03b`）的「单据」动作里调用。本文按三类单据各一节实化字段，最后给「客户差异矩阵」「盖章回签流转」「条码渲染」「编号配对」四张横切表。

| # | 屏 / 单据 | 类型 | 引擎落点 | 兼容性 |
|---|---|---|---|---|
| 1 | **PL 装箱单模板**（抬头/列集/银行块/批次子 sheet/外箱尺寸/条码开关） | 单据模板实化 | `doc_template`(doc_kind=PL) + `doc_template_field_line` + `pl_line` 渲染数据 | ➕extension（custom_html 渲染，`§9.2`） |
| 2 | **INV 商业发票模板**（抬头/列集/单价金额/银行块/付款条款） | 单据模板实化 | `doc_template`(doc_kind=INV) + 子表 | ➕extension |
| 3 | **送货单 · 客户送货单**（SA 制作、系统提取打印、签章随货） | 单据模板实化 | `doc_template`(doc_kind=DN_CUST) + 子表 | ➕extension |
| 4 | **送货单 · 仓库货代托运单**（HONGBODA 类香港仓 SHIPPER'S INSTRUCTIONS） | 单据模板实化 | `doc_template`(doc_kind=DN_FWD) + 子表 | ➕extension |
| 5 | **送货单 · 快递面单登记**（DHL/FedEx WAYBILL 外部产物，仅登记号 + 附件） | 登记字段（非渲染） | 出库单字段 `waybill_no` + 附件；不渲染面单 | ✅compatible（字段 + 附件） |
| 6 | **盖章/回签流转**（打印→盖章→扫描 PDF→回传，挂回签件） | 状态 + 附件 | 出库单 `doc_pack` 子态 + `stamped_pdf` 附件 | ➕extension（流转标志 + 附件回挂） |
| 7 | **条码渲染开关**（数量列条码 + 外箱发货日期条码，旭创/智禾） | 模板字段开关 | `doc_template_field_line.render_as_barcode` + 后端条码生成 | ➕extension（与 `§9.1` 同条码库） |

---

## 单据 1 · PL 装箱单（Packing List）

**定位**：随货 + 报关用的明细装箱单，**按客户 + 公司**渲染。三种形态（从样本归纳，由模板的 `pl_layout` 决定）：
- **明细型**（Eoptolink `PL-2606-005`）：每行 = 一个 SN/LOT 批次，CARTON 跨行合并（一箱含多批），列含 `SN/LOT#`、`Production date`、`CONTRACT NO.`、净重/毛重；尾行 Total 数量 + Total WEIGHT + 银行块（平安银行 OSA）。
- **汇总型 + 批次子 sheet**（Hisense `PL-2606-080`）：主 sheet 按外箱汇总（CARTON NO / QUANTITY / LOT NO=「详见附件」/ `Material PN` / `Country of Diffusion` / `CONTRACT NO.` / 净重/毛重），另起「批次信息」sheet 列「型號 / SN/LOT# / 數量」全量批次（83 行）。
- **保理银行块型**（Innolight `PL-2606-048`）：列含 `Part No.`、`Rev.`、`NO.`，尾部带**汇丰 GTRF 保理 assigned 账户块**（"This account has been assigned to … HSBC … As trustee for HSBC"）。

> 三型同一引擎、同一字段字典，差异 = 模板配置（列开关 + 银行块文本 + 是否出批次子 sheet）。数据源 = 出库单拣货批次子表（`03b` `outbound_order_line`：入仓编号/型号/SN-LOT/数量/供应商/性质）+ 主数据（HS/产地/Material PN/合同号）+ 仓库手填（实际分箱数/外箱尺寸/毛净重）。

### 字段表 · PL 表头（`pl_doc` 主单，渲染数据，按模板 + 出库单灌入）

| 字段 | 类型 | 必填 | 选择器来源 | 校验 | 默认 | 扫码兜底 | 引擎映射 |
|---|---|---|---|---|---|---|---|
| PL No.（PL 号） | str | 是 | 编号规则生成 `PL-{YYMM}-{seq}` | 与 INV 同尾号 | 出库单带出 | — | `*_number` 唯一前缀（引擎 02）+ 编号规则扩展（总览 §7） |
| Shipping date（发货日期） | date | 是 | 出库单出库日期 | — | 出库日期 | — | date；**Excel 样本存为序列号 46171=2026-05-29，渲染须格式化为日期**（UX 公约 §5） |
| 公司抬头 / 地址 / Tel/Fax | text | 是 | 公司主数据（实体代号 → 抬头）| 须本公司 | active_company 抬头 | — | 由 `company_id` 解析（6 实体：Photonteck/andesec/FTK/RJ/XGTC/TR，各自抬头，**待甲方提供 6 套抬头** gap） |
| 单据标题（Packing List） | str | 是 | 固定 | — | "Packing List" | — | 模板常量 |
| Bill-To（开单对象 名称/地址/Tel）| text | 是 | 客户主数据 | — | 客户带出 | — | FK 客户→抬头；可与 Ship-To 不同（Hisense：Bill-To=Hisense HK，Ship-To=CYTS 物流） |
| Ship-To（收货对象 名称/地址/Tel）| text | 是 | 客户/收货方主数据 | — | 客户带出 | — | 可填第三方收货仓（DHL 账号随附，如 Eoptolink「DHL account number is 950308513」） |
| CONTACT（联系人）| str | 否 | 客户联系人 | — | — | — | 单据页脚联系人（Long Jin / Mr. Key / Wang Chengcheng） |
| SHIP VIA（运输方式）| str | 否 | 出库送货形式 | — | LOCAL DELIVERY | — | DHL Account#/Local Delivey/Local delivery(HONGBODA) |
| PRICE TERM（价格条款）| enum | 是 | 模板/客户 | — | FOB HK | — | FOB HK / FCA HK（Innolight=FCA HK）|
| PAYMENT TERM（付款条款）| str | 是 | 模板/客户 | — | NET 30 DAYS | — | NET 30 / AMS 30 DAYS / Factoring 30 days |
| Packing（包装说明）| text | 否 | 模板/客户 | — | — | — | Innolight 有 "Manufacture's original standard packing and airworthy packing…" |
| 外箱尺寸（CARTON SIZE）| text | 是（仓库填）| 仓库手填 | 不同型号不混装一箱（`I-2606-048` 第 3 条）| — | — | 例 "2@66*51*29 CM"、"5ctn@61*41*37cm"、"3@61*41*37cm + 5@66*51*39cm"（`RE I-2606-005`）|
| Total QUANTITY（总数量）| number | 自动 | 子表汇总 | =Σ行数量 | 子表合计 | — | SubTableEditor `quantity` 汇总（Eoptolink 215674、Hisense 51968、Innolight 60000）|
| Total NET / GROSS WEIGHT（总净/毛重）| number | 是（仓库填）| 仓库手填/批次累加 | — | — | — | "Total WEIGHT 37.3 / 52.97"（Eoptolink）、"12.45 / 18.06"（Hisense）|
| 银行块（Bank block）| text | 否 | 模板（按客户/公司）| — | 公司默认银行块 | — | **平安银行 OSA**（Eoptolink/Photonteck 默认）vs **汇丰 GTRF 保理 assigned 块**（Innolight）——见「银行块差异」；**待甲方确认各客户用哪套** gap |
| Original/Copy 标记 | enum | 否 | 模板 | — | Original | — | 样本右下角 "Original" |

### 字段表 · PL 明细子表（`pl_line`，名含 `_line`→SubTableEditor 网格）

> 列集**按客户开关**（不是所有客户都有所有列）。下表为**字段全集字典**，每客户启用子集（见「客户差异矩阵」）。数据源主要来自出库单拣货批次子表 + 主数据。

| 字段 | 类型 | 必填 | 选择器来源 | 校验 | 默认 | 扫码兜底 | 引擎映射 |
|---|---|---|---|---|---|---|---|
| CARTON (NO)（箱号/箱序）| str | 是 | 仓库分箱 | — | 行号/分箱 | — | 明细型按批次行（CARTON 跨行合并）；汇总型一箱一行 |
| QUANTITY（数量）| number | 是 | 出库批次行 | >0 | 批次数量 | 手填兜底 | `quantity`；**旭创/智禾：渲条码**（见「条码渲染」）|
| UNIT（单位）| str | 是 | 产品 UOM | — | PCS/pcs | — | 主数据 UOM |
| DESCRIPTION OF GOODS（型号/品名）| str | 是 | 产品主数据 | 须与 INV 型号一致（`I-2606-048` 第 2 条）| 型号 | 扫码兜底 | 显示名解析（引擎 01 §1.4.2）|
| SN/LOT#（批次/序列号）| str | 是（明细型）| 出库批次行 | — | 批次带出 | 扫码兜底 | 明细型每行一个；汇总型填「详见附件」+ 批次子 sheet |
| Production date / D/C（生产日期）| date | 否 | 入库批次属性 | — | 批次带出 | 扫码兜底 | Eoptolink 用 8 位 `20260421`；**生产批次/日期要体现对应条码**（`I-2606-048` 第 1 条，落标签）|
| Material PN（客户物料号）| str | 否 | 产品代码（按客户/供应商）| — | — | — | **Hisense 专列**（4401039101）；对应产品代码主数据（一型号多 code，`02 主数据`）|
| Part No.（客户件号）| str | 否 | 产品代码 | — | — | — | **Innolight 专列**（283-0391-31）|
| Rev.（版本）| str | 否 | 产品代码/客户 | — | — | — | **Innolight 专列**（1A）；旭创要求物料号处加客户版本「见 INV」（`I-2606-048` 第 1 条）|
| Manufacturer / Country of origin（原厂/产地）| str | 是 | 供应商主数据 | — | 供应商带出 | — | "Lumentum(朗美通), Japan"、"Anritsu（安立）,Japan" |
| Country of Diffusion（扩散国）| str | 否 | 产品/主数据 | — | — | — | **Hisense 专列**（Japan）|
| CONTRACT NO.（合同号）| str | 是 | 销售订单/客户合同 | 来自销售（访谈 05 L619-628）| SO 带出 | — | 客户合同号（Z2026… / 4570116103 / 7200001864）|
| NO.（客户行号/数量约束）| str | 否 | 客户 | — | — | — | **Innolight 专列**（10）|
| NET WEIGHT (KG)（净重）| number | 否 | 仓库手填/批次 | — | — | — | 行级或合并 |
| GROSS WEIGHT (KG)（毛重）| number | 否 | 仓库手填 | — | — | — | 行级或合并 |
| ROHS/合规标记 | bool | 否 | 模板/客户 | — | — | — | `RE I-2606-005`「包装上请帮贴 ROHS 标识」（落标签/包装，PL 可备注）|

### PL 批次子 sheet（汇总型专用，`pl_batch_line`）

| 字段 | 类型 | 必填 | 来源 | 引擎映射 |
|---|---|---|---|---|
| 型號 | str | 是 | 出库批次行 | 与主表型号一致 |
| SN/LOT# | str | 是 | 出库批次行 | 全量批次明细 |
| 數量 | number | 是 | 出库批次行 | Σ=主表 Total（Hisense 批次 sheet 83 行汇总=51968）|

> **明细型 vs 汇总型选择**：当 PL 主表 LOT 列填「详见附件」时启用批次子 sheet（Hisense 模式）；否则每行带 SN/LOT（Eoptolink 模式）。由模板 `pl_layout=detail|summary` 决定，**渲染时同源数据两种排版**（决策⑦明细为真相，汇总=同源视图）。

---

## 单据 2 · INV 商业发票（Commercial Invoice）

**定位**：与 PL **配对**（同尾号）的对客户商业发票，**出单价 + 金额**（PL 不出价、INV 不出 SN/LOT 净毛重——两单职责互补）。数据源 = 销项发票（`05b` 页面 5，SA 制作）+ 出库单。

### 字段表 · INV 表头（`inv_doc`，与 PL 表头同结构，差异列见下）

> 表头字段（公司抬头/Bill-To/Ship-To/CONTACT/SHIP VIA/PRICE TERM/PAYMENT TERM/Packing/银行块/Original）**与 PL 完全同源**（同一出库单/客户），仅以下不同：

| 字段 | 类型 | 必填 | 选择器来源 | 校验 | 默认 | 引擎映射 |
|---|---|---|---|---|---|---|
| Invoice No.（发票号）| str | 是 | 销项发票 `I-{YYMM}-{seq}` | **与 PL 同尾号**（总览 §7）| 销项发票带出 | 编号规则扩展；报关时可切换为报关单号（`e` 开头，访谈 05 L489）|
| Invoice date（发票日期）| date | 是 | 销项发票 | — | 开票日 | date（Excel 序列号→格式化）|
| 单据标题（Commercial Invoice）| str | 是 | 固定 | — | "Commercial Invoice" | 模板常量 |

### 字段表 · INV 明细子表（`inv_line`，名含 `_line`→SubTableEditor 网格）

| 字段 | 类型 | 必填 | 选择器来源 | 校验 | 默认 | 扫码兜底 | 引擎映射 |
|---|---|---|---|---|---|---|---|
| ITEM（行号）| number | 是 | 自动 | — | line_number | — | SubTableEditor 自动行号 |
| QUANTITY（数量）| number | 是 | 出库/发票 | =PL 总数 | 汇总 | — | INV 按型号汇总（不按批次拆，Hisense 一行 51968 / Innolight 一行 60000）|
| UNIT（单位）| str | 是 | 产品 UOM | — | pcs | — | 主数据 UOM |
| DESCRIPTION OF GOODS（型号）| str | 是 | 产品 | 须与 PL 一致 | 型号 | 扫码兜底 | 显示名解析 |
| Material PN / Part No. / Rev. / LOT NO. / Country of Diffusion / CONTRACT NO. / NO. | mixed | 否 | 同 PL 子表 | — | — | — | **按客户开关同 PL**（Hisense 出 Material PN+Country of Diffusion+LOT「详见附件」；Innolight 出 Part No.+Rev.+NO.）|
| Manufacturer / Country of origin | str | 是 | 供应商 | — | 供应商带出 | — | 同 PL |
| **UNIT PRICE（单价）** | number(2-6) | 是 | 销项发票 | >0 | 发票带出 | — | **卖价**；金额列，字段防火墙见下（Hisense 5.74、Innolight 10.8）|
| **SUBTOTAL AMOUNT（小计）** | number(2) | 自动 | 数量×单价 | =QUANTITY×UNIT PRICE | 计算 | — | SubTableEditor `quantity*unit_price→total_price`（298296.32 / 648000）|
| **Total AMT（合计金额）** | number(2) | 自动 | 子表汇总 | =Σ SUBTOTAL | 合计 | — | 表尾合计 |

### INV 字段防火墙（关键）

- **PL/INV 是对客户的对外单据，天然只含卖价（UNIT PRICE / SUBTOTAL / Total AMT）与物流信息，绝不含采购进价/原厂报价/PO 单价/批次成本**（总览 §8）。
- **卖价对纯 SALES 角色的可见性**：INV 的金额列对 PM/财务/SA/ADMIN/BOSS 可见；对**纯 SALES 角色**是否在系统内屏蔽 INV 金额列，按总览 §8「卖价对内/对客户可见性细则待甲方确认」处理——**本文标待甲方确认**（gap）。SALES 与 SA 同一可见层（甲方 Q18 2026-06-16：都能看报价利润点/毛利），故 SA 必须能看 INV 金额以核对发票一致性（财务放行依赖此核对，`05b` 页面 4）。
- **采购侧进价/成本明细**（对原厂询价价、PO 单价、入库批次成本、采购在途单价）仍对销售端隐藏，只 PA/PM/财务可见（甲方 Q18）——这些字段**不出现在 PL/INV 任何位置**，无泄漏面。

---

## 单据 3 · 送货单（三类）

### 3a · 客户送货单（`dn_cust`，SA 制作、系统提取打印、签章随货）

**定位**：客户要求随货的送货单（旭创/智禾等），SA 在系统制作，物流出库时**从系统提取并打印**随货（`I-2606-048`「送货单晚点 SA 制作好后，请在系统上提取并打印」），**旭创财务要求打印随货后必须有签字或公章**（同邮件第 8 条）。字段清单直接来自 `RE I-2606-005` 与 `I-2606-048` 邮件列出的送货单列（与出庫登記同源）：

| 字段 | 类型 | 必填 | 选择器来源 | 校验 | 默认 | 扫码兜底 | 引擎映射 |
|---|---|---|---|---|---|---|---|
| 入倉編號 | str | 是 | 出库批次（指定入仓编号）| 串货隔离已在出库校验（`03b`）| 批次带出 | 扫码兜底 | `PR{YYMM}-{seq}-{line}`（总览 §7）|
| 進出庫單號（出库单号）| str | 是 | 出库单 | — | 出库单带出 | — | `PD{YYMM}-{seq}` |
| 進出庫日期 | date | 是 | 出库单 | — | 出库日期 | — | date |
| 型號 | str | 是 | 产品 | 与 INV 一致 | 批次带出 | 扫码兜底 | 显示名解析 |
| SN/LOT# | str | 是 | 出库批次行 | — | 批次带出 | 扫码兜底 | — |
| 供應商 | str | 是 | 供应商主数据 | — | 批次带出 | — | FK 供应商 |
| 性質（货物状态）| enum | 自动 | 批次 | GOODS/SAMPLE/RMA…（`03a` 货物状态）| 批次带出 | — | enum |
| 數量 | number | 是 | 出库批次行 | >0 | 批次数量 | 手填兜底 | `quantity`；**旭创/智禾渲条码** |
| 運單號 | str | 否 | 承运商 | — | — | 手填/扫码 | 快递面单号回填（DHL/FedEx）|
| 送貨形式 | str | 是 | 出库送货形式 | — | LOCAL DELIVERY | — | 同 PL SHIP VIA |
| 客戶 | str | 是 | 客户主数据 | — | 客户带出 | — | FK 客户 |
| INV# | str | 是 | 销项发票 | 与 INV 同号 | 发票带出 | — | 配对 |
| 箱號 | str | 否 | 分箱 | — | — | — | PL 箱号 |
| 签字/公章区 | image/flag | 否（旭创=是）| 盖章流转 | 旭创财务要求必须签字或公章 | — | — | 盖章流转（见下）|

> ⚠️ **客户送货单 vs 标签字段几乎同源**（入倉編號/出庫單號/出庫日期/型號/SN-LOT/供應商/性質/數量），但**用途不同**：送货单是随货纸质单据（整票级），标签是贴在每包/外箱（包级）。两者**共享同一数据源**（出库批次 + 主数据），共享同一**条码渲染开关**（數量列条码），但模板独立（`dn_cust` vs `§9.1 label_template`）。

### 3b · 仓库货代托运单（`dn_fwd`，HONGBODA 类香港仓 SHIPPER'S INSTRUCTIONS）

**定位**：香港仓（HONGBODA 等）给货代的托运指令单（`货物托运单-6.1铜陵.xls` 样本），物流出库时填写/打印。字段来自样本：

| 字段 | 类型 | 必填 | 选择器来源 | 校验 | 默认 | 引擎映射 |
|---|---|---|---|---|---|---|
| Receiving No.（收货号码）/ Income No.（进仓编号）| str | 否 | 仓库系统 | — | — | 例 `Q260601-102`（客户给的入仓号，`回复 RE I-2606-048`「入仓编号：Q260601-102」）|
| 仓库名称/地址/联系人/电话 | text | 是 | 仓库主数据 | — | HONGBODA 默认 | "HONGBODA (HONG KONG) LIMITED … 周小姐 00852-34893681 … 191 Hung Uk Tsuen, Hung Shui Kiu, Yuen Long, N.T." |
| Shipper（寄货人 名称/地址）| text | 是 | 公司主数据 | — | 公司抬头 | Photonteck 抬头 |
| Consignee（收货人 名称/地址/电话）| text | 是 | 客户主数据 | — | 客户带出 | "Innolight Technology(Tongling)… Tel: 15212333817" |
| Notify Party（通知人）| text | 否 | 客户 | — | — | — |
| Trade Term（交易条款）| str | 否 | 出库 | — | — | FOB/FCA |
| Marks & Nos.（唛头）| str | 否 | 分箱 | — | — | — |
| Description & HS code（申报品名及 HS 码）| str | 是 | 产品/HS 主数据 | — | 型号+HS | HS（`06 报关`）|
| Pallets/Cartons（板数/箱数）| str | 是 | 分箱 | — | — | "5Cartons" |
| Gross Weight（毛重）| number | 是 | 仓库填 | — | — | "26.2KGS" |
| Dimension（体积/卡板尺寸）| text | 否 | 仓库填 | — | — | — |
| INV NO（关联发票号）| str | 是 | INV | — | INV 带出 | "INV NO：I-2606-048" |
| Expect Time of Arrival / ETA HK W/H | date | 否 | 出库 | — | — | "2026.6.1" |
| 提货方式（货主送货进仓 / 派车提货）/ 车牌/司机/提货地址/联系人 | mixed | 否 | 物流约车 | — | — | 约车信息块（货代提货 vs 货主送货）|
| 危险品提示 | text | 否 | 模板常量 | — | — | "电池等 9 类危险品…需提前沟通"（样本固定提示）|
| Signature of shipper（寄货人/代理签名）| flag | 否 | 盖章流转 | — | — | 签名作实 |

### 3c · 快递面单登记（DHL/FedEx WAYBILL，外部产物）

**定位**：DHL/FedEx 等承运商系统生成的快递面单（`3048912834.pdf` = DHL EXPRESS WORLDWIDE，含 WAYBILL 30 4891 2834、From/To、Pce/Shpt Weight、Contents: OPTICAL LASER CHIPS）。**本系统不渲染面单本体**，只在出库单登记：

| 字段 | 类型 | 必填 | 来源 | 引擎映射 |
|---|---|---|---|---|
| 承运商（carrier）| enum | 是 | 出库 | DHL/FedEx/HONGBODA/货代 |
| 运单号（waybill_no）| str | 是 | 承运商/手填 | 出库单字段；与送货单「運單號」同（例 DHL `3048912834`）|
| 计费重/件数 | number | 否 | 面单 | "7.5/53.0 kg 1/8"（铜陵规则：20KG 内 FedEx 经济、20KG 以上货代，`I-2606-048`）|
| 面单 PDF 附件 | file | 否 | 上传 | 挂出库单附件（ABAC）|

> ✅ 这是唯一**不需要模板引擎**的送货单形态——只是字段 + 附件，引擎原生兼容（DocEditor 字段 + 附件上传）。

---

## 横切表 1 · 客户差异矩阵（首批 3 客户实化，其余待补）

> 同一引擎、同一字段字典，**差异 = 模板配置取值**。下表为**首批样本归纳**，每格**待甲方逐一确认**（蓝图 §6、总览 gap 2）。公司均为 **Photonteck（香港）**——内地实体（andesec/FTK/RJ/XGTC/TR）抬头/银行/税率差异待 6 套抬头到位后扩充（gap）。

| 维度 ＼ 客户 | Eoptolink（成都新易盛）| Hisense（海信）| Innolight（旭创·铜陵）|
|---|---|---|---|
| PL 形态 | 明细型（每行 SN/LOT）| 汇总型 + 批次子 sheet | 汇总型（按外箱）|
| PL 专属列 | Production date、CONTRACT NO. | Material PN、Country of Diffusion、LOT「详见附件」| Part No.、Rev.、NO. |
| INV 专属列 | — | Material PN、Country of Diffusion | Part No.、Rev.、NO. |
| 价格条款 | FOB HK | FOB HK | **FCA HK** |
| 付款条款 | NET 30 DAYS | AMS 30 DAYS | **Factoring 30 days**（保理）|
| 银行块 | 平安银行 OSA（SZDBCNBS / OSA15000098434729 USD）| （样本未出，默认公司块，待确认）| **汇丰 GTRF 保理 assigned 块**（HSBC，As trustee for HSBC，A/C 741-471031-274）|
| Bill-To vs Ship-To | 同（客户自收）| **不同**（Bill-To=Hisense HK，Ship-To=CYTS 物流）| 同（客户自收）|
| 送货形式 | DHL（账号 950308513，到付 FOB HK）| Local Delivery | Local delivery(HONGBODA)；20KG 内 FedEx 经济/以上货代 |
| 客户送货单 | 需（标签要求更新，随货+附实物外箱，一票多件放首件）| —（待确认）| **需**，旭创财务要求**签字或公章**，系统提取打印 |
| 数量列条码 | 新要求（旭创/智禾系，待确认是否含本客户）| —（待确认）| **是**（旭创要求）|
| 外箱发货日期条码 | —（待确认）| —（待确认）| **是**（`I-2606-048` 第 6 条）|
| 特殊备注 | 包装贴 ROHS；DHL 账号更新 950308513；CARTON SIZE 仓库填 | LOT「详见附件」+ 批次 sheet | 不同型号不混装一箱；物料号加版本「见 INV」；无 LOGO 包装旭创标签加 Brand；附测试数据贴「附出货报告/数据」 |

> **银行块差异（核心）**：①**默认块**=公司收款账户（Eoptolink/Photonteck 用平安银行 OSA 离岸账户）；②**保理 assigned 块**=应收账款已转让给银行（Innolight 用汇丰 GTRF，"This account has been assigned to … HSBC … and is to be paid direct to … GTRF Receivables Finance Division … Account Name: Photonteck Company Limited (As trustee for HSBC)"）。保理块**按客户/合同**切换，是**模板的可配文本块**（不是代码），**哪些客户走保理待甲方确认**（gap，且涉及金蝶应收对接，决策③）。

---

## 横切表 2 · 盖章 / 回签流转

> 盖章版 PL+INV 是硬流转（样本 `I-2606-005 …INV&PL.pdf` 4 页扫描、`260601-…_CIPL.pdf` 扫描图）。落为**出库单的「单据打包」子流程**（不是独立单据，挂出库单 `03b`）：

```
渲染PL/INV(草稿) → 打印 → 盖章 → 扫描成PDF → 邮件回传客户/挂回签件 → 出库放行依赖此件齐备
```

| 阶段 | 角色 | 动作 | 字段/产物 | 引擎映射 |
|---|---|---|---|---|
| 渲染 | LOGISTICS | 选模板灌数据渲 PL/INV | `pl_doc`/`inv_doc` 数据 + custom_html 预览 | ➕ custom_html 逃生舱（`§9.2`）|
| 打印 | LOGISTICS | 本地打印 | 占位（打印驱动待定 gap）| — |
| 盖章 | LOGISTICS | 加盖公司章 | 物理动作 | — |
| 扫描回传 | LOGISTICS | 扫描成 PDF 上传 | `stamped_pl_pdf` / `stamped_inv_pdf` 附件 | 出库单附件（ABAC）|
| 流转校验 | 系统 | 客户给入仓号前先发 PL，收 INV&PL 后给入仓号再约车（Innolight 流程）| 顺序门控标志 | hard_rules（声明式断言，引擎 04 §4.B）|

> **流转顺序约束（Innolight 模式，`I-2606-048`）**：「请先提供 PL，客户收到 INV&PL 后提供入仓号再安排送货」——即**盖章 PL/INV 回传 → 客户回入仓号 → 约车出库**。可落为出库单的 `doc_pack` 子态门控（提供入仓号前不可进 `picking`/约车），但**是否所有客户都走此顺序待甲方确认**（部分客户先发后给号、部分先给号，gap）。盖章为**可隐藏增强**：默认提供盖章+回传位，是否强制阻断出库按客户配置。

---

## 横切表 3 · 条码渲染（旭创/智禾 新要求，2026-06-16 在办）

> 来源：`旭创&智禾标签，新增要求：标签上 数量（Quantity）这一栏增加条形码.eml`（CMD 张凌通知出货组「从即日起数量（Quantity）这一栏加上条形码」，附实拍样张 `Catch71B1.jpg`：Supplier/WRI P/N/PN#/Contract#/**Quantity (pcs) 97 + 红圈标注新增条码**/Serial No.+条码/D/C/**Shipping Date+条码**/Brand/Made in）+ `I-2606-048` 第 6 条「外箱发货日期需增加条形码」、第 9 条「数量（Quantity）这一栏加上条形码」、第 1 条「生产批次和生产日期要体现对应的条码」。

| 渲染目标 | 落点 | 开关 | 条码内容 | 引擎映射 |
|---|---|---|---|---|
| **数量（Quantity）列条码** | ①标签（`§9.1` 包装/外箱）②本文 PL `pl_line.QUANTITY` ③客户送货单 `數量` | `render_as_barcode=true`（按客户）| 数量值（如 97）| `doc_template_field_line.render_as_barcode` + 后端条码图（引擎 08 custom_html 嵌 `<img>` data-uri）|
| **外箱发货日期条码** | 外箱标签（`§9.1`）+ PL「Shipping date」可选 | 同上 | 发货日期（统一日期格式，`I-2606-048` 第 7 条）| 同上 |
| **Serial No. / 生产批次/日期条码** | 标签（已有，`§9.1` 样张已含）| 已有 | SN/LOT、D/C | 已落标签册 |

> **关键**：数量列条码**同时**落标签（`§9.1`，包级）与 PL/客户送货单（本文，整票级）——同一 `render_as_barcode` 开关在两个模板各自启用，由后端同一条码生成库（python-barcode/qrcode 类，服务端生成 `<img>` 注入，避免前端拼，XSS 约束同 `§9.2 D-08d`）。**适用客户范围（旭创/智禾/是否扩展到其他客户）待甲方确认**（gap，邮件明确「旭创&智禾」，但出货组按通知全面执行需确认边界）。日期格式须统一（邮件第 7 条「日期格式统一」，例 `2026-05-29` / `May 28, 2026` 混用需收口，落模板的日期格式配置）。

---

## 横切表 4 · 编号配对与公司隔离

| 单据 | 编号规则 | 配对约束 | 公司隔离 |
|---|---|---|---|
| PL | `PL-{YYMM}-{seq}` | 与 INV **同尾号**（PL-2606-080 ↔ I-2606-080）| 每公司独立、月度重置连号（总览 §7）|
| INV | `I-{YYMM}-{seq}` | 与 PL 同尾号；报关时可切报关单号（`e` 开头）| 同上 |
| 客户送货单 | 跟随出库单 `PD{YYMM}-{seq}` + INV# | 挂 INV# / PD# | 同上 |
| 货代托运单 | 进仓编号 `Q{YYMMDD}-{seq}`（客户/仓库给，如 Q260601-102）| 挂 INV# | 仓库侧 |
| 快递面单 | 承运商号（外部，如 DHL 3048912834）| 登记 `waybill_no` | — |

> 编号规则本体（月度重置+连号+抬头编码）由 `09-配置与模板.md §9.3` 编号规则表生成（➕扩展，引擎 `*_number` 仅给唯一前缀）。本文只规定**配对约束**（PL↔INV 同尾号、送货单挂 INV#）。

---

## 状态机（单据模板本体 `DOC_TEMPLATE`，复用 `§9.2`）

> 单据模板**本体**的状态机已在 `09-配置与模板.md §9.2` 定义（`doc_template` doc_type：`draft → active → disabled`，ADMIN/物流主任配置，FlowEditor 管理态）。**本文不重复定义模板本体状态机**，只补**单据渲染/盖章流转**作为**出库单（`03b OUTBOUND_ORDER`）的子流程**（不是独立 doc_type）：

| 出库单态（`03b`）| 本文相关动作 | 角色 | 字段/校验 | 引擎映射 |
|---|---|---|---|---|
| `picking`（分箱拣货）| 选模板渲 PL/INV、写外箱尺寸/毛净重、提取客户送货单 | LOGISTICS | 不同型号不混装一箱（hard_rule）| custom_html 渲染 + SubTableEditor |
| `review`（互检★）| 核对 PL/INV 型号一致、数量条码、合同号 vs 发票（`03b`，**可同一人，Q7**）| LOGISTICS | 标签 vs 发票一致 | preview→ChangeCard→commit |
| `finance`（财务放行★）| INV 内容 vs 发货内容一致（货不能出仓）| FINANCE | 一致才放行 | 节点 allowed_roles=[FINANCE] |
| `shipped`（已发货）| 盖章 PDF 回传齐备、登记运单号 + 挂面单 | LOGISTICS | 盖章件齐备（按客户配置是否硬阻断）| 附件 + effect 推金蝶（INV→应收）|

---

## 引擎映射兼容性（逐项 ✅/➕/❌）

| 元素 | 引擎映射 | 兼容性 | 说明 |
|---|---|---|---|
| PL/INV/送货单模板本体 | `doc_template`(`__doc_types__`) + `doc_template_field_line`(`_line`→SubTableEditor) | ✅compatible | 模板本体=doc_type+子表，引擎原生（`§9.2` 已建模） |
| 单据**渲染**（抬头/列集/银行块/批次 sheet 排版）| custom_html 逃生舱（引擎 08 §8.3 NodeView innerHTML）| ➕extension | 引擎无单据渲染引擎，仅 custom_html 逃生舱；render_html **后端按白名单字段拼装**，**XSS 必管控**（引擎 08 D-08d）|
| 明细子表网格录入（PL/INV 行、批次 sheet）| SubTableEditor（脏跟踪/自动行号/quantity×unit_price）| ✅compatible | 引擎原生（引擎 08 §8.3）|
| INV 金额计算（数量×单价→小计→合计）| SubTableEditor `quantity*unit_price→total_price` | ✅compatible | 引擎原生自动计算 |
| **数量列/外箱日期条码渲染** | `render_as_barcode` 开关 + 后端条码图 `<img>` data-uri | ➕extension | 引擎无条码生成；服务端库生成图注入 custom_html（与 `§9.1` 同库）|
| 客户差异（列开关/银行块/价格付款条款）| 模板配置取值（数据，非代码）| ➕extension | 元数据驱动，零代码新增客户（`§9.2` 基调）|
| 盖章/回签流转 | 出库单子态 + `stamped_pdf` 附件 + 顺序 hard_rule | ➕extension | 流转标志 + 附件回挂；顺序门控用 hard_rules（引擎 04 §4.B）|
| 快递面单登记（运单号+附件）| 出库单字段 + 附件上传 | ✅compatible | 不渲染面单，仅字段+附件 |
| 公司抬头/银行块解析（6 实体）| `company_id`→抬头映射（主数据）| ➕extension | 需 6 套抬头/银行块入主数据（**待甲方提供** gap）|
| 编号配对（PL↔INV 同尾号、月度重置连号）| 编号规则表（`§9.3`）+ 生成命令 | ➕extension | 引擎 `*_number` 仅唯一前缀，不支持月度重置连号（总览 §7）|
| Excel 日期序列号格式化（46171→2026-05-29）| 前端 date 格式化（引擎 08 §8.3）| ✅compatible | 渲染时格式化，统一日期格式（邮件第 7 条）|
| 字段防火墙（INV 卖价对纯 SALES）| 序列化遮蔽（引擎 01 §1.5、05 §5.3）| ✅compatible（机制）/ 待确认（边界）| 机制原生；卖价对内可见性边界待甲方（总览 §8）|

---

## 金蝶推送

> 本文单据**本身不直接推金蝶**——PL/送货单是物流单据（不入账），INV 的应收推送由**销项发票**（`05b` 页面 5 / `07b` 金蝶推送）在「发票确认」态触发（决策③），出库扣库存/收入确认由**出库单**（`03b`）在「财务放行后出库」触发（总览 §6.2）。本文只确保 INV 的**金额/客户/合同号/币种**字段齐备且与销项发票一致，供 `07b` 映射推送。

| 关联单据 | 推金蝶用途 | 触发态 | 本文职责 |
|---|---|---|---|
| 销项发票（INV 数据源）| 应收/开票 | 发票确认（`05b`/`07b`）| 提供 UNIT PRICE/SUBTOTAL/Total AMT/客户/合同号字段，与 INV 单据一致 |
| 出库/发货单 | 收入确认/结转 | 财务放行后出库（`03b`）| 提供已渲染 PL/INV 作随货件 + 盖章回签件 |

> 保理 assigned 块（Innolight 汇丰 GTRF）涉及应收账款转让，**金蝶应收对接是否区分保理客户待甲方确认**（gap，涉及 `07b` 应收映射）。

---

## 验收标准（可测）

1. **PL/INV 配对**：同一出库单渲染的 PL 与 INV，PL No. 与 Invoice No. **同尾号**（PL-2606-080 ↔ I-2606-080）；型号一致；INV 总数量=PL 总数量。
2. **客户差异渲染**：选 Eoptolink 模板渲明细型 PL（每行 SN/LOT + Production date）；选 Hisense 渲汇总型 PL + 批次子 sheet（83 行批次 Σ=主表 51968）+ Material PN/Country of Diffusion 列；选 Innolight 渲 Part No./Rev./NO. 列 + 汇丰 GTRF 保理银行块。三者**同一引擎、不同配置**。
3. **银行块切换**：Eoptolink 出平安银行 OSA 块，Innolight 出汇丰 GTRF "As trustee for HSBC" 保理块——**改客户配置即切换，不改代码**。
4. **价格/付款条款**：FOB HK / FCA HK、NET 30 / AMS 30 / Factoring 30 按客户配置正确渲染。
5. **数量列条码**：旭创/智禾客户的 PL `QUANTITY` 列、客户送货单 `數量` 列、外箱标签数量值**渲出条形码**（对应 `Catch71B1.jpg` 红圈位置）；外箱发货日期渲条码；非旭创客户不渲（按开关）。
6. **日期格式化**：Excel 序列号 46171 渲染为统一格式日期（不出现 46171 裸数字）。
7. **盖章回签**：渲染→打印→盖章→扫描 PDF 回传可挂到出库单（`stamped_pl_pdf`/`stamped_inv_pdf`），Innolight 流程「先 PL→收 INV&PL→给入仓号→约车」顺序门控生效（若客户启用）。
8. **送货单三类**：客户送货单（SA 制作、系统提取打印、旭创签章位）、货代托运单（HONGBODA 字段集 + 进仓编号 Q260601-102）、快递面单（仅登记 DHL 3048912834 + 挂 PDF）各自正确。
9. **字段防火墙**：PL/INV **不含任何采购进价/原厂报价/PO 单价/批次成本**；INV 卖价列按角色可见性配置遮蔽（边界待甲方）。
10. **公司隔离**：6 实体（Photonteck/andesec/FTK/RJ/XGTC/TR）各自抬头/银行块渲染正确（待 6 套抬头到位）。

---

## 引擎扩展点（engineFlags，入 `_引擎扩展点汇总.md`）

| 扩展点 | 性质 | 引擎落点 |
|---|---|---|
| PL/INV/送货单**渲染引擎**（抬头/列集/银行块/批次 sheet 多排版）| ➕extension | custom_html 逃生舱（引擎 08 §8.3/§8.10），render_html 后端按白名单字段拼装；**XSS 必管控**（引擎 08 D-08d）|
| **条码渲染**（数量列 + 外箱发货日期 + 生产批次/日期）| ➕extension | `render_as_barcode` 开关 + 后端条码图库生成 `<img>` data-uri（与 `§9.1` 同库）；引擎无条码生成 |
| 6 实体抬头/银行块/保理块入主数据 | ➕extension | `company_id`→抬头/银行块映射；**待甲方提供 6 套抬头 + 保理客户清单** |
| 盖章/回签流转 + 顺序门控 | ➕extension | 出库单子态 + 附件回挂 + hard_rules 顺序断言（引擎 04 §4.B）|
| PL↔INV 同尾号 + 月度重置连号编号 | ➕extension | 编号规则表（`§9.3`）+ 生成命令；引擎 `*_number` 仅唯一前缀 |
| Excel 日期序列号格式化 + 日期格式统一 | ✅compatible（前端格式化）| 渲染层格式化；统一格式配置落模板 |

---

## 待甲方确认 gap 汇总（入 `_待甲方确认清单.md`）

1. **6 实体抬头/银行块/税率**：andesec/FTK/RJ/XGTC/TR 五个内地实体的 PL/INV 抬头、地址、银行账户、区域税率（HK vs 内地）——首批仅有 Photonteck（香港）实化，其余待提供（蓝图 §6、总览 gap 2）。
2. **保理客户清单**：哪些客户走应收账款保理（汇丰 GTRF assigned 块）vs 默认公司收款块——影响 PL/INV 银行块切换与 `07b` 金蝶应收映射（决策③）。
3. **数量列/外箱日期条码适用范围**：邮件明确「旭创&智禾」，是否扩展到其他客户、是否全面执行——出货组按通知全面执行需确认边界。
4. **INV 卖价对纯 SALES 角色可见性**：总览 §8 卖价对内/对客户可见性细则——SA 必须可见（核对发票一致），纯 SALES 是否屏蔽 INV 金额列待确认（甲方 Q18：SALES 与 SA 同一可见层，倾向均可见报价/毛利，但 INV 金额屏蔽边界需明确）。
5. **盖章流转是否硬阻断出库**：盖章 PL/INV 回签件未齐备是否阻断 `shipped`、各客户顺序（先发后给号 vs 先给号）是否统一——默认提供盖章位 + 按客户配置阻断。
6. **客户送货单字段全集**：首批从 `RE I-2606-005`/`I-2606-048` 邮件归纳，各客户送货单是否还有专属字段（如旭创 SRM 系统送货单格式）待逐一确认。
7. **打印机集成方式**：物理打印驱动（BarTender 类）+ 快递面单是否需系统侧调承运商 API 出单（vs 仅登记号），待甲方确认（顺丰 API 占位，决策⑪）。
8. **日期格式统一标准**：`2026-05-29` / `May 28, 2026` / `20260421`（8 位）/ Excel 序列号混用——统一为哪种格式（邮件第 7 条要求统一，未给标准）。
