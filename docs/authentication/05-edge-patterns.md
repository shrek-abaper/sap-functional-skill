# 05 边界模式：反向代理、OIDC 与 Kerberos 约束委派

当目标是 **SAP 标准 handler**（无法加 JWT 校验）或需要在进入 SAP 前统一收敛身份时，把认证转换放到"边界"——API 网关 / 反向代理。本章说明架构模式、Kerberos 约束委派（KCD）的落地，以及过渡信任的安全边界。

## 1. 为什么需要边界转换

| 对接目标 | 能否在 handler 内验 JWT | 方案 |
|---|---|---|
| 自研 Z handler（如 REST2RFC） | 可，直接开发 | [04 章](04-oidc-oauth2.md) 直连 |
| SAP 标准 handler（ADT、标准 ICF 服务） | **不可**（SAP 标准代码不能改，原生 OAuth 框架也不覆盖这些资源） | 边界代理转换 |

边界要同时解决两个问题：

1. **面向调用方**：提供现代认证入口（OIDC、MFA、条件访问）；
2. **面向 SAP**：把身份转换为 SAP 认识的凭证（SPNEGO 票据 / X.509 / 严格约束的 Basic），并保证**按人**。

## 2. 参考架构

```text
                ┌─────────────────────────────────────────────┐
CLI / AI Agent  │              边界（DMZ/内网入口）             │
   │ OIDC       │  oauth2-proxy / nginx / Azure APIM / SAP APIM │
   │ 登录+Bearer │  - 校验 IdP JWT（iss/aud/exp）/MFA/准入        │
   │ ───────────▶                                             │
                │  - 确定用户身份                               │
                │  - 协议转换：S4U 委派 / mTLS / 头部透传       │
                └───────────────┬─────────────────────────────┘
                                │ SPNEGO（KCD 按人申请票据）
                                ▼
                         SAP ICM/SICF（只信任边界来源）
```

常见组件：

- **oauth2-proxy**：成熟的 OIDC 守门组件，配合 nginx；注意它最初面向浏览器会话，API 客户端场景要确认其 bearer/前置认证的配置方式【待验证：按部署版本核对】。
- **nginx + 模块/外挂**：auth_request 子请求做校验；委派需额外组件（Linux 上 S4U 支持有限，见 §4）。
- **云 API 管理**：Azure API Management、SAP API Management 等，自带 JWT 校验与连接器。

## 3. 目标侧转换方式对比

| 转换方式 | 按人 | 改密影响 | 适用 |
|---|---|---|---|
| **Kerberos 约束委派（KCD）** | 是 | 无（用户不需要在边界存密码） | **推荐**；Windows AD 环境 |
| 每人 X.509 证书委派 | 是 | 按证书周期续签 | PKI 成熟时 |
| 代理保险库存 Basic 口令 | 是（名义上） | **口令一改即崩**；明文集中存储 | 反模式，不建议 |
| 单一服务账号 + 网络信任 | **否** | 无 | 仅极窄只读且合规批准 |

## 4. Kerberos 约束委派（KCD）协议转换

**【标准实践】** KCD 让一个服务在**用户不提供口令、甚至最初不是 Kerberos 认证**的情况下，代表用户向指定后端服务申请 Kerberos 票据。包含两项扩展：

- **S4U2Self（Protocol Transition）**：边界服务为用户向自身申请可转发票据——即把 OIDC 已认证的身份"转换"为 Kerberos；
- **S4U2Proxy（Constrained Delegation）**：再用该票据代表用户向目标 SPN（`HTTP/sapgw.example.com`）申请服务票据。

最终 SAP 看到的是一次**正常的、按人的 SPNEGO 登录**，SAP 侧只需按 [02 章](02-spnego.md) 启用 SPNEGO 即可，不知道前面发生过 OIDC。

### 4.1 AD 配置（在域控/管理员机器）

1. 边界组件使用一个**托管服务账号**（推荐 gMSA，如 `svc_edge$`）；
2. 在该账号属性 → 委派：
   - 选择"**仅信任此计算机来委派指定的服务**"（Trust this computer for delegation to specified services only）；
   - 勾选"**使用任何身份验证协议**"（Use any authentication protocol）——这是协议转换开关；
   - 添加目标 SPN：`HTTP/sapgw.example.com`（先按 02 章在 SAP 服务账号上注册）；

   等价 PowerShell：

   ```powershell
   # 约束委派 + 协议转换
   Set-ADAccountControl svc_edge -TrustedToAuthForDelegation $true
   Set-ADUser svc_edge -Add @{
     "msDS-AllowedToDelegateTo" = @("HTTP/sapgw.example.com")
   }
   ```

