# 03 · 仓储 WMS — 入库与库存

> 本文是 PHOTONTECK（富泰）CRM+WMS **商业交付级业务 PRD** 的模块 03a，覆盖**仓储 WMS 域的入库与库存部分**。出库 / 调拨 / 盘点的现场执行写在同域的另一文件（03b 出库与盘点）；本文只写：**入库收货、库存（批次/SN/LOT/状态/库位/标记）、库存流水/事务台账、库位管理、标签打印**。
>
> 公约一律继承 `00-导航与参与者总览.md`（下称「§00-x」）：角色中文名、编号规则、字段隐藏、金蝶推送总则、引擎映射约定、UX 公约。本文不重述，只在落点处引用。
>
> 一手源：蓝图 §3.4 仓储/库存域、§4 P03/P06、§5.2 串货隔离、§5.3 SN-LOT、§5.4 货物状态模型、§5.5 编号、§6 标签（下称「蓝图 §x」）；访谈 `飞书导出录音原件/01 香港仓库入库收货操作流程讲解`、`02 仓库进库流程与系统优化讨论`、`03 OCR扫描机与扫码枪入库讨论`（下称「访谈 01/02/03，行号」）；补充材料 `potonteck补充材料/入库/*`（**進庫詳細資料表头=入库字段权威**、扫码采集补充信息.txt、入库编号标签模板 图片5.png、客户标签字段清单回覆.xlsx、TTX-SN登記.xlsx、進庫通知邮件 .eml、供应商-PA主数据.xlsx、HS CODE & DESCRIPTION.xlsx）。
>
> 引擎源：`技术文档/01~04、08`（下称「引擎 0x」），并已核对**引擎现有 WMS 脚手架代码**（`models.py`：`GoodsReceipt/GoodsReceiptLine`=GOODS_RECEIPT、`Inventory`=INVENTORY、`InventoryMovement`/`InventoryTransaction`、`WarehouseLocation`、`InventoryCount/Line`、`SupplierSnRule`、`WmsAttachment`；`services/wms_workflow_extensions.py`：`apply_goods_receipt_costs` 已绑 `GOODS_RECEIPT→STOCKED_IN`）。**入库与库存的引擎底座大体已存在**，本模块多数页面是 ✅compatible 或在现有列上 ➕。
>
> 状态：待甲方评审。日期：2026-06-16。

---

## 模块定位（业务价值一句话）

把香港/内地仓库现在用 **Excel「進庫詳細資料」表 + 扫码枪 + 手工邮件**完成的整条入库流程（收货清点 → 扫码/手填型号·SN·数量·日期 → 取入仓编号 → 拆统一包装 → 库位上架 → 打 62×29mm 标签 → 发進庫通知邮件给 PA → ★PA 入库审核），收口为**一张入库单（批次明细子表为真相源）+ 一套事件溯源库存**，做到：全程留痕、扫码字段一律可手填兜底、库存=流水累加（不再靠 Excel 公式手扣）、明细自动汇总（不再人手维护"基本進庫"汇总表）、标签一键打印、進庫通知自动生成、审核通过自动推金蝶外购/其他入库单。

---

## 参与者视角（角色 → 做什么 / JTBD / 触发时机 / 数据范围 / 限制）

| 角色 | 在本模块做什么（JTBD） | 触发时机 | 数据范围 | 限制 |
|---|---|---|---|---|
| **LOGISTICS 物流专员** | 收货清点核箱数、登记破损异常、取入仓编号、扫码采集（型号/SN/数量/日期）+ 手填兜底、拆统一包装多 PO 行、库位上架、外箱标注、打标签、发進庫通知 | 每天上午 10 点前后快递（顺丰/FedEx/DHL）到货（访谈 01:151） | **本仓**（company_id+warehouse） | 货物异常**只记录不判定**；性质/PO 不明须问 PA 后再录（访谈 01:507、03:531） |
| **LOGISTICS_LEAD 物流主任** | 仓库统筹、库位主数据维护、库存查询、为难单指派审核 PA | 日常 | 本仓 | — |
| **PA 采购助理** | ★**入库审核**（核对该单型号/数量/SN 与 PO 一致、确认货物性质）；回答"该货什么性质" | 收到進庫通知邮件后（访谈 02:169、访谈 01:508） | **本人产线**（按供应商-PA 对应） | 不对客户；审核不过整单退回 |
| **FINANCE 财务** | 本系统**不在入库环节设财务关卡**；入库成本/暂估随★入库审核通过推金蝶后在金蝶侧做账 | 审核通过后 | 本公司账套 | 入库无独立财务放行关卡（区别于出库两道关，决策⑥） |
| **PM/FAE 产品线** | 被动接收：货物性质/版本不明时被 PA/物流问询确认 | 难单出现时 | 本产线 | 仅咨询，不直接操作入库单 |
| **SALES/SA 销售侧** | 查"某型号现在库存多少/某 PO 到货没"（自助查询，替代过去找仓库要数据，访谈 02:664/679） | 随时 | 库存视图（**成本/批次成本对 SALES 隐藏**，§00-8） | 不可改库存；不可见买价/批次成本 |
| **ADMIN 系统管理员** | 库位/HS/计量单位/SN-LOT 规则/标签模板/编号规则主数据 | 配置期 | 全局 | — |
| **BOSS 管理层** | 跨公司库存只读汇总（看板） | 随时 | 全部只读 | privileged，财务绝不合账 |

> 角色依据：物流"每个同事都收不同供应商、平均分配工作"（访谈 01:619）；入库审核"指定专门负责该客户/供应商的 PA"（访谈 02:174）；供应商↔PA 对应来自 `供应商-PA主数据.xlsx`（334 行 SUPPLIER→PA）；异常只记不判（蓝图 §2、访谈 01「不敢自己下判断」01:508）。

---

## 页面清单（本模块含哪些页面/屏）

| # | 页面 | 类型 | 核心引擎落点 |
|---|---|---|---|
| 03a-1 | **入库收货**（入库单 + 批次明细子表）⭐ | 单据 | `GOODS_RECEIPT` doc_type + `goods_receipt_line` 子表 SubTableEditor |
| 03a-2 | **入库审核**（★PA 审核，属审批中心） | 单据状态节点 | `GOODS_RECEIPT` 流程节点 `allowed_roles=[PA]` |
| 03a-3 | **库存（批次/SN/LOT/状态/库位/标记）**⭐ | 台账+下钻 | `INVENTORY`（DataExplorer 只读 + 下钻 DocEditor） |
| 03a-4 | **库存流水 / 事务台账**（事件溯源）⭐ | 只读台账 | `inventory_movement`（DataExplorer，✅引擎已有） |
| 03a-5 | **库位管理** | 主数据 | `warehouse_location`（✅引擎已有，__queryable__） |
| 03a-6 | **标签打印**（入仓编号 62×29mm 条码） | 工具/弹层 | ➕标签模板子系统（引擎仅 custom_html 逃生舱） |
| 03a-7 | **進庫通知**（生成+发邮件给 PA）➕ | 派生动作 | ➕命令/effect（引擎无邮件能力） |
| 03a-8 | **Excel 导入/导出**（系统卡时兜底）➕ | 工具 | ➕批量导入命令（引擎无原生导入） |

> 决策⑦（明细 vs 汇总合一）落点：**批次明细子表 = 真相源**（对应 Excel「進庫詳細資料」27 列）；「基本進庫」汇总表 = 同一入库单的**同页汇总视图 / 导出**，不另开页（访谈 02 现状是两张表手工 copy，01:826/838）。

---

## 03a-1 入库收货（入库单 + 批次明细子表）⭐

### 定位与使用者
物流专员每天收货后录入的主单据。一张入库单 = 一次"同一运单/同一批送达"的收货（如 `PR2606-040`），头部记**基本進庫**信息（单号/日期/供应商/性质/总数/运单/送货形式/PO#/客户），明细子表逐行记**進庫詳細資料**（每个入仓编号一行 = 一个批次/一包/一个 SN-LOT）。**子表为真相源**，头部汇总由子表聚合。

### 典型流程 / 场景（端到端，引用蓝图 P03）

1. **收货清点**（访谈 01:151）：快递 10 点送达，给一张收货单写总箱数；物流核对"箱数/包装破损"——**与送来一致才收货**，破损/缺件**只记异常、当场反映快递，不判定责任**（蓝图 §2「异常只记录不判定」）。
2. **分类摆放 + 开箱拆包**：按供应商分开摆，拆外箱到最小包装，**按生产日期先后排序**（替代不了 FIFO，但物理上按时间排，方便后续找货，蓝图 §5.2、访谈 01:154/304）。
3. **取入仓编号**：从本公司本月连号序列里取下一个 `PR{YYMM}-{seq}`（如 `PR2606-040`），物流"先选一个号、记住、避免打乱编号次序"（访谈 01:154、02:91）。每个批次行再带 `-{line}` 后缀（`PR2606-040-01/02…`）。
4. **扫码采集 + 手填兜底**（访谈 01:316/388、02:220）：
   - 扫码枪（CINO A670/A670BT）**先扫该供应商二维码切换解码程序**，再扫；**只有 4 个字段能扫：型号、SN、数量、（部分）生产日期**（扫码采集补充信息.txt、访谈 01:340）。
   - 扫码须**固定顺序：型号→SN→数量→日期**，顺序错就乱跳要删重扫（访谈 01:388/394）。
   - 其余字段（原产地/HS/运单/送货形式/箱号/位置/性质/Date Code/REMARK）**全部手填**；某些供应商（如 HK Phone）**全字段手填无可扫**（访谈 01:712、02:343）。
   - **生产日期**部分供应商条码无、需手填，按已排好的时间序"输一个、相同的往下复制"（访谈 02:220/274）。
