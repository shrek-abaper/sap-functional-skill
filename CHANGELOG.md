# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。

---

## [Unreleased]

### sap-stock-availability — 真实 S/4HANA 首跑与受控直读表兜底(2026-09-20)

- 首次对真实 S/4HANA(client 800)端到端联调:`doctor`、`describe`、`call` 全部跑通。
- 新增 `RFC_READ_TABLE` **受控兜底**:catalog 表白名单(MARD/MCHB/MARC/MARM/MSKA/MKOL/MSKU),CLI 强制显式 FIELDS、主键 WHERE、ROWCOUNT ≤ 100、OPTIONS 行 ≤ 72 字符;新增 `references/direct-table-reads.md` 与实测报文样例。
- 修正路由口径:`BAPI_MATERIAL_GET_DETAIL` 实测不返回库存数量(BAPIMATDOC 仅 PUR_GROUP/ISSUE_UNIT),不再作为账面库存路由。
- vendor `rest2rfc_meta.py` 落地并打三处契约补丁:`?RFC=<FM>` 契约、`functionname` 字段、`--password-stdin`。
- 记录网关侧两项缺陷:EXPORTING 参数不回传(GET_DETAIL 空体、ATP 标量丢失、MRP_STOCK_DETAIL 丢失)、非 200 响应丢弃错误 body。
- `connection.json` 改为本地文件(git 忽略),仓库提供 `connection.example.json` 模板。
- 根目录中英文 README 与 `CLAUDE.md` 收录第三个技能 sap-stock-availability。

## [1.0.0] - 2025-04-29

### 首次发布

**知识库覆盖模块（14 个 reference 文件）**

- `abap.md` — ABAP 开发：语法、性能优化、BAdI/Enhancement Spot、调试工具
- `mm.md` — MM 模块：采购订单、STO 工厂间调拨、科目确定、消息控制
- `sd.md` — SD 模块：销售订单、定价、交货、开票、信贷管理、ATP/MTO
- `fico.md` — FI/CO 模块：凭证过账、汇率、凭证分割、COPA、替换、自动付款
- `pp.md` — PP 模块：生产订单、BOM、工艺路线、MRP、可配置 BOM
- `wm.md` — WM 模块：转储单、转储需求、仓位管理、盘点
- `pm.md` — PM 模块：设备、功能位置、维护订单、维护计划、序列号管理
- `qm.md` — QM 模块：检验批、使用决策、质量通知书、检验计划
- `vms.md` — VMS 模块：IS-AUTO VELO 对象、IDoc 增强、SPRO 配置
- `integration.md` — 系统集成：PI/PO、IDoc、Proxy、OData、XML/JSON 排查
- `auth.md` — 权限管理：AUTHORITY-CHECK、角色、SU53、权限对象
- `print.md` — 打印技术：SmartForms、SAPscript、NACE 消息控制
- `reference-tables.md` — 全模块事务码 / 关键表 / BAPI 索引
- `troubleshooting.md` — 排查案例库 CASE-001 ~ CASE-015

**技能包**

  - `sap-trench-skill` — SAP 实战排查 Skill（首个 skill，位于 `skills/sap-trench-skill/`）
