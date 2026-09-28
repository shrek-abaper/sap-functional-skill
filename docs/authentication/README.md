# SAP↔AI 项目认证方式参考手册

本手册面向所有需要让外部程序（AI Agent、CLI、集成服务）通过 HTTP 调用 SAP 的项目，提供认证方式的**选型决策**与**操作级落地方案**。首次编写于库存可用性技能（`skills/sap-stock-availability`）的认证改造探讨，后续任何 SAP↔AI 对接项目均应以本手册为参考。

## 什么时候查这本手册

- 新设计一个 SAP HTTP 接口对接，不知道该让用户怎么登录；
- 业务用户反馈"配密码太麻烦"，想引入 SSO；
- 自研 Z handler 想接受企业 IdP 的令牌；
- 标准 SAP 服务（如 ADT）前需要加边界网关；
- CI/CD、定时任务需要非交互认证。

## 事实分级说明

编写时在线查证渠道受限，且手册内容必须对实施负责。所有关键事实按三级标注，随项目实测持续升级：

- **【已验证】**：在本仓库环境（库存技能 REST2RFC 网关）实测过的链路；
- **【标准实践】**：SAP/行业标准机制，附官方文档出处，可放心采用；
- **【待验证】**：依赖 SAP 版本、SP 或企业基线的细节，实施前必须在目标系统确认。

## 快速选型：决策树

```text
调用方是什么程序？
├─ CI/CD、无人值守定时任务
│    └─ 首选独立技术账号 + 环境变量注入（Basic）；
│       如企业支持，用工作负载联邦身份（OIDC client_credentials / 联邦令牌）
│       → 见 01、04、06 章
│
├─ 人：业务用户（查询/只读为主）
│    ├─ 用户电脑均加入 AD 域、内网直连 SAP
│    │    └─ 首选 SPNEGO（零配置、无感知）→ 02 章
│    ├─ 有企业 IdP（Entra ID / AD FS / Keycloak），用户环境混杂或外网访问
│    │    └─ 首选 OIDC（一次浏览器登录）→ 04 章
│    └─ 两者都没有
│         └─ Basic + 友好 login 封装过渡 → 01 章
│
└─ 人：开发者/管理员（含写操作，如 ADT）
     ├─ AD 域内机器 → SPNEGO（02 章）；保留 Basic 兜底
     ├─ 非域/WSL → Basic 或 OIDC
     └─ 目标是标准 SAP handler 且只有 IdP → 边界转换（OIDC + KCD）→ 05 章
```

补充判断：

1. **先问终端环境，再选技术**。同一套 SAP 后端，域内 Windows、WSL、外网笔记本的最优方案不同。
2. **自研 Z handler 与 SAP 标准 handler 要分开讨论**。前者可以把令牌校验写进 handler（04 章直连可行）；后者动不了，必须在边界做转换（05 章）。
3. **写操作场景对身份真实性要求更高**。任何让多个人共用一个账号的方案，都会使授权对象和审计日志失效，需合规显式批准。

## 全方式对比矩阵

| 方式 | 用户侧操作 | SAP 侧改动 | 密钥/密码是否落客户端 | 按人授权与审计 | 典型适用 |
|---|---|---|---|---|---|
| HTTP Basic | 每人配置一次密码 | 无（SICF 默认） | 是（应存 OS 凭据库） | 是 | 过渡方案、开发者、CI |
| Kerberos/SPNEGO | 域登录后无感知 | SPNEGO 配置，无代码 | 否（票据，可续期） | 是 | AD 域内业务用户 |
| X.509 客户端证书 | IT 签发后基本无感 | STRUST + ICM + 映射 | 证书+私钥（可硬件承载） | 是 | 有企业 PKI、强合规 |
| OIDC（PKCE/设备码） | 一次浏览器 SSO | 自研 handler 验 JWT | 短期令牌+刷新令牌 | 是（映射表） | 现代 IdP、外网、混合环境 |
| 边界代理（OIDC→KCD） | 一次浏览器 SSO | SICF 启用 SPNEGO + 域委派 | 否 | 是 | 标准 SAP handler + IdP |
| 共享技术账号 | 无配置 | 最小 | 否（服务端保管） | **否** | 仅极窄只读+网络强隔离 |

## 各章导航

| 章节 | 内容 |
|---|---|
| [01 HTTP Basic Auth](01-basic-auth.md) | 原理、当前库存技能实现剖析、凭据库体系、优缺点、过渡改进 |
| [02 Kerberos/SPNEGO](02-spnego.md) | AD/Kerberos 原理、SPN 与 keytab、`SPNEGO` 向导、客户端骨架 |
| [03 X.509 客户端证书](03-x509-client-cert.md) | PKI 前提、ICM/STRUST、`CERTSMAP` 映射、证书库坑 |
| [04 OIDC/OAuth2](04-oidc-oauth2.md) | PKCE 浏览器流、设备码流、JWKS 验签、用户映射与身份切换 |
| [05 边界模式](05-edge-patterns.md) | oauth2-proxy、Kerberos 约束委派（KCD）、过渡信任的边界 |
| [06 客户端通用模式](06-client-patterns.md) | 认证策略抽象、令牌存储、fail-closed、CI 路径、退出码协议、MCP/stdio AI 工具集成约束 |
| [07 OData 服务的认证](07-odata-services.md) | ICF 传输层通用性、SAP 原生 OAuth 2.0 保护 OData（`SOAUTH`/scope/Bearer）、CSRF/`$batch`、云端 principal propagation |

## 附：SAML 2.0 与 SAP 原生 OAuth 2.0（简述）

这两种方式在特定场景成立，但不作为本手册 CLI 场景的主推，了解边界即可。

### SAML 2.0

- **【标准实践】** AS ABAP 可作为 SAML 2.0 Service Provider（事务码 `SAML2`），与企业 IdP（AD FS、Entra ID via SAML）做浏览器 SSO，断言通过浏览器重定向 POST 传递。
- **为什么不适合 CLI/AI 场景**：SAML Web SSO 依赖浏览器和用户交互跳转，原生程序无法直接发起；SAML 断言通常也不是发给 API 资源服务器的长期调用凭证。
- **成立的用法**：SAP Fiori / Web GUI 等浏览器应用的统一登录；或以 **SAML 2.0 Bearer Assertion** 作为 OAuth2 授权 grant 换取令牌（见 04 章扩展），属于高级集成模式。

### SAP 原生 OAuth 2.0 AS

- **【标准实践】** AS ABAP 自带 OAuth 2.0 Authorization Server 与 Resource Server 框架（事务码 `SOAUTH`，令牌端点 `/sap/bc/sec/oauth2/token`），支持 scope、client 注册、SAML Bearer / client credentials 等 grant。
- **能力边界（关键）**：能被其保护的资源需要按 SAP 框架注册——**SAP Gateway 发布的 OData 服务在覆盖范围内（详见 [07 章](07-odata-services.md)）；但 ADT（`/sap/bc/adt`）等标准 SICF 应用不在**，不能简单配置后就让 ADT 接受 Bearer 令牌。
- **建议**：新项目优先选通用 OIDC IdP + 自研 handler / 边界模式；仅当资源恰好是 SAP OAuth 框架原生支持的服务类型时，再评估 `SOAUTH` 路线。

## 使用与维护

- 落地新认证方式后，回填本章对应文件的【已验证】标记与实测截图/命令输出摘要；
- 发现手册与实际系统不符，以实测为准并立即修正，不要让错误配置扩散到下一个项目；
- 手册不含任何真实口令、主机凭据，示例一律使用占位符。
