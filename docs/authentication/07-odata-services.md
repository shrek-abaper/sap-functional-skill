# 07 OData 服务的认证

本章澄清一个常见疑问：手册中的认证方式并非只适用于 SICF 自定义 REST 端点——它们是 ICM/ICF **传输层**机制，对所有走 HTTP 的 SAP 服务成立，**OData 同样适用**。本章同时说明 OData 特有的正规 OAuth 路线与应用层注意点。

## 1. 为什么传输层方式对 OData 全部成立

SAP OData 服务本身就是注册在 SICF 树上的节点：

```text
OData V2（SAP Gateway / IWFND）：
  /sap/opu/odata/<namespace>/<service>;sv/<version>/...
OData V4：
  /sap/opu/odata4/sap/<service>/srvd/sap/<...>/0001/
Fiori 所依赖的 OData 调用同属该树。
```

请求链路与 REST2RFC 完全相同：

```text
客户端 ── HTTP(S) ──▶ ICM（端口/TLS） ──▶ ICF 登录栈 ──▶ OData runtime（handler）
                          ▲ 认证发生在这里，与"后面是哪种 handler"无关
```

因此在 SICF 节点（或父节点）上配置的 Basic / SPNEGO / X.509 / SAML 登录，**不需要区分服务类型**即对 OData 生效。

## 2. 各方式适用性总表

| 方式 | OData | 配置位置 | 备注 |
|---|---|---|---|
| Basic | 适用 | SICF 登录过程 | 最简单，适合开发/过渡 |
| SPNEGO | 适用 | SICF + `SPNEGO` 向导（见 [02 章](02-spnego.md)） | 域内浏览器/程序零提示 |
| X.509 | 适用 | `icm/HTTPS/verify_client` + SICF + `CERTSMAP`（[03 章](03-x509-client-cert.md)） | 强合规 |
| SAML 2.0 | 适用 | 事务码 `SAML2` + SICF | Fiori/浏览器 SSO 常见 |
| **SAP 原生 OAuth 2.0** | **适用（正规路线）** | 事务码 `SOAUTH`（见 §3） | OData 在其资源覆盖范围内 |
| OIDC 直连（JWT 进 handler） | 默认不适用 | —— | OData 是标准 handler，无法写入校验 |
| 边界模式（OIDC + KCD） | 适用 | 见 [05 章](05-edge-patterns.md) | 外网/统一入口 |

> 对比记忆：ADT（`/sap/bc/adt`）与 OData 都是标准 handler，都**不能**把自研 JWT 校验塞进 handler；区别在于 **OData 能被 SAP 原生 OAuth 2.0 框架保护，ADT 不能**。

## 3. SAP 原生 OAuth 2.0 保护 OData（操作步骤）

**【标准实践】** AS ABAP 自带 OAuth 2.0 AS/RS 框架；SAP Gateway 发布的 OData 服务可注册为其受保护资源。具体界面随 NetWeaver 7.40/7.50 SP 有差异，标注【待验证】，实施时在目标系统逐屏核对。

### 3.1 一次性配置

1. **OAuth 2.0 客户端注册**（`SOAUTH`）：
   - 为调用方创建 OAuth client（机密客户端有 secret；public 客户端无）；
   - 记录 client ID；令牌端点固定为 `/sap/bc/sec/oauth2/token`。
2. **资源（scope）绑定**：
   - 将已发布的 OData 服务分配 OAuth scope（服务需已通过 `IWFND/MAINT_SERVICE` 注册激活）；
   - scope 与服务/操作关联，运行时 IWFND 据此做授权检查。
3. **用户映射 / 信任**：
   - 按人访问时，令牌最终对应 SU01 用户（见 §3.2 各 grant）；
   - SAML Bearer 联邦需先配好 `SAML2` 与企业 IdP 的信任。
4. **SICF**：令牌端点节点 `/sap/bc/sec/oauth2` 已激活；建议仅 HTTPS 暴露。

### 3.2 可用 grant 与典型用途

| Grant | 身份 | 典型场景 |
|---|---|---|
| `client_credentials` | 技术用户 | 服务到服务、CI、无人值守 |
| SAML 2.0 Bearer Assertion | 个人（IdP 联邦） | 企业 IdP 用户调 OData 的标准组合 |
| Authorization Code / Refresh Token | 个人 | 有用户授权环节的应用 |