5. **统一包装多 PO 拆分**（访谈 01:538/547、关键规则）：一包里若出现 2~3 个不同 PO，**必须按 PO 拆成 2~3 个入仓编号行**（系统一个入仓号只能对一个 PO）；这些行**型号/SN/日期相同、仅 PO 与数量不同**，须**红字标注 + 备注"統一包裝"**并在進庫通知里提醒 PA（访谈 01:577/592）。
6. **性质（goods_nature）确认**：默认 `GOODS`；文件上有 customer PO 基本=GOODS；**无 PO 或不明 → 可能是样品/翻收/RMA，必须问 PA 确认后才录，物流不敢自判**（访谈 01:507/514、03:531）。
7. **生产日期/Date Code/版本尾码补录**：部分原厂要求尾码标"新版/旧版/百分比/ROCK3"等，写在型号尾或 REMARK（访谈 01:322/658/673）。
8. **库位上架**：找有空位的货架放，记库位编号回填字段；**快进快出的高周转货走流转仓、不上架**（蓝图 P03、访谈 01:784）。**无 FIFO**——按时间序物理摆放（蓝图 §5.2）。
9. **外箱标注**：大箱在箱外写"本单编号 + 行范围"（如 `2606023, 1~14`）便于找货（访谈 01:604）。
10. **打标签**：约 20 包内逐包打 62×29mm 入仓编号条码标签贴左上角；极端量（如 700~800 包）才不逐包贴（访谈 01:280/298）。详见 03a-6。
11. **test data 附件**：随货有 test data 时扫描成附件，連同進庫通知一起发（访谈 01:835、02:28）。
12. **發送進庫通知邮件**给负责该供应商的 PA（CC 全体 PA），正文含「基本進庫」汇总 + 「進庫詳細資料」明细（访谈 02:01、進庫通知 .eml 实样）。详见 03a-7。
13. **提交入库 → ★PA 入库审核**（访谈 02:169「我们会有一个审查功能…要给 PA 看…审查就完成这一单」）。审核通过 → 库存生成 + 推金蝶。

> ★ 财务硬关卡：**入库环节无独立财务关卡**（财务做账随推金蝶在金蝶侧完成）；唯一审核关卡是 **★PA 入库审核**（决策⑤吸收进审批中心）。区别于出库的两道关（决策⑥）。

### 字段表 — 入库单头（基本進庫，对应 Excel「基本進庫」sheet + .eml 抬头）

