# 03 X.509 客户端证书认证

基于 TLS 双向认证（mTLS）：客户端在 TLS 握手时出示由企业 CA 签发的用户证书，SAP 校验证书链并映射到 SAP 用户。适合已有企业 PKI、合规要求强的环境。

## 1. 原理与认证流程

**【标准实践】** 普通 HTTPS 只有客户端校验服务器证书；启用客户端证书后，TLS 握手中增加 `CertificateRequest → 客户端证书 → CertificateVerify` 环节。ICM 在建立连接时就完成身份确认，应用层无口令。

```text
客户端                                      SAP ICM (HTTPS 端口)
  │ ClientHello（带可选客户端证书能力）        │
  │ ────────────────────────────────────────▶ │
  │ ◀──────────────── ServerHello/服务器证书  │
  │ ◀──────────────── CertificateRequest      │  ICM 要求客户端证书
  │ 客户端证书（链）+ CertificateVerify 签名   │
  │ ────────────────────────────────────────▶ │ ICM 用信任的 CA 验链/有效期/吊销
  │                                           │ 提取证书 Subject，按规则映射 SU01
  │ ◀──────────────── 握手完成/HTTP 响应      │
```

证书可由软件承载（本机证书库/PFX 文件）或硬件承载（USB Key、智能卡、TPM），硬件形态安全性最高。

## 2. 前提条件

| 条件 | 说明 |
|---|---|
| 企业 PKI 已建立 | 存在可信的用户证书签发 CA（AD CS 或第三方），可通过 GPO 自动注册 |
| SAP 已启用 HTTPS | ICM 配置 HTTPS 端口与服务器证书（`SMICM`、`STRUST` SSL server PSE） |
| ICM 信任签发 CA | SSL server PSE 的证书列表中包含用户证书 CA 链 |
| 证书映射已维护 | 事务码 `CERTSMAP` 映射规则，或 `SU01` 中绑定证书（见 §5） |
| 吊销可检查 | CRL/OCSP 机制【待验证：取决于版本配置位置】，否则证书离职/泄露后无法即时作废 |

## 3. SAP 侧落地

### 3.1 ICM：启用 HTTPS 并要求客户端证书

1. **`SMICM`**：确认 HTTPS 端口已开放（参数 `icm/server_port_<n>` 含 `PROT=HTTPS`）。
2. **`STRUST`**：
   - SSL server PSE 中持有服务器自身证书链；
   - 将**签发用户证书的企业 CA 证书**加入信任列表（Certificate List），否则 ICM 拒绝所有客户端证书。
3. **实例参数（`RZ10`）**：

   ```text
   icm/HTTPS/verify_client = 1
   ```

   | 值 | 含义 |
   |---|---|
   | 0 | 不要求客户端证书 |
   | 1 | 可以提供（提供则校验；无证书时回退其他登录方式） |
   | 2 | **必须提供**，无有效证书直接拒绝（强 mTLS） |

   > 参数名与取值为【标准实践】；具体在你们 release 的默认值/额外吊销参数【待验证】。

### 3.2 SICF：启用证书登录

`SICF` → 服务节点 → 登录数据 → 登录过程中勾选 **"使用 SSL 证书登录"（Logon Using SSL Certificate）**。

建议顺序：证书登录优先，SPNEGO/Basic 作为兜底（视终端形态）。

### 3.3 AD 证书自动注册（面向业务用户）

在 AD CS 上创建"用户"证书模板（含 Client Authentication EKU `1.3.6.1.5.5.7.3.2`），通过组策略**自动注册**：域用户登录后证书自动进入 Windows 证书库（`certmgr.msc` → "个人"），无需手工操作。验证：

```powershell
certmgr.msc                       # 图形查看
certutil -user -store My          # 命令行列出当前用户证书
# 手工测试 mTLS（pfx）
curl.exe --cert user.pfx:<pfx-password> -v https://sapgw.example.com:44300/...
```

## 4. 客户端落地

### 4.1 Python：PEM 证书直传

```python
import requests

resp = requests.post(
    "https://sapgw.example.com:44300/sap/bc/rest2rfc",
    params={"RFC": "BAPI_MATERIAL_GETLIST", "sap-client": "800"},
    cert=("/path/to/user.crt.pem", "/path/to/user.key.pem"),  # mTLS 客户端证书+私钥
    headers={"Content-Type": "application/json", "Accept": "application/json"},
    data=b"{}",
    verify="/path/to/ca-bundle.pem",   # 同时校验服务器证书
    timeout=60,
)
```

`cert` 也可传单个 PEM（证书与私钥拼接）或 PFX（需转换，见下）。依赖仍仅 `requests`（底层 urllib3 + OpenSSL）。

### 4.2 Windows 证书库的关键坑

Python（OpenSSL 后端）**不能直接读取 Windows 系统证书库中的证书和私钥**，而自动注册的证书恰好就在那里。两条可行路线：