### 3.3 客户端调用骨架

```python
import requests

# ① 取令牌（以 client_credentials 为例）
tok = requests.post(
    "https://<sap-host>:<port>/sap/bc/sec/oauth2/token",
    data={
        "grant_type": "client_credentials",
        "client_id": "<client-id>",
        "client_secret": "<client-secret-from-vault>",
        "scope": "<odata-scope>",
    },
    timeout=30,
)
tok.raise_for_status()
access_token = tok.json()["access_token"]

# ② 携带 Bearer 调用 OData
resp = requests.get(
    "https://<sap-host>:<port>/sap/opu/odata/<namespace>/<service>/<EntitySet>",
    params={"$top": 50, "$filter": "Werks eq '5260'", "$format": "json"},
    headers={"Authorization": f"Bearer {access_token}",
             "Accept": "application/json"},
    timeout=60,
)
resp.raise_for_status()
```

个人联邦场景把 ① 换成"SAML 断言 → SAML2 Bearer grant"；对外仍统一是 `Bearer` 头。

## 4. OData 应用层注意点（与认证正交）

### 4.1 CSRF 防护（写操作必须）

```text
① GET 任意服务资源，头：x-csrf-token: fetch
② 响应取 x-csrf-token + Set-Cookie（会话/路由 cookie）
③ POST/PUT/DELETE/PATCH 回带同一 token 与 cookie
```

切换 Basic/SPNEGO/OAuth 不改变这套流程；cookie 与认证方式正交。`403 + CSRF` 时重新 fetch 一次，与 [06 章 §1](06-client-patterns.md) 的重试原则一致。

### 4.2 `$batch` 请求

- 一个 multipart batch 内混读改写：V2 通常仍要求**外层 HTTP 请求**带 CSRF 头；
- 认证只在外层请求头出现**一次**，不要在每个 changeset 内重复凭据；
- batch 整体一个授权上下文，无法在批内切换用户。

### 4.3 其他运行时差异

- OData V4 的节点结构、错误格式与 V2 不同，但认证仍在同一 ICF 层；
- 深度展开（`$expand`）、大结果集只影响性能/超时，与认证无关，但长驻 AI 进程同样应做结果截断。

## 5. 云端与 API 管理场景

**【标准实践】**（具体产品能力随版本/租户【待验证】）：

- **SAP API Management / SAP Integration Suite**：在边界校验 OIDC/JWT，再向 SAP 做 **principal propagation**（用户主体传递），下游仍按人授权——与 [05 章](05-edge-patterns.md) 边界模式同构。
- **S/4HANA Cloud（公有云）**：通信场景使用通信用户/通信场景（technical users）或经 SAP Cloud Identity Services 的联邦；人对系统访问走业务用户与 IdP，认证模型与本手册一致但配置入口不同。
- **SAP Cloud Connector**：常用于云到本地 SAP 的 principal propagation（承载短期用户证书/主体），不是简单的 Basic 隧道。

## 6. 选型建议（OData 项目）

| 场景 | 推荐 |
|---|---|
| 开发调试、内网快速打通 | Basic |
| AD 域内用户/浏览器 SSO | SPNEGO（或 SAML） |
| 服务到服务 / CI | SAP OAuth `client_credentials` |
| 企业 IdP 用户程序化访问 | SAML2 Bearer 联邦换令牌；或边界 OIDC + KCD |
| 外网/混合终端/统一入口 | 边界模式（[05 章](05-edge-patterns.md)） |
| 强合规/智能卡 | X.509（[03 章](03-x509-client-cert.md)） |

## 7. 非 HTTP 通道的边界（避免误用）

本章及手册全部方式只覆盖 **HTTP(S) 类通道**。对非 HTTP 通道不适用：

- **JCo / RFC SDK**（如本仓库 `sap-sto-create` 技能）：SSO 的等价物是 **SNC**（Kerberos/X.509 通过 SNC 封装），是独立机制；
- 消息队列、IDoc 文件传输等也不走 ICF 登录栈。

需要时另立 SNC 主题文档，不要把 HTTP 的认证配置直接套到 RFC 连接上。