3. （可选，更现代）**基于资源的约束委派 RBCD**：在目标 SAP 服务账号上写 `msDS-AllowedToActOnBehalfOfOtherIdentity`，由资源方控制谁能委派，适合跨域/资源自治场景。

### 4.2 边界组件要求

- 边界必须运行在能发起 S4U 的栈上：Windows 原生（IIS/.NET/Windows 版 nginx 配合 SSPI）最顺；纯 Linux 的开源代理默认不支持 S4U2Self（需要额外 Kerberos 委派模块/商业网关），选型时先验证【待验证】；
- 边界从 JWT 得到的用户标识，必须能解析为 AD 中存在的账号（UPN/NT4 名）；AD 中不存在的用户不能委派（fail-closed）；
- 票据只请求登记过的目标 SPN，禁止开放为"可委派任意服务"。

### 4.3 验证链路

```text
① 用浏览器/CLI 在边界完成 OIDC 登录
② 在边界机器检查取得的委派票据（Windows: klist）
   期望看到 Server: HTTP/sapgw.example.com，Client: <真实用户>
③ SAP 侧 SM20 审计应显示真实用户，而非边界服务账号
④ 负向：停用某用户的 AD/IdP 账号 → 委派失败、SAP 拒绝
```

## 5. 过渡信任及其边界

在 SPNEGO/KCD 或 handler 验签完成评审前，常见过渡做法是"代理校验 + 头部透传身份"：

```http
X-Auth-User: <sap-user>
X-Auth-Signature: <边界用私钥对身份头的签名>
```

仅当满足**全部**条件才可接受：

1. 代理 → SAP 走 **mTLS 或专线**，SAP 侧 ICM/网络组限制**只有边界 IP 能到达该服务节点**；
2. 对**自研 Z handler**：handler 验证边界签名/共享机密（机密不入 URL、不落日志），不接受无签名的身份头；
3. 标准 handler 无法验签——因此标准 handler **不能**用"信任身份头"过渡，只能等 KCD 或在更粗粒度（网络隔离 + 只读 + 合规批准）下处理；
4. 审计双写：边界保留 IdP 原始登录日志，SAP 记录透传身份，两者可对账。

明确禁止的形态：在公网或普通办公网段让 SAP 仅凭一个可伪造的 HTTP 头切换用户。

## 6. 优点 / 缺点

**优点**

- 把认证集中为一次基础设施投入，新增后端服务/客户端时边际成本低；
- MFA、准入、限流、审计在边界统一实施；SAP 侧保持标准、补丁友好；
- KCD 全程按人、无集中口令库。

**缺点**

- 边界成为关键路径与高价值目标：可用性与安全要求都高；
- KCD 链路跨 IdP/AD/SAP 三方，初次排错复杂；Linux 开源栈 S4U 支持有限；
- 增加一跳延迟与部署运维成本；对单一内网技能可能属过度设计。

## 7. 适用与不适用场景

适用：多个 SAP 服务共享一个对外入口；外网/混合终端访问；只有 IdP 但目标是标准 handler；统一安全策略（MFA/限流/审计）要求。

不适用：单一自研 handler + 纯内网（直连 04 章更简单）；AD 域内用户直连（02 章更简单）；不具备网关运维能力的小团队。

## 8. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 边界登录成功，SAP 仍 401 | 委派未生效/SPN 未登记 | 检查 `msDS-AllowedToDelegateTo`、SAP SPNEGO 配置 |
| S4U 报客户端名无法解析 | JWT 身份映射不到 AD 账号 | 维护 IdP→AD（UPN）映射，缺则拒绝 |
| 委派票据账号显示为服务账号 | 没走协议转换（缺 S4U2Self） | 勾选"使用任何身份验证协议"；核对权限 |
| Linux 边界无法委派 | 栈不支持 S4U | 换支持 S4U 的网关；或 Windows 边界 |
| 偶发失败 | gMSA/票据、时钟 | 校时、检查 gMSA 与 KDC 健康 |
| SAP 审计不是本人 | 链路退回 Basic/服务账号 | 核对票据流向，移除宽松兜底 |

## 9. 安全注意事项

1. 委派范围最小化：按目标 SPN 显式登记，禁止"对任意服务委派"；优先 RBCD 由资源侧掌控。
2. 边界自身必须强认证运维、最小暴露面、配置纳入版本管理与审计。
3. 过渡头部信任仅限 mTLS/白名单 + 可验签的 Z handler，并设定拆除期限，避免临时方案永久化。
4. 边界到 SAP 建议 HTTPS；校验 SAP 服务器证书，防止票据被中间人截用。
5. 离职/停用要在 IdP、AD、SAP 映射三处联动生效，并定期做"停用账号尝试访问"的抽测。