| 字段 | 类型 | 必填 | 选择器来源 | 校验 | 默认 | 扫码兜底 | 引擎映射 |
|---|---|---|---|---|---|---|---|
| 入库单号 `receipt_number` | string | 自动 | — | 唯一、`PR{YYMM}-{seq}` 月度连号 | 系统生成 | — | `goods_receipt.receipt_number`（✅列已存在；月度连号规则 ➕，见§00-7） |
| 入库类型 `inbound_type` | enum | 是 | 外购入库/其他入库[样品]/退货入库/调拨入库/**委外加工入库** | — | 外购入库 | — | ➕新增列（访谈 02:37 外购物入单/其他入库；**委外加工入库做薄**，甲方 2026-06-16 反馈 + 决策⑫，详见 03a-9；区别于 K3 原工序版不做，访谈 02:56） |
| 进库日期 `received_date` | date | 是 | 日期 | ≤今天；27 号后归下月（盘点边界，访谈 02:79） | 今天 | — | `goods_receipt.received_date`（✅） |
| 供应商 `supplier_id` | fk | 是 | 供应商主数据 cell 选择器 | 存在 | — | 外箱肉眼识别后选（访谈 01:188） | `goods_receipt`→`supplier`（头部 ➕ FK，现行内 supplier 在行级；见兼容性注） |
| 性质 `goods_nature` | enum | 是 | GOODS/SAMPLE/RMA/翻收… | 不明须问 PA | GOODS | — | `goods_receipt_line.goods_nature`（✅列存在，头部可冗余） |
| 总数量 `total_quantity` | number | 自动 | — | =子表 Σ数量 | 子表聚合 | — | 子表聚合（决策⑦汇总视图） |
| 货物数量单位 `uom` | enum | 是 | 包/盘/PCS（§5.3） | — | PCS | — | `goods_receipt_line.uom`（✅） |
| 运单号 `tracking_number` | string | 否 | — | 同批一致；本地送货无单号填 `M1`（访谈 01:526） | — | 外箱运单贴纸手抄 | `goods_receipt_line.tracking_number`（✅） |
| 送货形式 `delivery_method` | enum | 是 | 顺丰/FEDEX/DHL/本地… | — | — | — | `goods_receipt_line.delivery_method`（✅） |
| PO# `purchase_order_id`/`source_doc_number` | fk/string | 是* | PO 总表 cell 选择器 | 与明细一致；无 PO 须问 PA | — | — | `goods_receipt.purchase_order_id`（✅）+ 行级 `source_doc_number` |
| 客户 `customer_id` | fk | 否（可后补） | 客户主数据 | — | — | — | ➕ `goods_receipt.customer_id`（蓝图 §3.4「客户可后补」；行级原厂报备客户见库存） |
| 审核 PA `reviewer_id` | fk | 是 | 按供应商自动带出（供应商-PA 对应表） | 存在 | 自动匹配 | — | ➕ `goods_receipt.reviewer_id`；自动匹配规则见兼容性 |
| 备注 `notes` | text | 否 | — | — | — | — | `goods_receipt.notes`（✅） |

\* PO# 必填但允许"无 PO 待 PA 确认"的暂挂态。

### 字段表 — 批次明细子表 `goods_receipt_line`（進庫詳細資料，**网格录入**，权威=27 列表头）

> UX：**Excel 式多行网格 + 行内 cell 选择器**（引擎 `SubTableEditor`），贴合现在用 Excel 登记的习惯（§00-5）。扫码枪把"型号/SN/数量/日期"按行依次填入；其余手填。下表「源列」= `進庫詳細資料.xlsx` r1 表头。

| 字段 | 源列 | 类型 | 必填 | 选择器/扫码 | 校验 | 引擎映射 |
|---|---|---|---|---|---|---|
| 入仓编号 `inbound_number` | 入倉編號 | string | 是 | 自动 `PR{YYMM}-{seq}-{line}` | 唯一=标签条码主键 | `goods_receipt_line.inbound_number`（✅）；编号生成 ➕ |
| 进出库单号 `source_doc_number` | 進出庫單號 | string | 自动 | 带入头单号 | — | `goods_receipt_line.source_doc_number`（✅） |
| 进出库日期 `production_received` | 進出庫日期 | date | 自动 | 带入头日期 | — | （映射头 `received_date`） |
| 型号 `material_id` | 型號 | fk | 是 | **扫码**①→产品/型号选择器 | 存在；尾码细分写 REMARK（访谈 01:658/673） | `goods_receipt_line.material_id`（✅）→`material.sku` |
| SN/LOT# `serial_lot_number` | SN/LOT# | string | 是 | **扫码**② / 手填 | 按 SN 唯一(单件)或 LOT(批) | `goods_receipt_line.serial_lot_number`（✅）；SN/LOT 规则 `supplier_sn_rule`（✅） |
| 供应商 `supplier_id` | 供應商/SUPPLIER | fk | 是 | 选择器 | 存在 | `goods_receipt_line.supplier_id`（✅） |
| 性质 `goods_nature` | 性質 | enum | 是 | 选择器（不明问 PA） | — | `goods_receipt_line.goods_nature`（✅） |
| 数量 `actual_quantity` | 數量 | number | 是 | **扫码**③ / 手填 | >0；每包数可变(几十~2000，§5.3) | `goods_receipt_line.actual_quantity`（✅）；`expected_quantity`=PO 应收 |
| 货物数量单位 `uom` | 貨物數量單位 | enum | 是 | 包/盘/PCS | — | `goods_receipt_line.uom`（✅） |
| 运单号 `tracking_number` | 運單號 | string | 否 | 同批带入 | — | `goods_receipt_line.tracking_number`（✅） |
| 送货形式 `delivery_method` | 送貨形式 | enum | 是 | 选择器 | — | `goods_receipt_line.delivery_method`（✅） |
| PO#/INV# `po_inv` | PO#/INV# | string | 是* | PO 选择器 | 统一包装多 PO 须拆行（见场景5） | 行级承载（✅ via source/po）；多 PO 拆行=多行 |
| 箱号 `carton_number` | 箱號 | string | 否 | 手填（如 `1-5`） | — | `goods_receipt_line.carton_number`（✅） |
| 原产地 `origin_country` | 原產地 | string | 是 | 历史带出/手填（访谈 01:739） | — | `goods_receipt_line.origin_country`（✅） |
| HS CODE `hs_code` | HS CODE | string | 是 | 按型号查 HS 主数据带出（访谈 01:883/02:553） | — | `goods_receipt_line.hs_code`（✅）；HS 主数据 `HS CODE&DESCRIPTION.xlsx` |
| 位置（库位）`location_code` | 位置 | string | 上架后 | 库位选择器/手填（访谈 01:792） | 流转仓可空 | `goods_receipt_line.location_code`（✅）+ `inventory.location_id` |
| Date Code `date_code` | Date Code | string | 否 | 手填 | 与生产日期不同(访谈 02:241) | `goods_receipt_line.date_code`（✅） |
| 生产日期 `production_date` | 生產日期 | date | 否 | **扫码**④(部分)/手填(部分) | 按时间序复制 | `goods_receipt_line.production_date`（✅） |
| REMARK `remark` | REMARK | text | 否 | 手填(尾码/版本/漏气/统一包装红字) | 统一包装须标 | ➕ `goods_receipt_line.remark`（现无此列，需加；访谈 01:673/02:301） |
| 报关费 `customs_fee` | 報關費 | number | 否 | 后补（报关域回填） | — | ➕列；多由报关模块回填 |
| 运费 `freight_fee` | 運費 | number | 否 | 后补 | — | ➕列 |
| 进出口证 `import_export_cert` | 進出口證 | string | 否 | 手填 | 可 `#N/A` | ➕列 |
| 发货数量 `shipped_quantity` | 發貨數量 | number | 自动 | 出库累减 | =Σ出库 | 由出库 movement 投影（出库模块） |
| 库存（结存）`balance_quantity` | 庫存 | number | 自动 | 数量-发货数量 | 事件累加 | `inventory.quantity`-`reserved`（事件投影，✅ movement） |
| BAG SEAL DATE `bag_seal_date` | BAG SEAL DATE | date | 否 | 手填 | — | ➕列（部分供应商封袋日） |
| BA留货 `ba_hold` | BA留貨 | string/bool | 否 | 手填 | — | ➕列（内部留货标记，访谈未深述→待甲方） |

> 字段权威：上表逐列对齐 `進庫詳細資料.xlsx` r1 的 27 个表头。其中约 18 列引擎 `goods_receipt_line` 已有同义列（标✅）；6 列需 ➕新增（remark/customs_fee/freight_fee/import_export_cert/bag_seal_date/ba_hold），均为简单加列、不破坏底座。

### 子动作页/弹层

| 子动作 | 说明 | 引擎落点 |
|---|---|---|
| **收货清点 / 破损异常登记** | 录总箱数、核实收、登记破损/缺件异常（只记不判） | 入库单初始态字段 + ➕ `discrepancy_note`（行级已有 `discrepancy_note`✅）；异常照片 `wms_attachment`✅ |
| **取入仓编号** | 取本月下一连号 | ➕编号生成命令（§00-7） |
| **扫码采集** | 4 字段扫码枪录入到网格行 | ➕前端输入增强（聚焦网格、扫码顺序锁、供应商二维码切换提示） |
| **OCR 兜底** | 包装无条码时拍照 OCR 填字段（甲方已被坑买了贵 OCR 大机，本系统轻量前端 OCR 即可，访谈 03 全篇） | ➕前端 OCR 控件（结果回填仍走人工确认；0/O、I/E 易错须复核，访谈 02:598） |
| **统一包装多 PO 拆分** | 一包多 PO → 拆多入仓编号行 + 红字 + 备注統一包裝 | 子表多行 + `remark` 红字标记；进庫通知红字提示 |
| **性质待 PA 确认** | 不明性质暂挂、问 PA | 暂挂态 / `goods_nature` 留空 + 备注 |
| **生产日期补录** | 部分供应商手填、按时间序复制 | 网格行 `production_date` 手填 + "向下复制"前端便捷 |
| **库位上架** | 回填库位编号 | `location_code`/`location_id` |
| **外箱标注** | 箱外写单号+行范围（线下，系统不强制） | 仅 `carton_number` + 行范围由 line_number 推导 |
| **test data 附件** | 扫描随货 test data 作附件 | `wms_attachment`（attachment_type=TEST_DATA）✅ |
| **Excel 导入/导出** | 系统卡时先扫到 SL 再导入（访谈 02:646/652） | 03a-8 ➕导入命令 |

### 单据状态机 `GOODS_RECEIPT`

| 状态 code | 名称 | 可操作角色 | 可编辑字段 | 硬规则/关卡 | 下一状态 |
|---|---|---|---|---|---|
| `DRAFT` *(is_initial)* | 草稿/收货录入 | LOGISTICS | 头部 + 全部明细字段 | 收货清点完成；统一包装多 PO 须拆行 | `PENDING_REVIEW`（提交并发進庫通知） |
| `PENDING_REVIEW` | 待 PA 入库审核 ★ | PA（按供应商自动匹配的 reviewer） | 仅审核备注（明细只读） | hard_rule：明细 Σ数量=头部总数；每行 SN/LOT 非空；每行性质非空（access SupplierSnRule）；统一包装行已标记 | `STOCKED_IN`（通过）/ `DRAFT`（退回） |
| `STOCKED_IN` *(is_terminal-ok)* | 已入库（库存生效） | 系统 | — | **effect：生成 Inventory 批次 + 写 InventoryMovement(IN) + 推金蝶外购/其他入库单** | （终态） |
| `REJECTED` | 已退回 | LOGISTICS | 全部 | — | `DRAFT`（修改重提） |

> 引擎契约：`STOCKED_IN` 已被现有 effect `wms.apply_goods_receipt_costs`（`GOODS_RECEIPT→STOCKED_IN`，`wms_workflow_extensions.py:48`）绑定，落 `InventoryMovement` + 成本。**入库审核=审批中心**：`PENDING_REVIEW.allowed_roles=[PA]`，PA 在「我的审批」收件箱经 `preview→ChangeCard→commit` 通过/退回（§00-4.7）。

### 引擎映射 & 兼容性（逐条）

- ✅ **入库单 doc_type**：`GoodsReceipt.__doc_types__=("GOODS_RECEIPT",)` 已注册，`receipt_number` 唯一前缀自动填（引擎 02 §2.3 `_auto_fill_required_fields`）。
- ✅ **批次明细子表**：`goods_receipt_line`（名含 `_line`、FK 指 `goods_receipt`）→ 前端自动 SubTableEditor 多行网格（引擎 08 §8.3）；约 18 列已存在。
- ✅ **入库审核状态节点**：`PENDING_REVIEW` 角色闸 + hard_rules（明细聚合断言走 rules.py DSL `sum_field`/子表上下文，引擎 04 §4.B）。
- ✅ **入库→库存→流水的派生**：`STOCKED_IN` AUTO effect 已接线写 `InventoryMovement`（引擎 04 §4.A、现有 `apply_goods_receipt_costs`）。
- ✅ **附件**：`wms_attachment`（含 test data/异常照片/标签照片）已建（`__queryable__`）。
- ✅ **SN/LOT 校验**：`supplier_sn_rule`（长度/正则/唯一范围）已建，挂 `@register_transition_validator`（引擎 04）。
- ➕ **入库类型列 `inbound_type`** + **头部 `supplier_id/customer_id/reviewer_id`** + **6 个明细补列**（remark 等）：均为简单加列 + 一次 alembic 迁移（引擎 01 §1.3 "加实体不改引擎一行"），不破坏底座。
- ➕ **入仓编号月度重置连号** `PR{YYMM}-{seq}-{line}`：引擎 `*_number` 只给唯一前缀，不支持月度重置连号 → §00-7 编号规则表 + 生成命令。**必入 engineFlags**。
- ➕ **扫码采集前端增强**：网格行聚焦 + 扫码顺序锁(型号→SN→数量→日期) + 供应商二维码切换提示 + 错序清行重扫；引擎无采集层（§00-4.9）。
- ➕ **OCR 兜底控件**：前端拍照→OCR→回填字段，人工复核（0/O、I/E 易错）；引擎无 OCR。
- ➕ **审核 PA 自动匹配**：按 `supplier→PA` 对应（供应商-PA主数据.xlsx）带出 `reviewer_id`；落 ➕主数据表 `supplier_pa_map` 或在 `supplier` 上加 `default_pa_id`，由创建态 effect/前端带出。
- ❌ **无**（本页未发现需破坏引擎语义的点）。

### 业务单据推送（金蝶）

| 触发态 | 推送单据 | 幂等键 | company_id | 备注 |
|---|---|---|---|---|
| `STOCKED_IN`（外购入库） | **外购入库单** | `receipt_number` | 本租户→对应金蝶组织 | 访谈 02:37「外购物入单新增」；明细级（K3 只接受明细数据，访谈 02:697/706） |
| `STOCKED_IN`（其他入库=样品/退货） | **其他入库单** | `receipt_number` | 同上 | 访谈 02:37「sample/RMA 用其他入库」 |

> 落点（§00-6.3）：`STOCKED_IN` 节点挂 ➕ `@register_transition_effect` 适配器写 `kingdee_outbox`（带 `receipt_number` 幂等键 + company_id + 状态 + 回执），失败可重推。**注意明细颗粒度**：金蝶要每包/每 SN 明细（访谈 02:697），TTX 等"汇总一箱一行"的入库须在推送时展开为明细（见 03a-1 场景 + TTX-SN 子表）。**委外加工入库**（做薄）按需推金蝶委外加工入库单 / 其他入库单，**委外发料**推委外出库单 / 其他出库单（甲方 2026-06-16 反馈，详见 03a-9）。

### 验收标准（可测） + 待甲方确认 gap

- ✅ 录一张含 3 行明细的入库单，头部总数 = 子表 Σ数量，否则提交被 hard_rule 拦。
- ✅ 一包 2 个 PO 时，系统支持拆成 2 个入仓编号行（型号/SN/日期相同、PO/数量不同），且 REMARK 自动带"統一包裝"红字标记。
- ✅ 扫码枪连扫"型号/SN/数量/日期"按行落入网格；任一字段可手工改写覆盖（兜底）。
- ✅ 提交后自动生成進庫通知（含基本進庫+詳細資料），收件人=该供应商对应 PA、CC 全 PA。
- ✅ PA 在审批中心通过 → 生成 Inventory 批次 + 1 条 InventoryMovement(IN) + 1 行 kingdee_outbox(外购/其他入库)。
- ✅ 性质留空/SN 空的行无法通过 PA 审核（hard_rule）。
- gap-1：**入库类型**取舍（委外加工入库改为"做薄"，详见 03a-9，甲方 2026-06-16；调拨入库是否走入库单还是调拨单生成？待甲方）。
- gap-2：`BA留貨`、`進出口證`、`BAG SEAL DATE` 三列的业务含义/填写规则需甲方逐列确认（访谈未深述）。
- gap-3：本地送货无运单号填 `M1` 是否系统固化为默认值（访谈 01:526）。
- gap-4：报关费/运费是入库时填还是报关模块回填（本文按"报关回填"设计，待确认）。

---

## 03a-2 入库审核（★PA，属审批中心）

### 定位与使用者
本页不是独立页，而是**审批中心的一个收件箱条目**（§00-4.7）。负责该供应商的 PA 收到進庫通知后，在「我的审批」里看到该入库单 `PENDING_REVIEW`，核对**型号/数量/SN 与 PO 一致、货物性质正确**，通过则入库生效，否则退回物流。

### 典型流程
1. PA 工作台「★入库待审核」卡显示待审入库单（访谈 02:169「派个人反复确认这一单的量/型号有没有错误」）。
2. PA 打开下钻入库单 DocEditor，看只读明细 + 历史 + 关联 PO（`/related` 沿 FK）。
3. 核对一致 → 通过（`STOCKED_IN`）；不一致 → 退回（`REJECTED→DRAFT`）并写退回原因。
4. 通过经 `preview→ChangeCard→commit`（字段 diff + 检查 + 建议），留 WorkflowLog。

### 引擎映射 & 兼容性
- ✅ 审批收件箱 = `list_user_todos`（角色=PA + 本租户 + 排除终态，引擎 02 §2.5）。
- ✅ 通过/退回 = `execute_transition` 推进（节点 `allowed_roles=[PA]`，引擎 02 §2.3）。
- ✅ 一致性 hard_rules（Σ数量、SN 非空、性质非空）= rules.py DSL（引擎 04 §4.B）。
- ➕（引擎欠账）**边级角色 D-02e**：若"退回"边设 `roles`，execute_transition 推进路径当前只校验节点级 → 列 §00-4.2 FR-2.7 补齐，入 engineFlags。
- ❌ 无。

### 验收标准 + gap
- ✅ 只有"该供应商对应 PA"（或 ADMIN/BOSS privileged）能在收件箱看到并推进该单。
- gap：审核是否需"多级"（访谈 02:169 提到「多级审查」一闪而过）→ 默认单级 PA，多级待甲方。

---

## 03a-3 库存（批次/SN/LOT/状态/库位/标记）⭐

### 定位与使用者
全仓库存的**真相台账**，按**批次（=入仓编号）**粒度。任何角色（含销售自助）查"某型号有多少/某 PO 到货没/在哪个库位"，替代过去找仓库人手 Excel 筛选（访谈 02:664/679「PA 提某型号/某 PO 现库存多少」）。**库存 = 库存流水累加的投影**（决策⑦、蓝图 §3.4「库存=事件累加，不用 Excel 公式」），本页只读 + 下钻，不在此直接改数。

### 典型流程/场景
- 入库审核通过 → 每个批次行生成一条 `Inventory`（status=AVAILABLE/或按性质置初态）。
- 出库发货 → `reserved`/`quantity` 经 movement 递减（出库模块）。
- 状态/标记变更（待检→可售、RMA好货混回可售、报废）→ 写一条状态变更 movement（不直接改库存数）。
- 串货隔离：批次带**原厂报备客户**，出库分配校验"报备给 A 的货不能出给 B"（蓝图 §5.2，校验在出库模块，本页只承载该字段）。

### 字段表（库存批次 `inventory`，**列表网格只读 + 下钻**）

| 字段 | 类型 | 说明 | 选择器/来源 | 扫码兜底 | 引擎映射 |
|---|---|---|---|---|---|
| 入仓编号 `inbound_number` | string | 批次主键=标签条码 | 入库带入 | 扫标签条码定位 | `inventory.inbound_number`（✅，index） |
| 批次号 `batch_number` | string | 批次 | 入库带入 | — | `inventory.batch_number`（✅，非空 index） |
| 型号 `material_id` | fk | 产品/型号 | 主数据 | — | `inventory.material_id`（✅）→`material.sku` |
| SN/LOT `serial_lot_number` | string | SN(单件)/LOT(批) | 入库带入 | 扫 | `inventory.serial_lot_number`（✅，index） |
| 供应商 `supplier_id` | fk | — | 主数据 | — | `inventory.supplier_id`（✅） |
| 性质 `goods_nature` | enum | GOODS/SAMPLE/RMA… | — | — | `inventory.goods_nature`（✅） |
| 数量 `quantity` | number | 当前结存 | 事件投影 | — | `inventory.quantity`（✅） |
| 已预留 `reserved_quantity` | number | 被订单占用 | 事件投影 | — | `inventory.reserved_quantity`（✅） |
| 单位 `uom` | enum | 包/盘/PCS | — | — | `inventory.uom`（✅） |
| **库存状态** `status` | enum(7) | 可售/已预留/待处理待检/NG/样品/原厂暂存/报废 | — | — | `inventory.status`（✅列存在，**但枚举需扩，见兼容性**） |
| **来源/品质标记** `source_marker` | json/string | RMA来源(客退/原厂换/修/返工/自测)+品质(好/坏)+原厂；PCN标记 | — | — | ➕新增列（引擎现无） |
| 原厂报备客户 `reported_customer_id` | fk | 串货隔离用 | 客户主数据 | — | ➕新增列（蓝图 §3.4/§5.2；现 `inventory` 无此列） |
| 库位 `location_id`/`location_code` | fk/string | 货区/货架/货层 | 库位选择器 | 扫库位码 | `inventory.location_id`+`location_code`（✅） |
| Date Code / 生产日期 | string/date | — | 入库带入 | — | `inventory.date_code`/`production_date`（✅） |
| 原产地/HS | string | 报关用 | 入库带入 | — | `inventory.origin_country`/`hs_code`（✅） |
| 收货日期 `received_date` | date | — | 入库带入 | — | `inventory.received_date`（✅，index） |
| 报关费/运费 | number | 后补 | 报关回填 | — | ➕（与入库明细同源） |
| 单位成本 `unit_cost`/批次成本 `total_cost` | number | **对 SALES 隐藏** | 入库结成本 | — | `inventory.unit_cost`/`total_cost`（✅）**字段防火墙** |

### 库存状态模型（蓝图 §5.4，甲方已确认两层）

**① 库存状态**（主状态，决定能否被占用/出货）

| status | 可售 | 引擎值（建议） |
|---|---|---|
| 可售 | ✅ | `AVAILABLE` |
| 已预留 | ❌ | `RESERVED` |
| 待处理/待检 | ⏳ | `QUARANTINE` ➕ |
| NG 不良 | ❌ | `NG` ➕ |
| 样品 | ❌ | `SAMPLE` ➕ |
| 原厂暂存 | ❌ | `VENDOR_HOLD` ➕ |
| 报废 | ❌（终态） | `SCRAP` ➕ |

**② 来源/品质标记**（可叠加，用于筛选+人工决策）：RMA来源(客退/原厂换/原厂修/返工/自测) + 品质(好/坏) + 哪个原厂；PCN 后货带 PCN 标记（可能限定销售对象）；样品转销售=样品→可售。**RMA"好"货 → status=可售（混回正常库）但保留来源标记，由人决策是否使用**（甲方确认）。

### 引擎映射 & 兼容性
- ✅ **库存台账**：`Inventory.__doc_types__=("INVENTORY",...)` → DataExplorer 只读网格（首行 introspection 自动出列、千分位、status 药丸）+ 下钻 DocEditor（引擎 08 §8.3）。决策⑩"大台账=只读网格+下钻"在此适用。
- ✅ **批次/SN/LOT/库位**列已存在（`inbound_number/serial_lot_number/location_id/...`）。
- ✅ **成本对 SALES 隐藏**：`inventory.unit_cost/total_cost` 走字段防火墙（query+schema 两路遮蔽），配 `BUY_TABLES/BUY_PRICE_FIELDS`（§00-8、引擎 01 §1.5）。**本页必须显式标防火墙**。
- ➕ **库存状态枚举扩展**：现 `inventory.status` 仅 `AVAILABLE/RESERVED`（wms_commands 只写这两值）→ 扩为 7 态枚举 + 各态可售性规则（出库占用校验读它）。不破坏底座（只是值集 + 校验）。
- ➕ **来源/品质标记 `source_marker`** + **原厂报备客户 `reported_customer_id`**：引擎现无 → 加列。前者驱动"RMA好货保留标记/PCN限售/筛选"，后者驱动**串货隔离出库校验**（蓝图 §5.2，校验落出库模块）。**必入 engineFlags**。
- ✅ **库存=事件累加**：当前值是投影，真相在 `inventory_movement`（见 03a-4），符合蓝图"不用 Excel 公式"。
- ❌ **无 FIFO**（蓝图 §5.2 物理做不了 FIFO）：引擎有 `ix_inventory_fifo` 索引但业务上**不强制 FIFO 出库**；出库批次由 SA 指定入仓编号（出库模块）。此为业务取向，非引擎不兼容——**不要在出库写死 FIFO 分配**，列入 gap 提醒。

### 业务单据推送（金蝶）
库存本身不单独推；其变动随入库（外购/其他入库单）、出库（出库发货单）、盘点（库存调整单）等触发单推送（§00-6.2）。

### 验收标准 + gap
- ✅ 销售角色查库存看不到 `unit_cost/total_cost`（schema 与 query 都不返回该列）。
- ✅ 入库审核通过后该批次以 `status=AVAILABLE`（或按性质置 SAMPLE/QUARANTINE）出现在库存台账。
- ✅ 7 种状态可在库存台账按 status 药丸过滤。
- gap-5：原厂报备客户的**录入时机**（入库时录 or 出库分配时定）需甲方确认（蓝图 §5.2 仅说带此属性）。
- gap-6：PCN 限售对象、RMA 好货"由人决策是否使用"的具体决策人/动作（默认人工筛选，不做自动拦截）。

---

## 03a-4 库存流水 / 事务台账（事件溯源）⭐

### 定位与使用者
库存的**事件溯源真相源**：入/出/调拨/盘点调整/状态变更每发生一次写一条不可改流水，`inventory.quantity` 只是这些事件的累加投影（蓝图 §3.4「StockTxn 事件溯源、库存=事件累加」）。物流主任/PA/财务/BOSS 查"这批货怎么来怎么走的"，审计与对账用。

### 典型场景
- 入库审核通过 → `IN`（quantity_delta>0）。
- 出库发货 → `OUT`（quantity_delta<0）/ 预留 `RESERVE`（reserved_delta>0）。
- 调拨（同公司仓间）→ 一对 `TRANSFER_OUT/IN`。
- 盘点差异 → `COUNT_ADJUST`（±差异，挂库存调整单）。
- 状态变更（待检→可售/报废）→ `STATUS_CHANGE`。

### 字段表（`inventory_movement`，**只读台账**）

| 字段 | 类型 | 说明 | 引擎映射 |
|---|---|---|---|
| 事件类型 `movement_type` | enum | IN/OUT/RESERVE/RELEASE/TRANSFER_OUT/IN/COUNT_ADJUST/STATUS_CHANGE | `inventory_movement.movement_type`（✅，index） |
| 型号 `material_id` | fk | — | ✅ |
| 仓库 `warehouse_id` | fk | — | ✅ |
| 批次 `inventory_id` | fk | 关联批次 | ✅ |
| 数量变化 `quantity_delta` | number | ±可用量 | ✅ |
| 预留变化 `reserved_delta` | number | ±预留 | ✅ |
| 单位成本 `unit_cost` | number | **对 SALES 隐藏** | ✅ 防火墙 |
| 来源单据 `source_doc_type`/`source_doc_id` | string/id | 入库/出库/盘点单 | ✅（index） |
| 命令链 `command_log_id` | fk | 同一命令审计链 | ✅（引擎 03/04） |
| 操作人/时间 | fk/datetime | — | `created_by_id`/`created_at`（✅） |

### 引擎映射 & 兼容性
- ✅✅ **完全现成**：`InventoryMovement.__queryable__` 已建（带 company_id/command_log_id/movement_type/quantity_delta/source_doc），现有 effect `apply_goods_receipt_costs` 已往里写。DataExplorer over `inventory_movement` = 流水台账，按 movement_type/material 过滤、下钻来源单。
- ✅ 命令日志查看器 `CommandCenter` 还提供 `/logs/{id}/inventory-movements`（引擎 03 §3.9 提及）做命令↔流水联查。
- ➕ 仅需补 `movement_type` 的枚举覆盖（STATUS_CHANGE/COUNT_ADJUST 等业务值），值集扩展，不破坏底座。
- ❌ 无。

### 验收标准
- ✅ 入库审核通过后，台账多一条 `IN`、quantity_delta=该批次数量、source_doc=该入库单。
- ✅ `Σ(quantity_delta where inventory_id=X) = inventory.quantity(X)`（投影一致性）。
- ✅ 流水不可编辑/删除（只增）。

---

## 03a-5 库位管理

### 定位与使用者
ADMIN/物流主任维护库位主数据（三级：货区/货架/货层，固定编号）+ 类型（普通/流转仓/RMA/样品/待处理/NG）。香港办公室平面布局见 `仓库平面图/香港办公室平面布局尺寸图.pdf`。

### 字段表（`warehouse_location`，主数据网格）

| 字段 | 类型 | 必填 | 校验 | 引擎映射 |
|---|---|---|---|---|
| 仓库 `warehouse_id` | fk | 是 | 存在 | `warehouse_location.warehouse_id`（✅） |
| 库位编码 `code` | string | 是 | (warehouse,code) 唯一（如 `F03`/`C51`/`C48`） | `warehouse_location.code`（✅） |
| 货区 `zone` | string | 否 | — | `warehouse_location.zone`（✅） |
| 货架 `shelf` | string | 否 | — | `warehouse_location.shelf`（✅） |
| 货层 `position` | string | 否 | — | `warehouse_location.position`（✅） |
| 库位类型 `location_type` | enum | 否 | 普通/流转仓/RMA/样品/待处理/NG | ➕新增列（蓝图 §3.4 Location.类型；现表无） |
| 启用 `is_active` | bool | — | — | `warehouse_location.is_active`（✅） |

### 引擎映射 & 兼容性
- ✅ `warehouse_location` 已建（`__queryable__`，(warehouse,code) 唯一约束）→ DataExplorer/DocEditor 维护。库位实例样例来自進庫詳細資料「位置」列（F03/C51/C48）。
- ➕ `location_type` 列（流转仓"快进快出不上架"、RMA/样品/NG 专仓需此分类）。
- ❌ 无。

### 验收标准 + gap
- ✅ 同仓库位编码唯一；流转仓库位可标记，使入库时该库位货可"不上架"。
- gap-7：6 公司各自库位编码体系是否统一；平面图仅有香港，内地库位待补（待甲方）。

---

## 03a-6 标签打印（入仓编号 62×29mm 条码）

### 定位与使用者
物流在入库时为每个入仓编号打 1 张 **62×29mm** 标签（`PR2604-048-01` 文本 + 一维条码），贴包装左上角，便于出库找货（访谈 01:280/379、模板实样 `入库编号标签模板/图片5.png` 确认尺寸 62×29mm）。当前痛点：要先开 SL 表输编号、拉数量、再跳打印机程序，步骤多（访谈 02:570）；诉求是**系统里点一下一键生成并打印**（访谈 02:563/586）。

> 注意：本页只管**内部入仓编号标签**。给客户出货用的**客户标签**（各客户字段/二维码拼接规则不同，~13~25 家，见 `客户标签字段清单回覆.xlsx` 25 个 sheet、`客户二维码信息/*.pdf`）属**出库模块 + 8 配置/模板模块**，本文不展开，仅指出其与入仓编号标签共用同一标签模板子系统。

### 典型流程
1. 入库录入后，对选中批次行（或整单约 20 包）点"打印标签"。
2. 系统按入仓编号生成条码（一维码=`inbound_number`），按 62×29mm 模板渲染。
3. 直接送标签打印机；漏打/多打可补打单张（访谈 01:439/448 多贴/漏贴自查）。

### 字段/模板要素

| 要素 | 值 | 来源 |
|---|---|---|
| 尺寸 | 62×29 mm | 图片5.png（红框规格 `62mm x 29mm`） |
| 主文本 | 入仓编号 `PR{YYMM}-{seq}-{line}` | `inventory.inbound_number` |
| 条码 | 一维条码(入仓编号) | 同上（=标签条码主键） |
| 批量 | 整单逐包 / 单张补打 | 子表行 |

### 引擎映射 & 兼容性
- ➕ **标签模板子系统**（§00 扩展点）：引擎仅 `custom_html` 逃生舱（节点级 innerHTML，引擎 08 §8.3/D-08d），不足以做"可配字段映射+条码渲染+尺寸+多客户二维码拼接规则"。需新增可配模板模型（`label_template`：尺寸/字段映射/条码字段/二维码分隔符序）+ 渲染服务 + 打印触发。**必入 engineFlags**。
- ➕ 一键打印动作 = 入库单/库存页上的批量动作命令（`@register_command`），生成条码图、调浏览器打印或标签机。
- ❌ 无（不破坏底座，纯新增子系统）。

### 验收标准 + gap
- ✅ 选中 N 个入仓编号 → 一键生成 N 张 62×29mm 标签（文本+条码一致），无需先手填编号/拉数量。
- ✅ 单张补打可用（解决漏打）。
- gap-8：标签打印机型号/驱动（ZPL/EPL/CSN）需现场确认；二维码拼接规则属客户标签（出库模块），首批字段待甲方逐家签字（§00 gap）。

---

## 03a-7 進庫通知（生成 + 发邮件给 PA）➕

### 定位与使用者
入库提交时，自动生成并发送"進庫通知"邮件给**负责该供应商的 PA**（CC 全体 PA + 相关同事），正文含**基本進庫汇总 + 進庫詳細資料明细**（统一包装红字提示），随货 test data 作附件（访谈 02:01/28、進庫通知 .eml 实样：标题 `260602 - 富泰進庫通知 PR2606-040`，正文两段表格）。这是 PA 入库审核的触发凭据。

### 内容要素（对齐 .eml）
- 标题：`{YYMMDD} - 富泰進庫通知 {receipt_number}`。
- 正文段一「基本進庫」：进出库单号/进库日期/型号/供应商/性质/数量/单位/运单号/送货形式/PO#/客户。
- 正文段二「進庫詳細資料」：18 列明细（每入仓编号一行）。
- test data 提示行 + 附件；统一包装红字提示。

### 引擎映射 & 兼容性
- ➕ **邮件能力**：引擎无邮件发送 → 新增 `@register_command`（生成 HTML 邮件 body + 收件人解析 + 发送）或 `@register_transition_effect`（`GOODS_RECEIPT→PENDING_REVIEW` 触发），写一条发送记录（可挂 `wms_attachment`/通知中心）。**必入 engineFlags**。
- ➕ 收件人解析复用"供应商→PA 对应"（供应商-PA主数据.xlsx）。
- ✅ 也可降级为"系统内通知中心 + 待办"（§00 通知中心），邮件作为可选增强（甲方现流程强依赖邮件，建议保留邮件）。
- ❌ 无。

### 验收标准 + gap
- ✅ 提交入库 → 自动产出進庫通知（基本+詳細），收件人=对应 PA、CC 全 PA。
- gap-9：是否保留外发邮件（vs 仅系统内通知）；邮件服务器/发件域（@photonteck.com）配置待甲方提供。

---

## 03a-8 Excel 导入 / 导出 ➕

### 定位与使用者
系统偶发卡顿时物流仍要做货：先扫到本地 SL（Excel），稳定后按格式**导入**系统；反向也要**导出**（导给报关用的"基本進庫"打印、给其他部门要的库存筛选）（访谈 02:646/652、01:826 打印报关表、TTX/SL 直接 copy 过去 02:687）。

### 引擎映射 & 兼容性
- ➕ **批量导入命令**：按進庫詳細資料列映射的 Excel → `@register_command` 批量建入库单+明细（带行级校验、错误回执）。引擎无原生导入。
- ✅ **导出**：DataExplorer 自带客户端 BOM CSV 导出（引擎 08 §8.3）；"基本進庫"打印视图 = 子表聚合导出。
- ❌ 无。

### 验收标准 + gap
- ✅ 用进库详细资料格式的 Excel 可一键导入成入库单（错误行有回执，不静默丢行）。
- ✅ 库存/流水/入库明细均可导出 CSV。
- gap-10：导入是否需 TTX 那种"汇总一箱一行 + 详细每包一行"双表同步导入（访谈 02:697 K3 要明细、SL 给汇总）→ 默认导入明细、汇总由系统聚合，待甲方确认。

---

## 03a-9 委外加工（薄）— 委外发料 + 委外加工入库 ➕

### 定位（业务价值一句话）
甲方有少量"把自己的材料发给委外方加工/采买、再把成品或货收回来"的场景。本系统**做薄**：只管两件实物动作——**①委外发料**（材料从本仓发出给委外方，库存减）+ **②委外加工入库**（成品/货从委外方收回入库，库存增）；**完全不管中间的生产过程、工序、BOM、工时、领料倒冲**（决策⑫"委外加工入库也要做但做薄"+ 甲方 2026-06-16 反馈"相当于只发材料给他们买东西/加工"）。即：委外 = 一发一收两张实物单，**不建工单、不拆工序、不算加工成本明细**（成本核算在金蝶侧）。

> 与早期"K3 原工序版委外不做"（访谈 02:56）的关系：那条说的是**不照搬 K3 的完整委外工序模块**；本节落地的是甲方 2026-06-16 拍板的**薄版**（只发料+成品入库）。两者不冲突——薄版即"去工序化"的委外。

### 参与者视角（角色 → 做什么 / JTBD / 触发时机 / 数据范围 / 限制）

| 角色 | 在委外（薄）做什么（JTBD） | 触发时机 | 数据范围 | 限制 |
|---|---|---|---|---|
| **PA 采购助理** | 发起**委外发料**（选委外方=供应商、选要发出的批次/型号/数量）；委外货回来后★**审核委外加工入库**（核对收回品名/数量与发料是否对得上、确认性质） | 委外加工需求出现时 / 货回仓收到時 | **本人产线**（按供应商-PA 对应；委外方按供应商主数据登记） | 不对客户；做薄=不管工序/BOM；审核不过整单退回 |
| **LOGISTICS 物流专员** | 按委外发料单**实际拣货发出**（拆包、扫码/手填发出批次与数量、登记物流单号）；货回时**收货清点 + 录委外加工入库单**（扫码/手填型号/SN/数量/日期 + 库位上架 + 打标签） | 委外发料执行时 / 委外货到仓时 | **本仓** | 异常只记不判（同 03a-1）；扫码字段一律手填兜底 |
| **FINANCE 财务** | 入库环节**不设独立财务关卡**；委外发料/入库成本随★审核通过推金蝶后在金蝶侧做账（与外购入库一致） | 审核通过后 | 本公司账套 | 委外**无独立财务放行关卡**（区别于正常出库两道关，决策⑥） |
| **PM/FAE 产品线** | 被动接收：委外货性质/版本不明时被问询确认 | 难单出现时 | 本产线 | 仅咨询，不操作单据 |
| **SALES/SA 销售侧** | 一般不参与；如需可查委外货回库存（**成本/批次成本对 SALES 隐藏**，§00-8） | 随时 | 库存视图 | 不可改库存；不可见买价/批次成本 |

> 角色依据：委外方=供应商主数据一员（供应商-PA 对应，同 03a-1 reviewer 自动匹配）；做薄=只发料+成品入库（甲方 2026-06-16）；异常只记不判、扫码手填兜底（§00-5、访谈 01）。

### 页面 / 单据清单（本节含）

| # | 页面/单据 | 类型 | 核心引擎落点 |
|---|---|---|---|
| 03a-9a | **委外发料**（出库的一种类型，材料发出）⭐ | 单据 | 复用出库单 doc_type，`outbound_type=委外发料`（出库模块 03b）；明细子表 SubTableEditor |
| 03a-9b | **委外加工入库**（成品/货回入库）⭐ | 单据 | `GOODS_RECEIPT` doc_type，`inbound_type=委外加工入库` + `goods_receipt_line` 子表 |

> 设计取向：**委外发料挂在出库域**（它就是一次实物出库，库存减），但因其与委外加工入库成对、且本节统一交代委外薄流程，故在 03a 同页交代发料端的字段/状态，出库模块（03b）只需在 `outbound_type` 枚举里承载"委外发料"值、复用出库状态机骨架（**不走客户发货的财务放行关卡**，因发料对象是委外方非客户）。

### 端到端流程（薄版，一发一收）

1. **委外发料发起**（PA）：选委外方（=供应商）、选要发出的库存批次（按入仓编号/型号/SN，库存减）、填数量、可附"加工/采买要求"说明（自由文本，不建工序）。
2. **委外发料执行**（物流）：按单拣货、拆包、扫码/手填实际发出批次与数量、登记物流单号（顺丰/快递），库存做 `OUT`（出库 movement）。
3. **委外加工/采买**（委外方线下完成，**系统不跟踪、不建工单**）。
4. **委外货回收货**（物流）：货回仓，收货清点（异常只记不判）、取入仓编号、扫码/手填录**委外加工入库单**（型号/SN/数量/日期 + 库位上架 + 打 62×29mm 标签），可在备注关联对应委外发料单号（弱关联，仅留痕，不做数量勾稽强校验）。
5. **★PA 审核委外加工入库**：核对收回品名/数量、确认性质，通过 → 库存生效（`IN`）+ 按需推金蝶；不一致退回物流。

> ★ 财务硬关卡：委外两端**均无独立财务关卡**（做账随推金蝶在金蝶侧完成）；委外加工入库的唯一审核关卡 = **★PA 入库审核**（复用 03a-2 审批中心机制）。

### 字段表 — 委外发料单头（复用出库单头 + 委外特有字段）

| 字段 | 类型 | 必填 | 选择器来源 | 校验 | 默认 | 扫码兜底 | 引擎映射 |
|---|---|---|---|---|---|---|---|
| 出库单号 `outbound_number` | string | 自动 | — | 唯一、`PD{YYMM}-{seq}` 月度连号 | 系统生成 | — | 出库单 `*_number`（出库模块；编号规则 ➕，§00-7） |
| 出库类型 `outbound_type` | enum | 是 | 客户发货/调拨出库/**委外发料** | — | — | — | ➕出库 `outbound_type` 枚举加"委外发料"（出库模块 03b） |
| 委外方 `vendor_id` | fk | 是 | 供应商主数据 cell 选择器 | 存在 | — | — | 复用出库单收货对象字段；委外方=供应商（➕语义=委外方） |
| 发料日期 `issued_date` | date | 是 | 日期 | ≤今天 | 今天 | — | 出库单日期列（✅同义） |
| 加工/采买说明 `outsource_note` | text | 否 | — | 自由文本，**不建工序** | — | — | ➕ `outsource_note` 列（仅留痕，无 BOM） |
| 物流单号 `tracking_number` | string | 否 | — | — | — | 外箱运单贴纸手抄 | 出库单 `tracking_number`（✅同义） |
| 审核 PA `reviewer_id` | fk | 是 | 按委外方(供应商)自动带出 | 存在 | 自动匹配 | — | ➕同 03a-1 reviewer 自动匹配（供应商→PA） |
| 备注 `notes` | text | 否 | — | — | — | — | 出库单 `notes`（✅） |

### 字段表 — 委外发料明细子表（**网格录入**，发出哪些批次/型号/数量）

| 字段 | 类型 | 必填 | 选择器/扫码 | 校验 | 引擎映射 |
|---|---|---|---|---|---|
| 发出入仓编号 `inbound_number` | string | 是 | 库存批次选择器 / **扫标签条码** | 该批次库存可用、status=可售/可发 | 出库明细→`inventory.inbound_number`（✅定位批次） |
| 型号 `material_id` | fk | 是 | **扫码**①/选择器 | 与所选批次一致 | 出库明细 `material_id`（✅）→`material.sku` |
| SN/LOT# `serial_lot_number` | string | 是* | **扫码**②/手填 | 单件按 SN | 出库明细 `serial_lot_number`（✅；*LOT 批量可空） |
| 发出数量 `quantity` | number | 是 | **扫码**③/手填 | >0 且 ≤该批次可用结存 | 出库明细数量（✅）；触发 `OUT` movement |
| 单位 `uom` | enum | 是 | 包/盘/PCS | — | 出库明细 `uom`（✅） |
| 备注 `remark` | text | 否 | 手填 | — | ➕出库明细 `remark`（同 03a-1 加列性质） |

### 字段表 — 委外加工入库（复用 03a-1 入库单，仅差异列）

> **完全复用 03a-1 入库单头 + `goods_receipt_line` 批次明细子表**（27 列权威，见 03a-1），仅以下差异：

| 字段 | 差异说明 | 引擎映射 |
|---|---|---|
| 入库类型 `inbound_type` | 固定取值 **`委外加工入库`** | ➕枚举新增值（见 03a-1 头字段表已加） |
| 供应商 `supplier_id`（=委外方） | 此处语义=委外方（货从谁那回来） | `goods_receipt.supplier_id`（✅同列，语义复用） |
| 性质 `goods_nature` | 默认 `GOODS`（委外成品/采买货）；不明问 PA | `goods_receipt_line.goods_nature`（✅） |
| 关联委外发料单 `source_issue_number` | 弱关联：备注/字段记对应委外发料单号，**仅留痕，不做数量勾稽强校验**（做薄） | ➕ `goods_receipt.source_issue_number` 或写 `notes`（弱关联） |
| 其余 27 列 | 同 03a-1（入仓编号/型号/SN/数量/库位/HS/原产地…） | 同 03a-1（✅/➕同源） |

### 状态机

**委外发料**（复用出库状态机骨架，**去掉客户发货的财务放行关卡**）

| 状态 code | 名称 | 可操作角色 | 硬规则/关卡 | 下一状态 |
|---|---|---|---|---|
| `DRAFT` *(is_initial)* | 草稿/发料录入 | PA / LOGISTICS | 发出数量 ≤ 各批次可用结存 | `ISSUED`（确认发出） |
| `ISSUED` *(is_terminal-ok)* | 已发料（库存减） | 系统 | **effect：写 InventoryMovement(OUT) 扣对应批次 + 按需推金蝶委外出库/其他出库单** | （终态） |
| `CANCELLED` | 已取消 | PA | — | （终态，未发出前可取消） |

> 关键差异：委外发料对象是**委外方（非客户）**，故**不经"仓库互检 + 财务放行"两道关**（决策⑥仅针对客户发货）；薄版按"发出即扣库存"处理（如需互检可后续按甲方反馈加，列 gap）。

**委外加工入库**（复用 03a-1 `GOODS_RECEIPT` 状态机，原样）

| 状态 code | 名称 | 可操作角色 | 硬规则/关卡 | 下一状态 |
|---|---|---|---|---|
| `DRAFT` *(is_initial)* | 草稿/收货录入 | LOGISTICS | 明细 Σ数量=头部总数；每行 SN/LOT 非空；性质非空 | `PENDING_REVIEW` |
| `PENDING_REVIEW` | 待 PA 审核 ★ | PA（按委外方自动匹配） | 同 03a-1 hard_rules | `STOCKED_IN`（通过）/`DRAFT`（退回） |
| `STOCKED_IN` *(is_terminal-ok)* | 已入库（库存生效） | 系统 | **effect：生成 Inventory 批次 + InventoryMovement(IN) + 按需推金蝶委外加工入库/其他入库单** | （终态） |
| `REJECTED` | 已退回 | LOGISTICS | — | `DRAFT` |

### 引擎映射 & 兼容性（逐条）

- ➕ **`inbound_type` 枚举加"委外加工入库"**：在 03a-1 已加的 `inbound_type` ➕列上**追加一个枚举值**，复用整套 `GOODS_RECEIPT` doc_type + `goods_receipt_line` 子表 + `STOCKED_IN→apply_goods_receipt_costs` effect + `PENDING_REVIEW` 审核节点。**不新增 doc_type、不新增状态机**——纯值集扩展。
- ➕ **委外发料走出库类型**：在出库模块（03b）的 `outbound_type` ➕枚举上**追加"委外发料"值**，复用出库单 doc_type + 出库明细子表 + `OUT` movement effect；仅在状态机配置上**绕过客户发货的财务放行边**（委外发料态机 `DRAFT→ISSUED` 不挂 FINANCE 放行节点）。**不新增 doc_type**。
- ➕ **委外特有列**：`outsource_note`（发料头，自由文本）+ `source_issue_number`（入库头，弱关联委外发料单号）+ 出库明细 `remark`——均简单加列 + 一次 alembic 迁移（引擎 01 §1.3）。
- ➕ **审核 PA 自动匹配**：复用 03a-1 E5（供应商→PA 对应，委外方=供应商）带出 `reviewer_id`。
- ✅ **库存事件溯源**：发料 `OUT` / 收回 `IN` 都落 `inventory_movement`（✅引擎已有），库存=事件累加，无需额外底座。
- ✅ **审批中心**：委外加工入库审核复用 `list_user_todos`（PA 收件箱）+ `execute_transition`（§00-4.7）。
- ❌ **不做（明确边界）**：**无工序 / 无 BOM / 无委外工单 / 无领料倒冲 / 无工时与加工成本明细核算**——这些引擎构件（若要做将是 K3 式委外工单模型 + 工序状态机）**本节一律不建**（决策"做薄"）。成本核算在金蝶侧。**别硬写工序模型**。
- ➕（引擎欠账）**边级角色 D-02e**：委外加工入库"退回"边若设 `roles`，execute_transition 推进路径当前只校验节点级 → §00-4.2 FR-2.7 补齐（同 03a-2）。

### 业务单据推送（金蝶，按需）

| 触发态 | 推送单据 | 幂等键 | company_id | 备注 |
|---|---|---|---|---|
| 委外发料 `ISSUED` | **委外出库单 / 其他出库单**（按金蝶组织科目惯例择一） | `outbound_number` | 本租户→对应金蝶组织 | 材料发出给委外方；做账在金蝶（甲方 2026-06-16「按需」） |
| 委外加工入库 `STOCKED_IN` | **委外加工入库单 / 其他入库单** | `receipt_number` | 同上 | 成品/货回入库；明细级（金蝶要明细，访谈 02:697）；与外购入库同机制 |

> 落点（§00-6.3）：复用 `STOCKED_IN`/`ISSUED` 节点挂 ➕ `@register_transition_effect` 适配器写 `kingdee_outbox`（带 `receipt_number`/`outbound_number` 幂等键 + company_id + 状态 + 回执），失败可重推。具体推"委外加工入库单"还是"其他入库单"、"委外出库单"还是"其他出库单"，依金蝶云星空对应组织的单据类型配置而定（参 `金蝶供应链财务API离线文档.html`，待甲方/金蝶侧确认映射）。**做账/成本核算在金蝶，本系统只推实物单据。**

### 验收标准（可测） + 待甲方确认 gap

- ✅ PA 发起委外发料，选 1 个库存批次发出 N 件 → `ISSUED` 后该批次结存减 N（1 条 `OUT` movement），库存台账实时反映。
- ✅ 发出数量 > 批次可用结存时被 hard_rule 拦截（不允许超发）。
- ✅ 委外货回，录一张 `inbound_type=委外加工入库` 的入库单，复用 03a-1 整套录入（扫码/手填/标签/库位），PA 审核通过 → 库存 `IN` + 1 行 kingdee_outbox（委外加工入库/其他入库）。
- ✅ 委外发料**不经财务放行关卡**（直接 DRAFT→ISSUED），区别于客户发货两道关（决策⑥）。
- ✅ 全程**无工序/工单/BOM 录入界面**（验证做薄边界：系统里找不到工序、领料倒冲、加工成本明细等字段）。
- gap-13：委外发料是否需要"仓库互检"一道关（薄版默认不设，发出即扣库存）——待甲方按上线反馈定。
- gap-14：委外发料↔委外加工入库的**数量勾稽**是否要做（薄版默认弱关联仅留痕、不强校验"发出 X 必收回对应 Y"）——委外采买/良率损耗场景下强校验会误拦，待甲方确认。
- gap-15：金蝶侧委外用"委外加工入库单 / 委外出库单"专用单据 还是 "其他入出库单"承载——需对 `金蝶供应链财务API离线文档.html` + 各公司金蝶组织配置逐一确认（§00 gap-7 组织映射）。
- gap-16：委外方是否一律登记为供应商主数据（默认是），还是需独立"委外方"主数据——默认复用供应商，待甲方。

---

## 本模块引擎扩展点汇总（必入全 PRD engineFlags）

| # | 扩展点 | 性质 | 引擎落点 |
|---|---|---|---|
| E1 | 入仓编号 `PR{YYMM}-{seq}-{line}` 月度重置连号 | ➕extension | §00-7 编号规则表（公司×单据×前缀×重置周期×当前序号）+ 生成命令；引擎 `*_number` 仅唯一前缀 |
| E2 | 库存状态枚举扩 7 态（QUARANTINE/NG/SAMPLE/VENDOR_HOLD/SCRAP） | ➕extension | 扩 `inventory.status` 值集 + 各态可售性校验；现仅 AVAILABLE/RESERVED |
| E3 | 来源/品质标记 `source_marker` + 原厂报备客户 `reported_customer_id` | ➕extension | `inventory` 加列；驱动 RMA好货保留标记/PCN限售/**串货隔离出库校验**（蓝图 §5.2） |
| E4 | 入库类型 `inbound_type` + 入库单头 supplier/customer/reviewer + 6 明细补列(remark/customs_fee/freight_fee/import_export_cert/bag_seal_date/ba_hold) | ➕extension | 加列 + 一次 alembic 迁移 |
| E5 | 审核 PA 自动匹配（供应商→PA） | ➕extension | ➕ `supplier_pa_map` 或 `supplier.default_pa_id` + 创建态 effect 带出 reviewer |
| E6 | 扫码采集前端增强（顺序锁/供应商二维码切换/错序清行） | ➕extension | 前端输入增强填字段；引擎无采集层 |
| E7 | OCR 兜底控件（拍照→回填，人工复核） | ➕extension | 前端 OCR；引擎无 OCR（甲方贵 OCR 大机可替代，访谈 03） |
| E8 | 标签模板子系统（入仓编号 62×29mm + 客户标签二维码拼接） | ➕extension | `label_template` 模型 + 渲染服务 + 打印命令；引擎仅 custom_html 逃生舱 |
| E9 | 進庫通知邮件生成+发送 | ➕extension | `@register_command`/effect（GOODS_RECEIPT→PENDING_REVIEW）+ 邮件服务；引擎无邮件 |
| E10 | Excel 导入命令 | ➕extension | 批量建单命令 + 行级错误回执；导出复用 DataExplorer CSV |
| E11 | 金蝶外购/其他入库单推送（STOCKED_IN） | ➕extension | `kingdee_outbox` + 适配器 effect（receipt_number 幂等键 + company_id），明细展开；§00-6.3。**全 PRD 最大扩展点** |
| E12 | movement_type 枚举补（STATUS_CHANGE/COUNT_ADJUST 等） | ➕extension | 值集扩展 |
| E13 | 边级角色推进路径补齐（退回边 roles） | ➕extension（引擎欠账） | 引擎 02 D-02e / FR-2.7 |
| E14 | 委外加工入库（薄）：`inbound_type` 枚举加"委外加工入库" + 入库头 `source_issue_number`（弱关联委外发料单） | ➕extension | 纯值集扩展 + 加列；复用整套 `GOODS_RECEIPT` doc_type/子表/审核节点/STOCKED_IN effect，**不新增 doc_type/状态机**（03a-9） |
| E15 | 委外发料（薄）：出库 `outbound_type` 枚举加"委外发料" + 发料头 `outsource_note` + 出库明细 `remark` | ➕extension | 出库模块（03b）值集扩展 + 加列；复用出库单 doc_type + `OUT` movement，发料态机绕过客户发货财务放行边；**不建工序/BOM/工单**（03a-9） |
| E16 | 委外金蝶推送（委外出库/其他出库 + 委外加工入库/其他入库，按需） | ➕extension | 复用 `kingdee_outbox` + 适配器 effect（`ISSUED`/`STOCKED_IN`），单据类型映射依金蝶组织配置（§00-6.3、03a-9） |

> 已存在、无需扩展（✅）：`GOODS_RECEIPT` doc_type、`goods_receipt_line` 子表（18 列）、`STOCKED_IN→apply_goods_receipt_costs` effect、`inventory` 批次真相源（绝大多数列）、`inventory_movement` 事件流水、`warehouse_location`、`inventory_count/line`、`supplier_sn_rule`、`wms_attachment`、字段防火墙、审批中心机制。

## 待甲方确认 gap 汇总

1. 入库类型取舍：**委外加工入库改为"做薄"**（甲方 2026-06-16 反馈，详见 03a-9；早期"不做"指不照搬 K3 工序版，访谈 02:56）；调拨入库是走入库单还是由调拨单派生入库流水（待甲方，影响 03a-1 与 03b 调拨）。
2. 進庫詳細資料 3 个含义不明列 `BA留貨` / `進出口證` / `BAG SEAL DATE` 的填写规则。
3. 本地送货无运单号是否固化默认 `M1`（访谈 01:526）。
4. 报关费/运费录入归属（入库时填 vs 报关模块回填，本文按报关回填设计）。
5. 原厂报备客户的录入时机（入库录 vs 出库分配时定）。
6. PCN 限售对象 / RMA "好货由人决策是否使用" 的具体决策人与动作（默认人工筛选，不自动拦截）。
7. 6 公司库位编码体系是否统一；内地库位（平面图仅香港）。
8. 标签打印机型号/驱动；客户标签首批字段逐家签字（属出库/配置模块）。
9. 是否保留外发進庫通知邮件（vs 仅系统内通知）；邮件服务器/发件域配置。
10. Excel 导入是否需 TTX 双表（汇总+明细）同步（默认导明细、系统聚合汇总）。
11. 入库审核是否需多级（访谈 02:169 一闪"多级审查"）→ 默认单级 PA。
12. 金蝶外购/其他入库单的**组织映射**与**明细颗粒度**（每包/每 SN）确认（访谈 02:697 K3 只接受明细）。
13. 委外发料是否需"仓库互检"一道关（03a-9 薄版默认不设，发出即扣库存）。
14. 委外发料↔委外加工入库的**数量勾稽**是否要做（薄版默认弱关联仅留痕、不强校验"发出 X 必收回 Y"，避免委外采买/良率损耗误拦）。
15. 金蝶侧委外用"委外加工入库单/委外出库单"专用单据 还是 "其他入出库单"承载（参 `金蝶供应链财务API离线文档.html` + 各公司金蝶组织配置）。
16. 委外方是否一律登记为供应商主数据（默认是，复用 reviewer 自动匹配），还是需独立"委外方"主数据。
