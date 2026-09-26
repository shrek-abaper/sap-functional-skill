---
name: sap-stock-availability
description: 查询 SAP 库存与物料可用性(只读):ATP 可用量与能否发货、MD04 供需缺口与缺料时间、按库存地点或批次的账面库存、特殊库存(销售订单/供应商寄售/客户寄售)、近期收发货明细、按描述找物料号。当用户问"某物料在某工厂还有多少库存/可用量""库存够不够发""什么时候缺料""库存在哪个库存地点""最近收了多少、发了多少",即使没有点名本技能也应使用。不适用并应直接拒绝:任何过账/创建/修改/删除(收货、发货、转储、预留)、采购审批、财务凭证、物料主数据维护。
license: MIT
allowed-tools: [Read, Bash]
metadata:
  version: "1.0.0"
  type: hybrid
  valid_until: evergreen
  permissions:
    read_paths:
      - "connection.json"
      - "catalog.json"
      - ".cache/"
    write_paths:
      - ".cache/"
    network_endpoints:
      - "REST2RFC gateway URL configured in connection.json (user-provided)"
    can_spawn_processes: true
    requires_elevation: false
    accesses_env_vars:
      - REST2RFC_HOST
      - REST2RFC_CLIENT
      - REST2RFC_USER
      - REST2RFC_PASSWORD
      - REST2RFC_PATH
      - REST2RFC_VERIFY
      - REST2RFC_CA_BUNDLE
      - REST2RFC_TIMEOUT
  output_schema:
    format: json
  mcp_hints:
    readOnlyHint: true
    destructiveHint: false
    idempotentHint: true
    openWorldHint: true
---

# SAP 库存与物料可用性查询(只读)

## 适用与不适用

适用:库存可用量、供需缺口、账面库存、物料移动明细、按描述找物料号。
不适用(直接拒绝并说明原因):任何过账、修改、创建、删除;非库存域问题(采购审批、财务凭证等)。
本 Skill 只能调用 `catalog.json` 里列出的函数。清单外的函数不要尝试,网关会返回 404。

## 执行纪律(按顺序)

1. **环境体检**:本会话首次调用前跑 `python3 scripts/sap_stock.py doctor`。它同时报告凭据后端与网关可达性。退出码 3 = 凭据缺失或失效,转到「凭据配置引导」,**不要重试**。
2. **选函数**:从下表按问句选一个函数。无法判定时问用户一个消歧问题,不要"全部试一遍"。
3. **读函数说明**:`python3 scripts/sap_stock.py describe <FUNC>`。输出参数树 + SE37 长文本 + 请求骨架。**不要凭记忆拼参数名**。
4. **组装报文**:把对话里的业务值填进骨架。必填筛选缺一个就向用户要,绝不自己编默认值(工厂、日期区间、检查规则尤其不能猜)。
5. **调用**:`python3 scripts/sap_stock.py call <FUNC> --payload <file.json>`。
6. **叙事说明**:先给结论数字,再说口径,最后附调用事实。格式见下。

## 场景 → 函数 → 必填筛选 → 口径

| 场景问句 | 函数 | 必填筛选 | 口径说明 |
| --- | --- | --- | --- |
| 还有多少可用量 / 能不能发 | BAPI_MATERIAL_AVAILABILITY | 物料、工厂、单位、检查规则 | ATP 可用量,受检查规则影响,**不等于**账面库存;网关已可用,但真实承诺量以 OPJJ(T441V)为准,`DIALOGFLAG=N` 表示检查组+规则未配置、检查被跳过 |
| 什么时候缺料 / 供需缺口 | BAPI_MATERIAL_STOCK_REQ_LIST | 物料、工厂 | MD04 口径,含计划要素;是快照不是承诺;工厂级 WB 汇总 + EXPORTING 的 MRP_STOCK_DETAIL(库存分类)均回传 |
| 各库存地点的账面数量 / 批次库存 | RFC_READ_TABLE(受控兜底) | 表名、物料、工厂 | 直读 MARD/MCHB 当前值;不走转换出口;必须标注"直读表口径" |
| 物料主数据描述与工厂属性 | BAPI_MATERIAL_GET_DETAIL | 物料、工厂 | MATERIAL_GENERAL_DATA 含物料描述、基本单位等;**不含库存数量**(MATERIALPLANTDATA 仅 PUR_GROUP/ISSUE_UNIT) |
| 最近的收发货明细 | BAPI_GOODSMVT_GETITEMS | MATERIAL_RA + PLANT_RA + **PSTNG_DATE_RA** | 范围表入参(SIGN/OPTION/LOW/HIGH);凭证行级;无日期区间会超时;空结果看 RETURN M7/842 |
| 按描述找物料号 | BAPI_MATERIAL_GETLIST | MATERIALSHORTDESCSEL + PLANTSELECTION | 选择表入参(descr_low / plant_low,通配 I/CP);仅用于消歧,**不作为数据结论** |

> 表中"必填筛选"是业务要素;报文 JSON 键名以 `describe` 骨架为准,catalog 的 required 与网关契约一致。

## 受控兜底:RFC_READ_TABLE(最后手段,不是首选)

仅当以下**全部**成立才允许调用:

