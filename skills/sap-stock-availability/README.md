# sap-stock-availability

只读的 SAP 库存与物料可用性场景化 Skill。通过 REST2RFC 动态网关调用白名单内的 BAPI,不建服务、不起常驻进程、不写 MCP Server。

## 状态

**2026-09-20 已在真实 S/4HANA(client 800)首次端到端跑通**:`doctor`、`describe`(经 `RFC_METADATA_GET`)、`call` 均实测。

已验证:

- `BAPI_MATERIAL_STOCK_REQ_LIST`:MD04 口径,工厂级 WB 汇总行可用(实测 59 EA 与 MARD 账面一致)。
- `RFC_READ_TABLE`:作为受控兜底,MARD/MCHB/MSKA/MKOL/MSKU 字段结构全部实测,CLI 有表白名单与主键过滤守卫。
- `catalog.json` 的 `required` 已经 `describe` 实参树校对。

遗留(均为网关 `sap-rest2rfc-gateway` 侧问题,不阻塞只读使用):

1. binder 只绑定入参与 TABLES 参数,**EXPORTING 结构/标量不回传**:`BAPI_MATERIAL_GET_DETAIL` 返回空体、`BAPI_MATERIAL_AVAILABILITY` 的 ATP 数量取不到、`MRP_STOCK_DETAIL` 丢失。
2. 非 200 响应不回写 body,binder 的 400 错误明细被丢弃,客户端只能看到空 400。
3. 网关仓库自带的 `rest2rfc_meta.py` 与现行契约脱节,本 Skill 的 vendor 版带三处适配补丁(见下),待上游化。
4. `BAPI_MATERIAL_GET_DETAIL` 的库存路由口径已纠正:BAPIMATDOC 实测仅 PUR_GROUP/ISSUE_UNIT,不含库存数量。

## 安装

```bash
pip install requests keyring            # file 后端额外需要 cryptography
```

补两个 vendored 文件:

- `scripts/rest2rfc_meta.py` — 已从 `sap-rest2rfc-gateway` 仓库 vendor,`describe` 依赖它。网关侧需注册 `RFC_METADATA_GET`(按 FM 名注册,不是 SYS_* IFCODE);`DDIF_FIELDINFO_GET` / `DOCU_READ` 未注册时客户端优雅降级。vendor 版含三处契约适配补丁(见下「vendor 补丁」),待上游化。
- `scripts/sap_credentials.py` — 包里带的是**API 兼容的临时实现**。目标是换成 `sap-adt-cli` 里那套凭据层,保持 `Credentials` / `load_credentials` / `select_keystore` / `probe_keystores` 四个导出。如果那边名字不同,**改这个文件,不改 `sap_stock.py`**。

## 首次配置

1. `cp connection.example.json connection.json`,填三个必填项:`host`、`client`、`user`(本人账号,不填共享服务账号)。`connection.json` 含内网地址与个人账号,已被 `.gitignore` 忽略,不会提交。
2. `python3 scripts/sap_stock.py credentials set` — `getpass` 录入口令,进操作系统凭据库。
3. `python3 scripts/sap_stock.py doctor` — 报告选中的凭据后端、每个后端不可用的原因、TLS 状态与网关可达性。

可选项:`path`(默认 `/sap/bc/rest2rfc`)、`ca_bundle`、`verify`(默认 `false`)、`timeout`(默认 60)。

CI / 容器里可不建 `connection.json`,全用环境变量:`REST2RFC_HOST`、`REST2RFC_CLIENT`、`REST2RFC_USER`、`REST2RFC_PASSWORD`(env 后端只读,专供此场景)、`REST2RFC_PATH`、`REST2RFC_VERIFY`、`REST2RFC_CA_BUNDLE`、`REST2RFC_TIMEOUT`。

## 凭据规则(不可放松)

- 口令只进操作系统凭据库。仓库里只有非机密配置。
- 后端按能力探测选择:`env → keyring → dpapi → pass → file`。不按 `platform.system()` 分支——WSL 返回 `Linux`,但可用的是 Windows DPAPI。
- fail-closed:取不到凭据就报错,永不回落共享账号,永不在非交互环境挂起等输入。
- `Credentials` 覆写 `__repr__` / `__str__`——CLI 工具最高频的泄露路径是异常堆栈。
- 不提供 `credentials export`。
- 凭据键 = `host|client:user`。不用 SID:这是个 HTTP 端点,SID 是程序校验不了的字段。
- 凭据不可跨机器复制(DPAPI 绑 Windows 账户、Keychain 绑 macOS 登录),换机器就重新 `credentials set`。

## TLS

`verify` 默认 `false`——网关多数跑在内网自签证书上,默认 `true` 的真实后果是每个人学会「随手关校验」。填了 `ca_bundle` 就**自动**转为校验,`doctor` 每次把 `tls_verify` 打出来。**面向生产的连接必须配 `ca_bundle`。**

## 只读闸门的四层

1. 网关配置:`ZTIF_GENERAL_CON` 只注册读类函数,`COMMITMODE = N`。
2. SAP 授权:一人一账号,只给对应 `S_RFC` 与业务只读授权。
3. CLI 契约:必填筛选参数、行数上限、截断提示、稳定退出码。
4. `catalog.json`:白名单在本地先拦一道,清单外的函数不出网关。

### 关于 RFC_READ_TABLE(受控兜底)

默认策略仍然是**不注册**通用读表函数——它绕过 BAPI 内嵌的业务授权检查,
是明确的审计风险点。当前受控环境作为例外注册,且必须同时满足:

- 只在场景 BAPI 无法回答时兜底,决策顺序写在 SKILL.md;
- `catalog.json` 的 `table_allowlist` 限定库存域七张表;
- CLI 强制显式 FIELDS、主键 WHERE、ROWCOUNT ≤ 100、OPTIONS 行 ≤ 72 字符;
- 真正的边界仍是网关注册表与 S_TABU 授权,本地守卫只是操作纪律。

向其它环境推广时,首选服务端硬编码表名的窄包装函数,而不是裸 `RFC_READ_TABLE`。

## vendor 补丁(待上游化到 sap-rest2rfc-gateway)

vendor 的 `rest2rfc_meta.py` 相对上游有三处适配:

1. URL 契约由 `?ACTION=SYS_META` 改为 `?RFC=<函数名>`(现行网关按 FM 名查注册表);
2. 元数据请求行字段 `funcname` 改为 `functionname`(实测正确字段名,旧名 400);
3. 新增 `--password-stdin`,口令走 stdin 不进 argv(`ps` 可见)。

## 目录

```txt
sap-stock-availability/
├── SKILL.md                  # Agent 入口:场景四列表 + 调用纪律
├── catalog.json              # 场景白名单(唯一可调函数清单)
├── connection.example.json   # 连接配置模板(从它拷贝生成 connection.json)
├── connection.json           # 本地实际配置,gitignore 忽略,不提交
├── scripts/
│   ├── sap_stock.py          # CLI:doctor / credentials / list / describe / call
│   ├── sap_credentials.py    # KeyStore 层(待换成 sap-adt-cli vendored 版)
│   └── rest2rfc_meta.py      # vendored + 三处契约补丁(见上)
├── references/
│   ├── direct-table-reads.md # RFC_READ_TABLE 受控兜底参考(表白名单/口径/陷阱)
│   └── payloads/             # 核对过的 request/response 示例
└── .gitignore
```
