# 04 OIDC / OAuth2（企业身份平台 SSO）

让 SAP 网关接受企业身份平台（**Entra ID / AD FS / Keycloak** 等标准 OIDC Provider）签发的短期令牌，用户只需一次浏览器登录。对混合终端（域机、WSL、外网笔记本）都友好，是现代集成的主流路线。

## 1. 原理与认证流程

**【标准实践】** OAuth2 是授权框架，OIDC 是在其上的身份层。角色：

- **End User**：业务用户，在 IdP 拥有账号（通常已配置 MFA）；
- **Client**：本场景是 CLI / AI Agent（**public client**，无法保密 client secret）；
- **Authorization Server（IdP）**：签发令牌、提供登录与 discovery/JWKS；
- **Resource Server（RS）**：SAP 侧的网关 handler，校验并消费 access token。

令牌类型：

| 令牌 | 用途 | 寿命（典型） | 存放 |
|---|---|---|---|
| access token | 调 API 时放 `Authorization: Bearer` | 约 1 小时 | 本地文件（600）即可 |
| refresh token | access 过期后换新 | 数天~数月，可撤销 | OS 凭据库 |
| id token | 客户端获得用户身份信息（JWT） | 短 | 本地读取，不发给 RS 也可 |

**直连形态（仅适用于自研 Z handler）：**

```text
① login（每终端一次）：CLI 起本地回调 → 浏览器到 IdP 完成登录 → 回调带 code
                     CLI 用 code+PKCE 换取 access/refresh/id token，本地保存
② call（日常）：
CLI ── POST ... Authorization: Bearer <access token> ──▶ SAP 网关 handler
                                                         验 JWKS/iss/aud/exp
                                                         claim 映射 SU01
                                                         以映射用户执行 RFC
③ access 临期：CLI 用 refresh token 静默换新；refresh 失效 → 提示重新 login
```

> **关键边界**：标准 SAP handler（如 ADT `/sap/bc/adt`）不能直连此方案，必须走边界转换，见 [05 边界模式](05-edge-patterns.md)。

## 2. 前提条件

| 条件 | 说明 |
|---|---|
| 存在 OIDC IdP | Entra ID、AD FS、Keycloak 等，支持 discovery 与所需 grant |
| 已注册应用 | public client；允许 loopback 重定向；启用设备码流（Entra 需开启） |
| 网关可验签 | Z handler 能访问 IdP JWKS 端点（内网需代理/缓存） |
| 时钟同步 | JWT 校验 `exp`/`nbf`，偏差会导致全体失败 |
| 用户映射表 | 约定 claim → SU01 的映射并预置（见 §6） |

## 3. IdP 应用注册

在 IdP 管理后台为 CLI 注册应用（名称如 `sap-stock-cli`）：

- **类型**：public client / native client（**无 client secret**）；
- **重定向 URI**（PKCE 流）：`http://127.0.0.1` 或 `http://localhost`（RFC 8252 loopback，端口动态）；
- **允许的 grant**：Authorization Code（+PKCE）、Device Code；
- **scope**：`openid profile offline_access`（`offline_access` 才发 refresh token）；
- **受众（aud）**：约定一个 API 标识，例如 Keycloak 的 audience 为网关 client，Entra 为 `api://<api-app-id>`；需要 scope 如 `api://rest2rfc/access`；
- 确认租户/issuer：Entra 单租户用 `https://sts.windows.net/<tenant-id>/`；避免 `/common`（签发的 iss 随租户变化，RS 难校验）。

## 4. 客户端落地

仅用标准库 + `requests`，无需新依赖。

### 4.1 Discovery

```python
def discover(issuer: str) -> dict:
    resp = requests.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration", timeout=20)
    resp.raise_for_status()
    return resp.json()

# 返回：authorization_endpoint / token_endpoint / device_authorization_endpoint /
#       jwks_uri / issuer
```

配置可缓存到 `.cache/`，启动时若 404/失效再刷新。

### 4.2 PKCE 浏览器流（RFC 7636 + RFC 8252）

