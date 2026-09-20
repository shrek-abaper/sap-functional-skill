# 受控直读表兜底:RFC_READ_TABLE

本文件是 SKILL.md「受控兜底」一节的展开。所有内容基于 2026-09-20 对一台
S/4HANA 系统(client 800,动态 REST2RFC 网关)的实测,不是照抄 SAP 文档。

## 1. 它是什么,什么时候才允许用

`RFC_READ_TABLE` 是 SAP 自带的通用读表函数。它不理解业务,只做一件事:
把任意透明表/兼容视图的行按 WHERE 条件读出来,拼成字符串返回。

**它是最后手段,不是首选。** 允许使用的前提(SKILL.md 已固化):

1. 场景白名单函数无法回答——未注册、返回体为空、或返回字段不覆盖问题;
2. 已经向用户说明为什么要落到直读表;
3. 目标表在 `catalog.json` 的 `table_allowlist` 内;
4. 报文满足主键过滤、显式 FIELDS、ROWCOUNT ≤ 100、OPTIONS 行 ≤ 72 字符。

CLI 在本地做这四条的机器校验(`guard_table_read`)。注意定位:

> 本地守卫是**操作纪律**,不是安全边界。真正的闸门是网关的注册表
> (`ZTIF_GENERAL_CON`)和 SAP 服务端的 S_TABU_DIS / S_TABU_NAM 授权。

因此绝不能因为"客户端会拦"就认为注册裸 `RFC_READ_TABLE` 是零成本的:
它能读到该账号表授权内的一切,绕过 BAPI 内嵌的业务授权对象,审计上是
SoD 风险点。受控环境之外,应优先用服务端硬编码表名的窄包装函数替代。

## 2. 接口契约(实测)

IMPORTING:

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `QUERY_TABLE` | 是 | 表名,大写 |
| `DELIMITER` | 否 | 字段分隔符,建议 `;` |
| `ROWCOUNT` | 否 | 最大行数;CLI 缺省注入 100,超过上限拒绝 |
| `ROWSKIPS` | 否 | 跳过行数,分页用 |
| `NO_DATA` | 否 | `X` = 只返回 FIELDS 结构不取数 |

TABLES:

| 参数 | 方向 | 行类型 | 说明 |
| --- | --- | --- | --- |
| `OPTIONS` | 入 | RFC_DB_OPT | WHERE 子句,每行 `TEXT` 最多 **72** 字符,可多行拼接,**不带 `WHERE` 关键字** |
| `FIELDS` | 入/出 | RFC_DB_FLD | 入参填 `FIELDNAME`;返回时补 OFFSET/LENGTH/TYPE/FIELDTEXT |
| `DATA` | 出 | TAB512 | 每行一个 `WA`,定长拼接或按 DELIMITER 分隔,行宽上限 **512** 字节 |

EXPORTING 的 `ET_DATA` 是新版结构型参数——当前动态网关只回传 TABLES 参数,
导出结构会丢失,因此取数只能靠 `DATA` 表。

## 3. 表白名单与语义

| 表 | 主键(逻辑) | 回答什么 | 关键库存字段(实测) |
| --- | --- | --- | --- |
| `MARD` | MATNR/WERKS/LGORT | 工厂 + 库存地点的账面库存(非批次) | LABST、UMLME、INSME、EINME、SPEME、RETME |
| `MCHB` | MATNR/WERKS/LGORT/CHARG | 批次库存 | CLABS、CUMLM、CINSM、CEINM、CSPEM、CRETM |
| `MARC` | MATNR/WERKS | 工厂段主数据 + 在途 | TRAME(在途)、DISPO、DISMM 等 |
| `MARM` | MATNR/MEINH | 计量单位;基本单位行 UMREZ=UMREN | MEINH、UMREZ、UMREN |
| `MSKA` | MATNR/WERKS/LGORT/VBELN/POSNR | 销售订单库存(特殊库存 E) | KALAB、KAINS、KASPE、KAEIN |
| `MKOL` | MATNR/WERKS/LGORT/LIFNR | 供应商寄售库存(特殊库存 K) | SLABS、SINSM、SSPEM、SEINM |
| `MSKU` | MATNR/WERKS/KUNNR | 客户寄售库存(特殊库存 W) | KULAB、KUINS、KUEIN、KUUML |

库存类别字段含义(MARD 行,其余表按前缀平移):

| MARD | MCHB(C) | MSKA(K) | MKOL(S) | MSKU(KU) | 含义 |
| --- | --- | --- | --- | --- | --- |
| LABST | CLABS | KALAB | SLABS | KULAB | 非限制使用 |
| UMLME | CUMLM | — | — | KUUML | 转储中/工厂间转移 |
| INSME | CINSM | KAINS | SINSM | KUINS | 质量检验中 |
| EINME | CEINM | KAEIN | SEINM | KUEIN | 限制批次 |
| SPEME | CSPEM | KASPE | SSPEM | — | 冻结 |
| RETME | CRETM | — | — | — | 冻结退货 |

