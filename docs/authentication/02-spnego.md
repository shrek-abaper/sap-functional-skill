# 02 Kerberos / SPNEGO（域内单点登录）

AD 域内业务用户的首选方案：用户登录 Windows 后，程序对 SAP 的请求自动携带 Kerberos 票据，**客户端零配置、无口令落盘**。SAP 侧为纯配置，无 ABAP 代码改动。

## 1. 原理与认证流程

**【标准实践】** Kerberos 是票据协议，核心角色：

- **KDC**（Key Distribution Center）：AD 域控同时承担，签发票据；
- **TGT**（Ticket Granting Ticket）：用户登录域后获得，可续期，无需再输口令；
- **SPN**（Service Principal Name）：服务实例的 Kerberos 标识，形如 `HTTP/<fqdn>@REALM`；
- **SPNEGO**（RFC 4178）：把 Kerberos 的 GSSAPI 令牌包装进 HTTP `Negotiate` 机制。

```text
① 用户登录域 → 获得 TGT（本机 LSA/凭据缓存）
② 首次访问 SAP → 用 TGT 向 KDC 申请 SPN=HTTP/<sap-fqdn> 的服务票据
③ HTTP 协商（可能 1~2 个往返）：

客户端 (WSL: kinit 后用票据缓存；域 Windows: SSPI 自动)
  │  GET/POST，401 WWW-Authenticate: Negotiate
  │ ◀───────────────────────────────────
  │  Authorization: Negotiate <base64 GSSAPI token（AP-REQ，含服务票据）>
  │ ────────────────────────────────────▶ SAP ICM
  │                                      用 SPN 密钥解密验票 → 映射 SU01 用户
  │  200（可选：Negotiate 回执 AP-REP 完成双向认证）
  │ ◀────────────────────────────────────
```

票据有时效（AD 默认约 10 小时、可续期 7 天），过期后台自动续，用户无感。

## 2. 前提条件

| 条件 | 说明 |
|---|---|
| 客户端加入 AD 域 | 域内 Windows 最顺；非域/WSL 需手工 `kinit`（见 §4） |
| SAP 与 AD 时间同步 | Kerberos 容忍约 5 分钟时钟偏差，超出直接失败 |
| SAP 支持 SPNEGO | **【标准实践】** AS ABAP 7.0（SP12 以后）/ 7.02+，配合 CommonCryptoLib（原 SAPCRYPTOLIB）；具体 patch 级别【待验证】 |
| SPN 在 AD 唯一注册 | 一个 SPN 只能注册在一个 AD 对象上，重复注册导致票据签给错误主体 |
| 主机名可解析 | 客户端按 URL 主机名构造 SPN；CNAME/反向 DNS 不一致是常见坑 |

## 3. SAP 侧落地

### 3.1 AD 侧：服务账号 + SPN + keytab

在 AD 上为 SAP 服务创建一个专用账号（如 `SAP_HTTP_<SID>`），设"口令永不过期"、使用 AES 加密类型。

```powershell
# 注册 SPN（在域管理员机器执行；FQDN 必须是用户访问 SAP 时使用的主机名）
setspn -S HTTP/sapgw.example.com SAP_HTTP_P01
setspn -L SAP_HTTP_P01          # 核对
setspn -X                       # 全目录查重，确认无重复 SPN
```

导出 Kerberos keytab（供 AS ABAP 验证票据）：

```powershell
# 【标准实践】Windows ktpass；/crypto 建议 AES256（不建议 RC4）
ktpass -princ HTTP/sapgw.example.com@EXAMPLE.COM `
  -mapuser SAP_HTTP_P01 `
  -pass "<account-password>" `
  -ptype KRB5_NT_PRINCIPAL `
  -crypto AES256-SHA1 `
  -out C:\keytabs\saphttp.keytab
```

> 注意：重复执行 `ktpass` 会改变 kvno；必须用**最后一次**导出的 keytab 导入 SAP，否则验票失败。

### 3.2 AS ABAP：导入 keytab 并启用 SPNEGO

1. **`STRUST`**：确认 SPNEGO（Kerberos）用的 PSE/凭据库就绪；将 keytab 导入到 SPNEGO 配置。
2. **`SPNEGO` 事务码（SPNEGO 向导）**：
   - 新建配置条目，选择/添加 AD Realm（`EXAMPLE.COM`）；
   - 录入 SPN 与服务账号、keytab；
   - 定义 **Kerberos principal → SAP 用户映射规则**（见 §5）；
   - 激活配置。
3. **`SICF`**：定位服务节点（如 `/sap/bc/rest2rfc` 或父节点 `/sap/bc`），登录过程（Logon Data → 过程）中：
   - 勾选/启用 **SPNEGO（"通过 SPNEGO 登录"）并置于优先位置**；
   - **建议保留 Basic 作为兜底**（移动设备/非域场景），顺序按需排列；
4. **`SMICM` / `RZ10`**：重启 ICM 或按向导要求使配置生效；确认实例参数（向导通常自动写入，无需手工维护；具体参数集【待验证】，勿凭记忆在 `RZ10` 手改）。

### 3.3 连通性验证

```bash
# Linux/WSL 上的标准验证：--negotiate 启用 SPNEGO，-u : 表示不使用口令
curl --negotiate -u : -v \
  "http://sapgw.example.com:8000/sap/bc/rest2rfc?RFC=BAPI_MATERIAL_GETLIST&sap-client=800" \
  -X POST -d '{}' -H "Content-Type: application/json"