```python
import base64, hashlib, secrets, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

def login_pkce(cfg: dict, client_id: str) -> dict:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = _b64url(secrets.token_bytes(16))
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):                              # noqa: N802
            q = parse_qs(self.path.split("?", 1)[-1])
            result["code"] = q.get("code", [None])[0]
            result["state"] = q.get("state", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write("登录完成，可回到终端。".encode())
        def log_message(self, *a):                     # noqa: A003
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)     # 系统分配空闲端口
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    authz_url = cfg["authorization_endpoint"] + "?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid profile offline_access",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    webbrowser.open(authz_url)
    server.handle_request()
    assert result["state"] == state, "state mismatch（可能是 CSRF）"

    tok = requests.post(cfg["token_endpoint"], data={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": result["code"],
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }, timeout=30)
    tok.raise_for_status()
    return tok.json()    # access_token / refresh_token / id_token / expires_in
```

### 4.3 设备码流（RFC 8628，WSL/headless/无浏览器）

```python
import time

def login_device(cfg: dict, client_id: str) -> dict:
    d = requests.post(cfg["device_authorization_endpoint"], data={
        "client_id": client_id,
        "scope": "openid profile offline_access",
    }, timeout=30).json()
    print(f"打开 {d['verification_uri']} 输入代码：{d['user_code']}")

    interval = d.get("interval", 5)
    while True:
        time.sleep(interval)
        tok = requests.post(cfg["token_endpoint"], data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id,
            "device_code": d["device_code"],
        }, timeout=30)
        data = tok.json()
        err = data.get("error")
        if err in (None, ""):
            return data
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err in ("access_denied", "expired_token"):
            raise RuntimeError(f"设备登录失败：{err}")
```

### 4.4 刷新与日常调用

```python
def refresh(cfg: dict, client_id: str, refresh_token: str) -> dict:
    r = requests.post(cfg["token_endpoint"], data={
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
        "scope": "openid profile offline_access",
    }, timeout=30)
    if r.status_code == 400 and r.json().get("error") in ("invalid_grant",):
        raise RuntimeError("OIDC_RELOGIN")      # 刷新令牌失效/被撤销 → 重新 login
    r.raise_for_status()
    return r.json()

resp = requests.post(
    gateway_url,
    params={"sap-client": "800"},
    headers={"Authorization": f"Bearer {tokens['access_token']}",
             "Content-Type": "application/json"},
    data=b"{}",
    timeout=60,
)
```

### 4.5 连接配置形态

```json
{
  "host": "https://sapgw.example.com:44300",
  "path": "/sap/bc/rest2rfc",
  "client": "800",
  "auth": {
    "type": "oidc",
    "oidc": {
      "issuer": "https://login.microsoftonline.com/<tenant-id>/v2.0",
      "client_id": "<cli-app-id>",
      "login_mode": "auto",
      "scopes": ["openid", "profile", "offline_access", "api://rest2rfc/access"]
    }
  }
}
```

## 5. SAP 网关侧落地（Z handler）

### 5.1 JWT 校验（必须强校验，缺一不可）

校验项：签名（按 `alg=RS256`，用 JWKS 中匹配 `kid` 的公钥）、`iss` 白名单、`aud` 必须包含本 API 标识、`exp` 未过期、`nbf` 已生效。

```text
# 伪代码
on request:
  token = header["Authorization"] removeprefix("Bearer ")
  header = decode_jwt_header(token)
  key = jwks_cache.get(header.kid)           # JWKS 定期刷新（如按 Cache-Control/1h）
  if key is None: fetch jwks_uri and retry once
  claims = verify_jwt(token, key, algorithms=["RS256"])
  assert claims.iss in TRUSTED_ISSUERS
  assert API_AUDIENCE in as_list(claims.aud)
  now = utcnow(); assert claims.nbf <= now < claims.exp
  identity = claims["preferred_username"]    # 或 Entra: oid+tid / upn
  sap_user = lookup ZTIF_OIDC_MAP where issuer=claims.iss and claim=identity
  if sap_user is None: reject 401            # fail-closed
  execute_rfc_as(sap_user)
```