字段名不是简单换前缀(实测如此,不要凭记忆拼):供应商寄售是
`S` 前缀(SLABS 不是 KLABS),客户寄售是 `KU` 前缀(KULAB),
销售订单库存没有 RETME 对应字段。

### 3.1 特殊库存怎么收窄条件

- 批次 MCHB:加 `CHARG = '<批次>'`;要看工厂内全部批次就只过滤
  MATNR/WERKS,ROWCOUNT 给足但不超过 100。
- 销售订单库存 MSKA:用 `VBELN = '<销售订单>' AND POSNR = '<行号>'`;
  POSNR 是 NUMC,值形如 `000010`。
- 供应商寄售 MKOL:用 `LIFNR = '<供应商内部编号>'`;供应商号走 ALPHA
  转换出口,直读表必须给前导零内部格式。只问"该库存地点寄售总量"
  可直接用 MARD 的汇总字段 KLABS/KINSM/KEINM/KSPEM,不必按供应商展开。
- 客户寄售 MSKU:本版系统该表含 WERKS 字段,WHERE 仍带 MATNR/WERKS,
  再按 `KUNNR`(同样前导零)收窄。

### 3.2 前期库存与 CWM 并行数量

每张库存表还带一组"上一期间"字段(MARD 的 VMLAB/VMINS 等,MCHB 的
CVMLA/CVMIN 等),查"上期结存"才用,日常"现在有多少"不要取错列。
启用了 Catch Weight Management 的系统另有 `/CWM/` 命名空间的并行数量
字段(如 `/CWM/CLABS`),那是并行计量单位下的数量,叙事时必须注明单位
口径;不确定业务是否启用 CWM 时不要 SELECT 这些字段。

口径提醒:这些是表中当前值,**不扣预留、不含在途承诺、不做 ATP 运算**。
MARD 汇总行在 MD04 里显示为 WB 要素,实测两者数字一致时可互相印证,
但叙事时仍要写清是"直读 MARD",不要简称"库存"后与 ATP 混用。

## 4. S/4HANA 物料号陷阱(实测踩坑)

S/4HANA 扩展物料号 `MATNR` 长度为 **40**。实测系统上:

- 非数字物料号(如 `P0274635AB`)**左对齐、尾部补空格**存储;
- `RFC_READ_TABLE` **不走转换出口**,BAPI 能吃的外部格式它不认识;
- 等值条件写短码即可,Open SQL 自动补尾空格:
  `MATNR = 'P0274635AB'`;
- 按 EPC 习惯补前导零(18 位、40 位)都查不到,返回 0 行但不报错。

不确定内部格式时,先去 MARA 确认真实键:

```text
OPTIONS: MATNR LIKE '%P0274635AB'
FIELDS : MATNR, MTART, MATKL
```

数字物料号才是前导零规则;拿不准一律先 MARA 确认,不要猜补零位数。

## 5. 实测报文(P0274635AB / 工厂 5260)

请求:

```json
{
  "query_table": "MARD",
  "delimiter": ";",
  "fields": [
    {"fieldname": "MATNR"}, {"fieldname": "WERKS"},
    {"fieldname": "LGORT"}, {"fieldname": "LABST"},
    {"fieldname": "UMLME"}, {"fieldname": "INSME"},
    {"fieldname": "EINME"}, {"fieldname": "SPEME"},
    {"fieldname": "RETME"}
  ],
  "options": [{"text": "MATNR = 'P0274635AB' AND WERKS = '5260'"}]
}
```

返回 DATA 表一行(分隔后):

| MATNR | WERKS | LGORT | LABST | UMLME | INSME | EINME | SPEME | RETME |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P0274635AB | 5260 | 0001 | 59.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

基本单位取 MARM:`MEINH = EA, UMREZ = 1, UMREN = 1` 即基本单位行。
同物料 MD04(WB 要素)返回 59,与账面一致,交叉验证通过。

结论叙事样例:

> P0274635AB 在 5260/0001 的非限制账面库存为 59 EA,质检/冻结/限制均为 0
> (直读 MARD,2026-09-20 时点;不扣预留、不含在途)。
> 调用事实:RFC_READ_TABLE · MARD · MATNR+WERKS 过滤 · 1 行。

## 6. 技术限制清单

- **行宽 512**:所选字段长度合计超过 512,服务端抛 DATA_BUFFER_EXCEEDED。
  处理:减少 FIELDS 分两次读,不要删 WHERE。
- **OPTIONS 每行 72 字符**:长条件拆成多行(相邻行自动 AND 拼接),
  每段仍是完整 token,不要在常量中间断开。