1. 上表场景函数无法回答(未注册、返回空体、字段不覆盖),并已向用户说明原因;
2. 目标表在 `catalog.json` 的 `table_allowlist` 内(当前:MARD/MCHB/MARC/MARM/MSKA/MKOL/MSKU);扩表需改 catalog 并经用户确认;
3. 报文满足:FIELDS 显式列字段(禁止 SELECT *)、OPTIONS 必含主键过滤(白名单表现均需 MATNR+WERKS,仅 MARM 只要 MATNR;特殊库存再按供应商/客户/销售单行收窄)、ROWCOUNT ≤ 100、每个 OPTIONS 行 ≤ 72 字符。

CLI 本地拦截违规,退出码 2:`TABLE_NOT_ALLOWED` / `EMPTY_FIELD_LIST` / `MISSING_FILTER` / `MISSING_KEY_FILTER` / `OPTION_LINE_TOO_LONG` / `ROWCOUNT_EXCEEDS_CAP`。本地守卫是**操作纪律,不是安全边界**——真正的闸门是网关注册表和 S_TABU_DIS 授权。

直读表口径与陷阱:

- 读到的是数据库当前值,不经过 BAPI 业务校验与转换出口;叙事必须写明"直读 \<表名\>"与时点,仍然**不得**与 ATP/MD04 数字相加。
- S/4HANA 的 `MATNR` 为 40 位:非数字物料号**左对齐、尾部补空格**,等值条件直接写短码;查不到时先 `MARA` 上 `MATNR LIKE '%<物料号>'` 确认真实内部键,不要猜前导零位数。
- 行缓冲 512 字节(TAB512),字段总长超限服务端抛 DATA_BUFFER_EXCEEDED → 减少 FIELDS 分次读。
- 结果在 DATA 表的 WA 字符串里,按 DELIMITER 拆分;数量是压缩 DEC,需自行转数。
- 表/字段语义、库存类别、实测报文见 `references/direct-table-reads.md`。

## 叙事输出格式

```
<结论句:数量 + 单位 + 工厂 + 时点>
<口径句:这个数字是什么口径、不包含什么>
<异常句:RETURN 里的 W/E 消息,有则原文引用>
调用事实:<FUNC> · <关键入参> · <返回行数/是否截断>
```

硬规则:
- 返回为空就说空,**不得**用常识补数字。
- 截断时必须告知"仅前 N 行",不得对全量做合计或趋势判断。
- ATP 与账面库存不得混用或相加。用户问"能不能发货"走 ATP;问"仓里有多少"走账面。
- `RETURN` 里的 MESSAGE 只给人读,不拿它做程序判定。
- **取不到 ATP 确认量时的降级**:发生两种情况之一——接口返回 400/500(最多重试确认一次),或返回 200 但 `DIALOGFLAG=N`(该检查组+规则在 T441V 未配置、检查被跳过;此时 WMDVEX-COM_QTY 只是需求量回显),然后:
  - 需求量 > 非限制在库(MARD/MD04 WB)→ 可下保守结论"现在不能足额发",并写明真实 ATP ≤ 在库、ATP 确认量取不到;
  - 需求量 ≤ 在库 → **不得**承诺可发(在库可能已被预留/交货占用),只能回答在库数并建议 GUI 用 CO09 按检查规则复核;
  - 任何情况下不得把账面/MD04 数字或"检查被跳过时的回显量"冒充 ATP 确认量。

## 凭据配置引导(仅在退出码 3 时触发)

CLI 返回 `{"error":"NO_CREDENTIAL"}`、`{"error":"AUTH_REQUIRED"}` 或 `{"error":"CONFIG_MISSING"}` 时,**停止重试**,向用户输出:

> 网关取不到可用凭据。口令不写在文件里,存在你本机的操作系统凭据库,请自己跑一次:
> ```
> python3 scripts/sap_stock.py credentials set
> python3 scripts/sap_stock.py doctor
> ```
> 它会用 `getpass` 让你输入口令(不回显、不进命令行、不进日志)。如果 `doctor` 报没有可用后端,把它的输出发我,我看是 WSL 还是 headless 的问题。账号一人一份,不共用服务账号;非机密的 host / client / user 填在 `connection.json` 里。

**绝不**索要口令,也不代替用户执行 `credentials set`。用户若把口令直接发在对话里:提醒他这条消息已经泄露、应去 SAP 侧改密码,然后改用 `credentials set` 录入,并**不要重复该口令**。

## 其他退出码

正常结果走 stdout,错误 JSON 走 stderr。

| 码 | 含义 | 动作 |
| --- | --- | --- |
| 0 | 成功 | 继续叙事 |
| 2 | 参数错误(MISSING_PARAM / TYPE_MISMATCH / UNKNOWN_PARAM,或兜底守卫各码) | 重跑 describe 后修正报文,最多重试一次 |
| 3 | 认证/凭据问题 | 进入凭据配置引导,不重试 |
| 4 | 函数未注册或未激活(404) | 告知用户需在 `ZTIF_GENERAL_CON` 注册,不改走其他函数 |
| 5 | 超时/行数过大 | 要求用户收窄筛选条件后重试 |