1. **一次性导出 PFX → 转 PEM**：

   ```powershell
   # certmgr.msc 导出（带私钥，设置 PFX 口令），然后转换
   openssl pkcs12 -in user.pfx -clcerts -nokeys -out user.crt.pem
   openssl pkcs12 -in user.pfx -nocerts -out user.key.pem
   ```

   缺点：私钥导出策略常被 GPO 禁止（"不允许导出私钥"），且导出后有副本需要管理。

2. **使用走 Schannel（Windows 原生 TLS 栈）的 HTTP 客户端**：如 `curl_cffi`（libcurl-impersonate）配合系统证书库/SSPI，可直接使用不可导出的证书与智能卡：

   ```python
from curl_cffi import requests as crequests
# 具体证书选择参数随版本而异，实施时核对 curl_cffi 文档【待验证】
resp = crequests.post(url, ..., cert=("CurrentUser", "My", "<thumbprint>"))
   ```

   额外依赖，但用户体验最好；跨平台不一致，需按终端区分后端。

### 4.3 智能卡/USB Key

若证书在硬件 Key 上，Python OpenSSL 路线同样不可用，需要：支持 PKCS#11 的客户端栈（如 `python-pkcs11` + 支持 engine 的 TLS 库），或直接使用 Schannel/SSPI 路线并在使用时接受 PIN 提示。该形态多为高权限账号场景，按项目专门验证。

## 5. 用户映射与授权

**【标准实践】** 证书到 SAP 用户有两条路径：

1. **`CERTSMAP` 映射规则（推荐）**：按证书 Subject DN 的字段（如 `CN=<用户名>`、`OU=...`）配置规则模式批量映射，支持按发布者区分；规则集中可审计，适合人数多的场景。
2. **`SU01` 逐用户绑定证书**：在用户主数据中录入具体证书；精确但维护量大，适合少量管理员账号。

映射不到用户即拒绝（fail-closed）。授权仍以映射后的 SAP 用户身份走标准对象检查（`S_RFC` 等），审计按人。

## 6. 优点 / 缺点

**优点**

- 安全性强：非对称凭证、有效期受控、可硬件承载、可吊销；无口令传输与存储问题；
- TLS 握手即完成认证，无额外往返；外网经 HTTPS 同样可用（配合 VPN/公开可信链）；
- AD 自动注册时业务用户基本无感。

**缺点**

- 强依赖企业 PKI 及其运维（签发、续期、吊销、模板、GPO）；
- 证书有效期到需续签，自动注册可掩盖该问题，但非域/手工证书易出现过期中断；
- Python 生态对 Windows 证书库、不可导出私钥、智能卡支持差，往往要换 TLS 栈，集成复杂度高于 SPNEGO；
- 吊销链路（CRL/OCSP）若没配或 SAP 无法访问，安全承诺打折。

## 7. 适用与不适用场景

适用：已建企业 PKI；合规明确要求证书/智能卡；高权限写操作账号；需要 mTLS 强身份的服务到服务集成。

不适用：没有 PKI 且不打算建设；纯内网域环境追求最简（SPNEGO 更合适）；业务终端类型杂、难以统一证书生命周期管理。

## 8. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 握手阶段失败 `unknown ca` / `bad certificate` | ICM 未信任签发 CA | `STRUST` SSL server PSE 补全 CA 链 |
| `peer did not return a certificate` | 客户端没出证书 / 参数为 2 时无证书 | 检查证书库、`cert=` 路径、策略 |
| 证书有效但 401 | 映射规则未命中 | `CERTSMAP`/`SU01` 核对 Subject DN 与规则 |
| `certificate has expired` | 证书过期 | 触发重新注册/续签；检查自动注册 GPO |
| `certificate revoked`（或该吊销未生效） | CRL/OCSP 行为 | 核对吊销配置与 ICM 可达性【待验证】 |
| Python 找不到证书 | OpenSSL 读不了 Windows 库 | 导出 PFX 转 PEM，或改 Schannel 栈 |
| 私钥不可导出 | GPO 限制 | 使用系统 TLS 栈；不要尝试绕过策略 |

## 9. 安全注意事项

1. 用户证书私钥是核心秘密：优先不可导出/硬件承载；PEM/PFX 副本必须 600 权限、用后删除，禁止入库入 git。
2. **必须规划吊销**：员工离职、私钥泄露依赖 CRL/OCSP 即时止损；同时保留 SAP 侧禁用/锁定映射用户的兜底流程。
3. `icm/HTTPS/verify_client=2` 前确认所有合法终端都具备证书，避免一刀切锁死。
4. 信任列表只放真正用于签发用户的 CA；误把根 CA 泛化信任会扩大可登录身份面。
5. 证书主题字段用于映射时选择稳定标识（工号/UPN），避免用可改名的显示名称。
