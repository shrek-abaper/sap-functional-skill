<div align="center">

# SAP Functional Skill

[![GitHub Stars](https://img.shields.io/github/stars/shrek-abaper/sap-functional-skill?style=flat-square&color=FFD700&logo=github&logoColor=white&label=Stars)](https://github.com/shrek-abaper/sap-functional-skill/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/shrek-abaper/sap-functional-skill?style=flat-square&color=3E40C9&logo=github&logoColor=white&label=Forks)](https://github.com/shrek-abaper/sap-functional-skill/network/members)
[![Contributors](https://img.shields.io/github/contributors/shrek-abaper/sap-functional-skill?style=flat-square&color=2EA043&logo=github&logoColor=white)](https://github.com/shrek-abaper/sap-functional-skill/graphs/contributors)
[![Last Commit](https://img.shields.io/github/last-commit/shrek-abaper/sap-functional-skill?style=flat-square&color=0066CC&logo=github&logoColor=white)](https://github.com/shrek-abaper/sap-functional-skill/commits/main)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![SKILL](https://img.shields.io/badge/SKILL-%E8%A7%84%E8%8C%83-7C3AED?style=flat-square&logo=markdown&logoColor=white)](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills)

### 把 SAP 一线实战经验，打包成 AI 智能体可复用的 Skill

#### *十余年 SAP 项目笔记蒸馏为知识型与执行型技能，在 SAP 话题出现的那一刻自动加载。*

> 目前包含两个技能：覆盖 14 个模块、对话中检测到 SAP 话题即自动触发的被动知识库；以及通过 S/4HANA OData API 创建 STO 调拨订单、强制执行「先 preview 预览、后 create 创建」安全门禁的主动执行技能。遵循标准 SKILL 规范，Claude Code、OpenCode 及任何兼容的智能体框架均可直接加载。

**知识型技能 &nbsp;·&nbsp; 执行型技能 &nbsp;·&nbsp; 自动触发路由 &nbsp;·&nbsp; 标准 SKILL 规范**

**14 大 SAP 模块 &nbsp;·&nbsp; 15 个一线排查案例 &nbsp;·&nbsp; S/4HANA OData &nbsp;·&nbsp; SAP JCo / BAPI**

**兼容 Claude Code &nbsp;·&nbsp; 兼容 OpenCode &nbsp;·&nbsp; MIT 许可 &nbsp;·&nbsp; 知识应该流动，不应该沉睡**

#### 面向 SAP 功能顾问、ABAP 开发者，以及用 AI 智能体交付项目的团队

**[项目背景](#项目背景)** &nbsp;·&nbsp; **[项目简介](#项目简介)** &nbsp;·&nbsp; **[sap-trench-skill](#sap-trench-skill)** &nbsp;·&nbsp; **[sap-sto-create](#sap-sto-create)** &nbsp;·&nbsp; **[安装与使用](#安装与使用)** &nbsp;·&nbsp; **[License](#license)**

[English](README.md) &nbsp;·&nbsp; 中文

</div>

---

## 项目背景

做 SAP 顾问这些年，真正有价值的经验往往散落在项目现场的每一次排查过程中——那些在标准文档之外、只有亲历才能积累的判断与洞察。

这些年笔记工具换了一轮又一轮：最早用 **Mybase** 做树形笔记，后来迁到 **OneNote**，再后来系统化整理进 **Notion**。每次迁移都是一次沉淀，但笔记终究只是静态的文档，对着 AI 对话窗口它们帮不上忙。

现在 AI Coding Agent 已经成为日常工具。与其让这些积累继续躺在 Notion 里，不如把它重新组织成 AI 智能体能直接加载、索引、引用的 **SKILL** 格式——让每一条记录都能在下一次对话里及时被召唤出来，也分享给同样在 SAP 战壕里作业的同行。

这就是 **SAP Functional Skill** 的起点。从最初记录 SAP 战壕里的第一手经验（[sap-trench-skill](skills/sap-trench-skill/)），到逐步扩展为覆盖 SAP 各业务领域的 Skill 集合。

---

## 项目简介

`sap-functional-skill` 是一个遵循标准 **SKILL 规范**的 SAP 业务领域 AI 技能包集合，适用于所有支持 SKILL 格式的 AI 智能体（包括 Claude Code、OpenCode 及其他兼容框架）。

目前包含两个不同类型的 Skill：

| Skill | 类型 | 说明 |
|---|---|---|
| [`sap-trench-skill`](skills/sap-trench-skill/) | 知识型 | 被动触发——对话中检测到 SAP 话题即自动加载，涵盖 14 个模块参考文件 |
| [`sap-sto-create`](skills/sap-sto-create/) | 执行型 | 主动触发——通过 S/4HANA OData API 创建 STO 调拨订单，Python + Java/JCo 实现 |

---

## sap-trench-skill

来自真实 SAP 项目交付的参考知识库，覆盖所有主要模块。在 AI 对话中检测到任何 SAP 相关话题时自动触发，无需手动调用。

### 覆盖模块

| 模块 | 文件 | 内容重点 |
|---|---|---|
| ABAP 开发 | `references/abap.md` | 语法、性能优化、BAdI/Enhancement Spot、调试工具 |
| MM 采购与库存 | `references/mm.md` | 采购订单、STO 工厂间调拨、科目确定、消息控制 |
| SD 销售与分销 | `references/sd.md` | 销售订单、定价、交货、开票、信贷管理、ATP/MTO |
| FI/CO 财务 | `references/fico.md` | 凭证过账、汇率、凭证分割、COPA、替换、自动付款 |
| PP 生产计划 | `references/pp.md` | 生产订单、BOM、工艺路线、MRP、可配置 BOM |
| WM 仓库管理 | `references/wm.md` | 转储单、转储需求、仓位管理、盘点 |
| PM 工厂维护 | `references/pm.md` | 设备、功能位置、维护订单、维护计划、序列号 |
| QM 质量管理 | `references/qm.md` | 检验批、使用决策、质量通知书、检验计划 |
| VMS 车辆管理 | `references/vms.md` | IS-AUTO VELO 对象、IDoc 增强、SPRO 配置 |
| 系统集成 | `references/integration.md` | PI/PO、IDoc、Proxy、OData、XML/JSON 排查 |
| 权限管理 | `references/auth.md` | AUTHORITY-CHECK、角色、SU53、权限对象 |
| 打印技术 | `references/print.md` | SmartForms、SAPscript、NACE 消息控制 |
| 事务码速查 | `references/reference-tables.md` | 全模块 T-code、关键表、BAPI 索引 |
| 排查案例库 | `references/troubleshooting.md` | CASE-001 ~ CASE-015，完整根因分析 |

### 典型触发场景

- *"MIGO 过账时报错 Serial number already exists 怎么解决？"*
- *"SD 定价过程中 PR00 条件类型找不到，根因是什么？"*
- *"IDoc 状态 51 排查思路"*
- *"ABAP BAdI 实现步骤"*

---

## sap-sto-create

通过 S/4HANA 标准 OData 服务 `API_PURCHASEORDER_PROCESS_SRV` 创建 STO 调拨订单的执行型技能。当发出工厂为售后工厂时，自动通过 SAP JCo 调用 `BAPI_OUTB_DELIVERY_CREATE_STO` 创建外向交货单。

**核心设计**：强制执行「先 `preview` 确认、再 `create`」的双步骤门禁，防止误创建订单。

### 技术栈

- **Python** — CLI 入口与 OData 编排
- **Java / SAP JCo** — 外向交货单创建（RFC/BAPI）
- **S/4HANA OData** — `API_PURCHASEORDER_PROCESS_SRV`

### 快速上手

```bash
# 查看可用工厂组合
python3 scripts/sap_sto_cli.py plants

# 预览（dry run，创建前必须先执行）
python3 scripts/sap_sto_cli.py preview \
  --supply-plant P002 \
  --receiving-plant A002 \
  --material MAT-001:3 \
  --delivery-date 2026-05-30 \
  --batch-number BATCH001

# 创建（需显式传入 --confirmed 安全开关）
python3 scripts/sap_sto_cli.py create \
  --supply-plant P002 \
  --receiving-plant A002 \
  --material MAT-001:3 \
  --delivery-date 2026-05-30 \
  --batch-number BATCH001 \
  --confirmed
```

完整环境配置与 JCo 库放置说明见 [`skills/sap-sto-create/README.md`](skills/sap-sto-create/README.md)。

---

## 安装与使用

```bash
git clone https://github.com/shrek-abaper/sap-functional-skill.git

# 安装知识型技能
cp -r sap-functional-skill/skills/sap-trench-skill ~/.agents/skills/

# 安装执行型技能
cp -r sap-functional-skill/skills/sap-sto-create ~/.agents/skills/
```

Claude Code 会在对话启动时自动发现并加载已安装的技能。

---

## 项目结构

```
sap-functional-skill/
└── skills/
    ├── sap-trench-skill/          # 知识型技能——SAP 实战排查
    │   ├── SKILL.md               # 触发层（路由表 + 关键词）
    │   ├── README.md
    │   ├── CONTRIBUTING.md
    │   ├── evals/
    │   │   └── golden-set.yaml    # 7 条评测问答
    │   └── references/            # 14 个知识文件
    │       ├── abap.md
    │       ├── auth.md
    │       ├── fico.md
    │       ├── integration.md
    │       ├── mm.md
    │       ├── pm.md
    │       ├── pp.md
    │       ├── print.md
    │       ├── qm.md
    │       ├── reference-tables.md
    │       ├── sd.md
    │       ├── troubleshooting.md
    │       ├── vms.md
    │       └── wm.md
    └── sap-sto-create/            # 执行型技能——OData 创建 STO 订单
        ├── SKILL.md               # 触发层 + 工具路由
        ├── README.md
        ├── .env.example           # 环境变量模板
        ├── evals/
        │   └── evals.json
        └── scripts/
            ├── sap_sto_cli.py     # CLI 入口
            ├── requirements.txt
            └── lib/
                ├── create_sto_odata.py   # 核心 OData 业务逻辑
                └── java/
                    ├── SapDeliveryCreator.java
                    ├── sapjco3.jar
                    └── lib/              # 各平台 JCo 本地库
                        ├── linux/
                        ├── macos/
                        └── windows/
```

---

## 贡献

欢迎提交你自己踩过的 SAP 坑。贡献规范见 [CONTRIBUTING.md](skills/sap-trench-skill/CONTRIBUTING.md)。

每条知识卡片遵循统一结构：**现象 → 根本原因 → 解决方案 → 经验总结**，确保 AI 能准确理解和引用。

---

## 适用平台

所有技能遵循标准 SKILL 规范，凡是支持该规范的 AI 智能体均可直接加载使用：

- [Claude Code](https://claude.ai/code)
- [OpenCode](https://github.com/opencode-ai/opencode)

---

## License

MIT — 知识应该流动，不应该沉睡。