JWKS 缓存要点：按 `kid` 索引；未知 kid 时允许刷新一次；缓存失败要拒绝请求而不是跳过验签。

### 5.2 用户映射（fail-closed）

建议维护映射表（如沿用网关现有 `ZTIF_*` 命名风格，新建 `ZTIF_OIDC_MAP`）：

| issuer | claim 名 | claim 值 | SAP 用户 | 有效期/状态 |
|---|---|---|---|---|
| https://sts.windows.net/<tid>/ | preferred_username | <sap-user>@example.com | <SAP-USER> | active |

不自动开户、不按"去掉域名前缀"做隐式宽松匹配（命名巧合会造成越权）。

### 5.3 用户身份切换（安全关键，需评审）

校验通过后要让后续动态 RFC **以映射的 SAP 用户身份**执行，否则 `S_RFC` 权限与审计按 handler 的服务账号算，SSO 失去意义。

- **【待验证】** AS ABAP 提供 kernel user switch 能力（如 `SUSR_INTERNET_USERSWITCH` 一类函数），但属于敏感操作，多数企业基线严控或禁用；**具体可用函数、版本支持与开关必须先咨询安全/基线团队并在目标系统 PoC**，不要按本文档直接上线。
- 切换后必须在同一请求结束时恢复原上下文，错误路径也要恢复，防止身份泄漏到后续请求。
- 评审完成前的过渡：见 [05 边界模式](05-edge-patterns.md)（前置代理校验 + mTLS/白名单）。

## 6. 用户映射与授权（小结）

- 身份来源 claim 要稳定（工号、Entra `oid`+`tid`，避免可改的显示名）；
- 授权仍按映射后的 SAP 用户走 `S_RFC` 等对象；审计记录映射关系与原始 claim。

## 7. 优点 / 缺点

**优点**

- 用户只需一次浏览器 SSO；MFA/条件访问由 IdP 统一实施；
- 令牌短期、可即时撤销；refresh 自动续期，口令轮换对用户无感；
- 终端形态无关：域机/WSL/Mac/外网一致；是跨项目最通用的方式。

**缺点**

- 依赖 IdP 与应用注册治理；SAP handler 需开发验签与映射；
- 身份切换涉及安全评审，是工期最大不确定性；
- 链路排错环节多（discovery/浏览器/回调/刷新/JWKS）；aud/scope 配置错误最常见。

## 8. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 登录回调失败 `redirect_uri mismatch` | 注册 URI 与 loopback 不一致 | 精确注册 `http://127.0.0.1`（端口可省略注册） |
| 令牌拿到但网关 401 `invalid audience` | scope/aud 未包含 API | IdP 配置 audience 与 scope；检查 RS 期望 |
| JWKS `kid not found` | 换密钥后缓存陈旧 | RS 刷新 JWKS；检查多环境混用 issuer |
| 刷新报 `invalid_grant` | refresh 过期/被撤销/换设备 | 提示重新 `login`；不自动重试 |
| 登录即 `invalid_client` | 误配成机密客户端/缺 client_id | 注册为 public client |
| Entra：用户需管理员同意 | 权限需要 admin consent | 管理员预授权；检查租户同意策略 |
| 时间相关失败 | 时钟偏差 | NTP 同步客户端与 SAP |
| 设备码一直 pending | 用户未完成网页登录 | 检查打印的 URI/code；确认设备码流已启用 |

## 9. 安全注意事项

1. 必须使用 PKCE；`state` 防 CSRF；public client 不使用 secret。
2. 网关**永远**验签且校验全部声明；禁止 `alg=none`、禁止从 token 的 `alg` 字段选择对称密钥。
3. refresh token 按用户机密存 OS 凭据库；access token 文件 600；不在日志/URL 里打印令牌（详见 [06 章](06-client-patterns.md)）。
4. 映射严格、身份切换经评审；离职/异常以 IdP 撤销 + 映射停用双保险。
5. CI 不能走用户交互流；如用 `client_credentials` 得到的是技术身份，不得映射为某个真实用户，需单独授权与审计。
