# sap-stock-availability

只读的 SAP 库存与物料可用性场景化 Skill。通过 REST2RFC 动态网关调用白名单内的 BAPI,不建服务、不起常驻进程、不写 MCP Server。

## 状态

**2026-09-20 已在真实 S/4HANA(client 800)首次端到端跑通**:`doctor`、`describe`(经 `RFC_METADATA_GET`)、`call` 均实测。

已验证:

- `BAPI_MATERIAL_STOCK_REQ_LIST`:MD04 口径,工厂级 WB 汇总行可用;EXPORTING 的 `MRP_STOCK_DETAIL`(非限制/质检/冻结等库存分类)、`MRP_LIST`、`RETURN` 均回传。
- `BAPI_MATERIAL_GET_DETAIL`:EXPORTING 结构回传,`MATERIAL_GENERAL_DATA` 含物料描述、基本单位等(不含库存数量;`MATERIALPLANTDATA` 仅 PUR_GROUP/ISSUE_UNIT)。
- `BAPI_MATERIAL_AVAILABILITY`:网关调用 200,`AV_QTY_PLT`/`WMDVEX`/`RETURN` 正常回传;真实 ATP 以 OPJJ(T441V)检查控制为准,`DIALOGFLAG=N` 表示该检查组+规则未配置、检查被跳过。
- `RFC_READ_TABLE`:作为受控兜底,MARD/MCHB/MSKA/MKOL/MSKU 字段结构全部实测,CLI 有表白名单与主键过滤守卫。
- `catalog.json` 的 `required` 已经 `describe` 实参树校对。

遗留:

1. 非 200 响应不回写 body,binder 的 400 错误明细被丢弃,客户端只能看到空 400(网关 `sap-rest2rfc-gateway` 侧;错误明细可在 `ZTIF_GENERAL_LOG` 查到)。
2. 网关仓库自带的 `rest2rfc_meta.py` 与现行契约脱节,本 Skill 的 vendor 版带三处适配补丁(见下),待上游化;该工具会把 MATNR18 这类数据元素误标为 structure。
3. 业务配置待补:实测检查组 KP 在 T441V 中无任何检查规则行,相关物料 ATP 被跳过,需 OPJJ 补配置后才有真实承诺量。

## 安装

```bash
pip install -r scripts/requirements.txt
# 可选凭据后端:keyring(SecretService/DPAPI/Keychain);file 加密后端额外需要 cryptography
```

补两个 vendored 文件:

- `scripts/rest2rfc_meta.py` — 已从 `sap-rest2rfc-gateway` 仓库 vendor,`describe` 依赖它。网关侧需注册 `RFC_METADATA_GET`(按 FM 名注册,不是 SYS_* IFCODE);`DDIF_FIELDINFO_GET` / `DOCU_READ` 未注册时客户端优雅降级。vendor 版含三处契约适配补丁(见下「vendor 补丁」),待上游化。
- `scripts/sap_credentials.py` — 包里带的是**API 兼容的临时实现**。目标是换成 `sap-adt-cli` 里那套凭据层,保持 `Credentials` / `load_credentials` / `select_keystore` / `probe_keystores` 四个导出。如果那边名字不同,**改这个文件,不改 `sap_stock.py`**。

## 首次配置

1. `cp connection.example.json connection.json` 并 `chmod 600 connection.json`,填三个必填项:`host`、`client`、`user`(本人账号,不填共享服务账号)。`connection.json` 含内网地址与个人账号,已被 `.gitignore` 忽略,不会提交。
2. `python3 scripts/sap_stock.py credentials set` — `getpass` 录入口令,进操作系统凭据库。
3. `python3 scripts/sap_stock.py doctor` — 报告选中的凭据后端、每个后端不可用的原因、TLS 状态与网关可达性。

可选项:`path`(默认 `/sap/bc/rest2rfc`)、`ca_bundle`、`verify`(默认 `false`)、`timeout`(默认 60)。

CI / 容器里可不建 `connection.json`,全用环境变量:`REST2RFC_HOST`、`REST2RFC_CLIENT`、`REST2RFC_USER`、`REST2RFC_PASSWORD`(env 后端只读,专供此场景)、`REST2RFC_PATH`、`REST2RFC_VERIFY`、`REST2RFC_CA_BUNDLE`、`REST2RFC_TIMEOUT`。

## 测试

```bash
python3 -m pytest tests/        # 离线:兜底守卫、退出码、stderr 错误流,不需要 SAP 连接
```

路由与口径的评测问答在 `evals/golden-set.yaml`(7 条:账面/ATP/MD04/日期追问/写操作拒绝/跨域拒绝/物料消歧)。

## 退出码:有意偏离通用 CLI 约定

skill-dev-standard 的通用约定是 1=配置/2=网络/3=权限/4=参数,本 Skill 使用面向 Agent
处置动作的领域协议:0=成功、2=报文参数(可修一次重试)、3=凭据(转录入引导)、
4=网关注册缺失、5=超时/行数过大(应收窄筛选)、1=其他。理由:消费方是 Agent,
码值直接决定下一步动作(录口令 vs 收窄日期 vs 申请网关注册),通用约定表达不了
"404 = 去 ZTIF_GENERAL_CON 注册"这一处置。错误信封为 `{ok:false,error,hint}`,
错误 JSON 走 stderr。变更此协议属 breaking change。

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
├── SKILL.md                  # Agent 入口:场景路由 + 调用纪律(含 frontmatter 元数据)
├── catalog.json              # 场景白名单(唯一可调函数清单 + 兜底表白名单)
├── connection.example.json   # 连接配置模板(从它拷贝生成 connection.json)
├── connection.json           # 本地实际配置(600),gitignore 忽略,不提交
├── scripts/
│   ├── sap_stock.py          # CLI:doctor / credentials / list / describe / call
│   ├── sap_credentials.py    # KeyStore 层(待换成 sap-adt-cli vendored 版)
│   ├── rest2rfc_meta.py      # vendored + 三处契约补丁(见上)
│   └── requirements.txt      # 运行依赖(requests;keyring/cryptography 可选)
├── references/
│   ├── direct-table-reads.md # RFC_READ_TABLE 受控兜底参考(表白名单/口径/陷阱)
│   └── payloads/             # 核对过的 request/response 示例
├── tests/
│   └── test_cli.py           # 离线测试:兜底守卫/退出码/stderr(pytest,免 SAP 连接)
├── evals/
│   └── golden-set.yaml       # 路由与口径评测问答(7 条)
└── .gitignore
```
