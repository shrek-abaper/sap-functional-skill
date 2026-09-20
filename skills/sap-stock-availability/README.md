# sap-stock-availability

只读的 SAP 库存与物料可用性场景化 Skill。通过 REST2RFC 动态网关调用白名单内的 BAPI,不建服务、不起常驻进程、不写 MCP Server。

## 状态

**未在真实系统跑过。** 进入生产前必须核实:

1. 五个函数在 `ZTIF_GENERAL_CON` 的注册行(`TASKFM` = 函数名,`ACTFLG` = X,`COMMITMODE` = N)与实际参数名。
2. `BAPI_MATERIAL_AVAILABILITY` 响应字段的实际拼写。
3. 网关 404 / 401 的真实响应体形状(错误码映射依赖它)。
4. `catalog.json` 里的 `required` 字段名需用 `describe` 输出校对后定稿。

## 安装

```bash
pip install requests keyring            # file 后端额外需要 cryptography
```

补两个 vendored 文件:

- `scripts/rest2rfc_meta.py` — 从 `sap-rest2rfc-gateway` 仓库拷过来,`describe` 依赖它。网关侧需注册 `SYS_META` / `SYS_DDIC` / `SYS_DOCU` 三行元数据。
- `scripts/sap_credentials.py` — 包里带的是**API 兼容的临时实现**。目标是换成 `sap-adt-cli` 里那套凭据层,保持 `Credentials` / `load_credentials` / `select_keystore` / `probe_keystores` 四个导出。如果那边名字不同,**改这个文件,不改 `sap_stock.py`**。

## 首次配置

1. 填 `connection.json` 三个必填项:`host`、`client`、`user`(本人账号,不填共享服务账号)。
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

`RFC_READ_TABLE` **绝不注册**。

## 目录

```txt
sap-stock-availability/
├── SKILL.md                  # Agent 入口:场景四列表 + 调用纪律
├── catalog.json              # 场景白名单(唯一可调函数清单)
├── connection.json           # 非机密配置(无口令)
├── scripts/
│   ├── sap_stock.py          # CLI:doctor / credentials / list / describe / call
│   ├── sap_credentials.py    # KeyStore 层(待换成 sap-adt-cli vendored 版)
│   └── rest2rfc_meta.py      # 待补:从网关仓库 vendored
├── references/payloads/      # 核对过的 request/response 示例
└── .gitignore
```