- **不能 JOIN、不能聚合**:跨表信息分表读,在叙事层对齐,不要在客户端
  替数据库做"推断式 JOIN"后当成系统结论。
- **无转换出口**:不仅 MATNR,所有带 ALPHA 出口的字段(G/L、客户、
  供应商编号等)都要按内部格式给值。白名单内主要是 MATNR/WERKS/CHARG。
- **客户端是隐式的**:读到的是登录 client(本系统 800)的数据;
  跨 client 表不在白名单内,也不允许尝试。
- **压缩数格式**:QUAN/DEC 字段返回字符串如 `59.000`,按字符串解析转数,
  三位小数,不要用整数接口接收。
- **空结果不报错**:0 行就是 0 行,先怀疑键格式(见第 4 节),不要重试加量。

## 7. 错误对照

| 现象 | 含义 | 处理 |
| --- | --- | --- |
| CLI `TABLE_NOT_ALLOWED`(退 2) | 表不在白名单 | 停止;确属库存域再提 catalog 变更,经用户确认 |
| CLI `MISSING_KEY_FILTER` | WHERE 缺主键字段 | 补 MATNR/WERKS,禁止全表扫描式提问 |
| CLI `ROWCOUNT_EXCEEDS_CAP` | 行数超 100 | 收窄物料/工厂/批次条件 |
| HTTP 500 NOT_AUTHORIZED 类 | 账号缺 S_TABU_DIS/S_TABU_NAM | 告知用户走权限申请,不要换表绕过 |
| HTTP 500 DATA_BUFFER_EXCEEDED | 字段超 512 字节 | 减少 FIELDS |
| HTTP 500 OPTION_NOT_VALID | WHERE 语法/超长/转换问题 | 拆行;核对内部格式 |
| 0 行且确定物料存在 | 键格式不匹配 | MARA 上 LIKE 确认真实内部键 |

## 8. 与其它路由的选择顺序

1. 能不能发货 / ATP → `BAPI_MATERIAL_AVAILABILITY`(当前网关暂不可用,
   等 EXPORTING 绑定修复,不要用 MARD 数字冒充承诺量);
2. 缺料时间线 / MD04 → `BAPI_MATERIAL_STOCK_REQ_LIST`(工厂级快照);
3. 收发货明细 → `BAPI_GOODSMVT_GETITEMS`(必须带日期区间);
4. 库存地点/批次账面数量、特殊库存 → 本兜底(MARD/MCHB/MSKA/MKOL/MSKU);
5. 物料号消歧 → `BAPI_MATERIAL_GETLIST` 或 MARA 只读确认键。

## 9. 调用前自检清单(Agent)

发请求前逐项过:

- [ ] 场景 BAPI 确实无法回答,且已准备好向用户解释原因;
- [ ] 目标表在 `table_allowlist` 内,没有"顺手"读别的表;
- [ ] FIELDS 逐列显式列出,且字段名经 `describe`/`NO_DATA` 实测,不是凭记忆;
- [ ] WHERE 含 MATNR(工厂级表含 WERKS),特殊库存带 LIFNR/KUNNR/VBELN;
- [ ] OPTIONS 每行 ≤ 72 字符,不含 `WHERE` 关键字;
- [ ] ROWCOUNT 省略或 ≤ 100;字段总长 ≤ 512;
- [ ] MATNR 内部格式已确认(不确定先 MARA LIKE);ALPHA 出口编号已补零;
- [ ] 叙事稿里写了"直读 \<表名\>"、时点、不包含项,且没有与 ATP 数字相加。

CLI 守工会机械拦截其中大部分,但清单的意义是让兜底**少发生、可解释**,
而不是学会绕过守卫——例如绝不要为了通过检查在 WHERE 里写恒真主键条件。

## 10. 已知边界与明确不做的事

- 不读跨 client 数据:登录 client 是隐式条件,白名单表均为业务数据表,
  不要尝试任何 client 字段比较。
- 不读主数据以外的敏感表(用户、权限、薪资、财务凭证明细等),
  即使账号表授权允许——那超出本 Skill 的场景边界,应直接拒绝用户。
- 不用直读表结果回答"能不能发货":那是 ATP 的承诺口径,
  账面数字可被预留/计划要素全部占用。
- 不基于单次快照做趋势判断;要趋势就多次读取并在叙事中注明各自时点。
- 不把 DATA-WA 的字符串位置当契约:用 DELIMITER 拆分,
  位置随 FIELDS 选择变化,OFFSET 只用于排错。
- 网关注册表(系统侧)若把 `RFC_READ_TABLE` 开放给更多场景调用方,
  风险归属系统管理员;本 Skill 的本地守卫不构成对他人的保护。