```

期望看到 `Authorization: Negotiate ...` 且最终非 401。域内 Windows 也可用 PowerShell `curl.exe`（注意不是 `Invoke-WebRequest` 的别名行为）验证。

## 4. 客户端落地

### 4.1 Python 依赖

```text
# requirements（可选后端，运行时探测导入）
# requests-gssapi     # Linux / WSL（基于 gssapi，MIT Kerberos）
# requests-kerberos   # 原生 Windows 走 SSPI，域内零配置；也支持 Unix
```

### 4.2 域内 Windows（业务用户场景）

`requests-kerberos` 在 Windows 上通过 SSPI 自动使用域登录票据：

```python
import requests
from requests_kerberos import HTTPKerberosAuth, OPTIONS, DISABLED

auth = HTTPKerberosAuth(mutual_authentication=DISABLED)  # 内网 HTTP 常关双向认证
resp = requests.post(
    "http://sapgw.example.com:8000/sap/bc/rest2rfc",
    params={"RFC": "BAPI_MATERIAL_GETLIST", "sap-client": "800"},
    auth=auth,
    headers={"Content-Type": "application/json", "Accept": "application/json"},
    data=b"{}",
    timeout=60,
)
```

用户无需做任何配置。

### 4.3 WSL / Linux（开发者场景）

需要 MIT Kerberos 与 `/etc/krb5.conf` 指向同一 AD Realm，并先取得票据：

```bash
# 安装（Debian/Ubuntu）
sudo apt-get install krb5-user
# 配置 /etc/krb5.conf 后获取 TGT（用 AD 域账号）
kinit user@EXAMPLE.COM
klist                 # 查看票据缓存与有效期
```

```python
from requests_gssapi import HTTPSPNEGOAuth, OPTIONS, DISABLED

auth = HTTPSPNEGOAuth(mutual_authentication=DISABLED)
resp = requests.post(url, ..., auth=auth)  # 其余参数同 Windows 示例
```

也可用 `k5start`/`krenew` 或 cron `kinit` 保持票据长期有效。

### 4.4 配置示例（建议的连接配置形态）

```json
{
  "host": "http://sapgw.example.com:8000",
  "path": "/sap/bc/rest2rfc",
  "client": "800",
  "auth": {
    "type": "kerberos",
    "kerberos": { "spn": "HTTP/sapgw.example.com", "principal": "" }
  }
}
```

无显式 SPN 时，客户端按 URL 主机名自动推导。

## 5. 用户映射与授权

SPNEGO 配置中定义票据身份到 SAP 用户的映射，**【标准实践】** 常见三种：

1. **同名映射**：Kerberos 短名 = SAP 用户名（如 `<sap-user>@EXAMPLE.COM → <sap-user>`），可配大小写不敏感；
2. **映射表/前缀后缀规则**：多域、命名规范不一致时在向导中维护显式映射；
3. 映射不到用户时**拒绝登录**（fail-closed），不自动开户。

授权与 Basic 完全一致：后续处理以映射后的 SAP 用户身份执行，`S_RFC` 等授权对象、`SM20` 审计均按人生效。

## 6. 优点 / 缺点

**优点**

- 业务用户真正零配置：登录 Windows 即登录 SAP，无口令输入环节；
- 客户端不存长期口令；票据短期、自动续期；口令轮换对用户透明；
- SAP 侧无代码，纯向导配置；可与 Basic 并存。

**缺点**

- 依赖 AD 域与域加入机器；外网/非域电脑基本不可用（需 VPN + `kinit`，体验回落）；
- 初次配置链路长（AD 账号、SPN、keytab、向导），排错需要同时懂 AD 和 SAP；
- WSL/Linux 要装 Kerberos 并手工 `kinit`；
- SPN 重复注册、CNAME、时钟偏差、kvno 不一致是典型"全员都登不上"的高风险点。

## 7. 适用与不适用场景

适用：AD 域内 Windows 业务用户的只读/写技能；企业内网统一 SSO 推广。

不适用：非域终端、外网直接访问、无 AD 环境；这些场景选 OIDC（[04 章](04-oidc-oauth2.md)）。

## 8. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 一直 401，无 Negotiate 成功 | SPN 错误/重复、keytab kvno 不一致 | `setspn -X`；重新 ktpass 并重新导入 keytab |
| `Clock skew too great` | 时间偏差超 5 分钟 | NTP 对齐客户端/SAP/DC |
| `Key version number mismatch` | 服务账号改过密/重导 keytab | 用最新 keytab 重新导入 |
| `Server not found in Kerberos database` | URL 主机名与 SPN 不匹配（CNAME 影响） | 按注册 SPN 的主机名访问；检查 DNS |
| 加密类型相关失败 | RC4 被禁/客户端无 AES | 统一 AES256；检查账号与客户端支持 |
| WSL：`No credentials cache` | 未 `kinit` 或票据过期 | `kinit user@REALM`，检查 `klist` |
| 偶发全员失败 | DC 问题/SPNEGO 配置被改 | 检查域控健康与传输请求中的配置变更 |

## 9. 安全注意事项

1. 服务账号口令强且永不过期、仅用于 SPN；启用 AES，禁用 RC4（除非老客户端强制需要并经评审）。
2. Basic 兜底若保留，需明确策略：SPNEGO 优先、Basic 仅限受信网段或逐步关闭。
3. keytab 等同服务账号密钥，传输/存放按机密处理；导入后删除中间副本。
4. 多 SAP 主机/多 SPN 要逐一注册，禁止多个服务共享同一 keytab 主体造成越权票据互认。
5. 映射规则禁止通配（如去掉 Realm 后宽松匹配），防止域外身份冒用。
