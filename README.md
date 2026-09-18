<div align="center">

# SAP Functional Skill

[![GitHub Stars](https://img.shields.io/github/stars/shrek-abaper/sap-functional-skill?style=flat-square&color=FFD700&logo=github&logoColor=white&label=Stars)](https://github.com/shrek-abaper/sap-functional-skill/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/shrek-abaper/sap-functional-skill?style=flat-square&color=3E40C9&logo=github&logoColor=white&label=Forks)](https://github.com/shrek-abaper/sap-functional-skill/network/members)
[![Contributors](https://img.shields.io/github/contributors/shrek-abaper/sap-functional-skill?style=flat-square&color=2EA043&logo=github&logoColor=white)](https://github.com/shrek-abaper/sap-functional-skill/graphs/contributors)
[![Last Commit](https://img.shields.io/github/last-commit/shrek-abaper/sap-functional-skill?style=flat-square&color=0066CC&logo=github&logoColor=white)](https://github.com/shrek-abaper/sap-functional-skill/commits/main)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![SKILL](https://img.shields.io/badge/SKILL-Specification-7C3AED?style=flat-square&logo=markdown&logoColor=white)](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills)

### SAP Field Experience, Packaged as Reusable AI Agent Skills

#### *A decade of SAP project notes distilled into knowledge and execution skills that load the moment an SAP question comes up.*

> Two skills today: a passive knowledge base spanning 14 modules that auto-triggers on any SAP topic, and an active execution skill that creates STO transfer orders through the S/4HANA OData API — with a mandatory preview-before-create safety gate. Standard SKILL format: Claude Code, OpenCode, and any compatible agent framework load them as-is.

**Knowledge Skills &nbsp;·&nbsp; Execution Skills &nbsp;·&nbsp; Auto-Trigger Routing &nbsp;·&nbsp; Standard SKILL Format**

**14 SAP Modules &nbsp;·&nbsp; 15 Field Troubleshooting Cases &nbsp;·&nbsp; S/4HANA OData &nbsp;·&nbsp; SAP JCo / BAPI**

**Claude Code Ready &nbsp;·&nbsp; OpenCode Ready &nbsp;·&nbsp; MIT Licensed &nbsp;·&nbsp; Knowledge Should Flow, Not Sleep**

#### Built for SAP Functional Consultants, ABAP Developers, and Teams Delivering with AI Agents

**[Background](#background)** &nbsp;·&nbsp; **[What's Inside](#whats-inside)** &nbsp;·&nbsp; **[sap-trench-skill](#sap-trench-skill)** &nbsp;·&nbsp; **[sap-sto-create](#sap-sto-create)** &nbsp;·&nbsp; **[Installation](#installation)** &nbsp;·&nbsp; **[License](#license)**

English &nbsp;·&nbsp; [中文](README.zh-CN.md)

</div>

---

## Background

Years of SAP consulting work leaves behind something valuable: the hard-won judgment that accumulates from actual incidents on the ground — insights that live outside the standard documentation and only come from being there.

Those notes have migrated through tools over the years: **Mybase** tree notes, then **OneNote**, then a more structured **Notion** workspace. Each migration was a refinement. But static documents don't help when you're mid-conversation with an AI agent.

Now that AI coding agents are a daily tool, it makes more sense to restructure this accumulated knowledge into the **SKILL format** — so every record can be loaded, indexed, and referenced at the right moment in the next conversation, and shared with others working in the same SAP trenches.

That's the origin of **SAP Functional Skill**: starting from first-hand SAP field experience ([sap-trench-skill](skills/sap-trench-skill/)), and expanding into a growing collection of skills covering SAP business domains.

---

## What's Inside

`sap-functional-skill` is a collection of SAP business-domain AI skill packages following the standard **SKILL specification**, compatible with any AI agent framework that supports the format (including Claude Code, OpenCode, and other compatible frameworks).

The collection currently contains two skills of different types:

| Skill | Type | Description |
|---|---|---|
| [`sap-trench-skill`](skills/sap-trench-skill/) | Knowledge | Passive — auto-triggers on any SAP question. 14 reference files covering all major modules. |
| [`sap-sto-create`](skills/sap-sto-create/) | Execution | Active — creates STO transfer orders via S/4HANA OData API. Python + Java/JCo. |

---

## sap-trench-skill

A reference knowledge base distilled from real SAP project delivery across all major modules. Auto-triggers in AI conversation whenever an SAP topic is detected — no manual invocation required.

### Coverage

| Module | File | Focus |
|---|---|---|
| ABAP Development | `references/abap.md` | Syntax, performance tuning, BAdI/Enhancement Spot, debug tools |
| MM (Procurement & Inventory) | `references/mm.md` | Purchase orders, STO plant-to-plant transfer, account determination, message control |
| SD (Sales & Distribution) | `references/sd.md` | Sales orders, pricing, delivery, billing, credit management, ATP/MTO |
| FI/CO (Finance) | `references/fico.md` | Document posting, exchange rates, document splitting, COPA, substitution, auto payment |
| PP (Production Planning) | `references/pp.md` | Production orders, BOM, routing, MRP, configurable BOM |
| WM (Warehouse Management) | `references/wm.md` | Transfer orders, transfer requirements, bin management, physical inventory |
| PM (Plant Maintenance) | `references/pm.md` | Equipment, functional location, maintenance orders, maintenance plans, serial numbers |
| QM (Quality Management) | `references/qm.md` | Inspection lots, usage decisions, quality notifications, inspection plans |
| VMS (Vehicle Management) | `references/vms.md` | IS-AUTO VELO objects, IDoc enhancements, SPRO configuration |
| System Integration | `references/integration.md` | PI/PO, IDoc, Proxy, OData, XML/JSON troubleshooting |
| Authorization | `references/auth.md` | AUTHORITY-CHECK, roles, SU53, authorization objects |
| Print | `references/print.md` | SmartForms, SAPscript, NACE message control |
| T-code Reference | `references/reference-tables.md` | Full-module T-code, key table, BAPI index |
| Troubleshooting Case Library | `references/troubleshooting.md` | CASE-001 ~ CASE-015, complete root-cause analysis |

### Typical Trigger Examples

- *"MIGO posting fails with 'Serial number already exists' — how to fix?"*
- *"PR00 condition type missing in SD pricing procedure — root cause?"*
- *"IDoc status 51 troubleshooting flow"*
- *"ABAP BAdI implementation steps"*

---

## sap-sto-create

An execution skill that creates STO (Stock Transfer Order) transfer orders in S/4HANA via the standard OData service `API_PURCHASEORDER_PROCESS_SRV`. When the issuing plant is an after-sales plant, it automatically attempts to create an outbound delivery via SAP JCo (`BAPI_OUTB_DELIVERY_CREATE_STO`).

**Key design**: enforces a mandatory two-step gate — `preview` (dry run) before `create` — to prevent accidental order creation.

### Tech Stack

- **Python** — CLI entry point and OData orchestration
- **Java / SAP JCo** — outbound delivery creation via RFC/BAPI
- **S/4HANA OData** — `API_PURCHASEORDER_PROCESS_SRV`

### Quick Start

```bash
# List available plant combinations
python3 scripts/sap_sto_cli.py plants

# Preview (dry run — always run this first)
python3 scripts/sap_sto_cli.py preview \
  --supply-plant P002 \
  --receiving-plant A002 \
  --material MAT-001:3 \
  --delivery-date 2026-05-30 \
  --batch-number BATCH001

# Create (requires --confirmed safety flag)
python3 scripts/sap_sto_cli.py create \
  --supply-plant P002 \
  --receiving-plant A002 \
  --material MAT-001:3 \
  --delivery-date 2026-05-30 \
  --batch-number BATCH001 \
  --confirmed
```

See [`skills/sap-sto-create/README.md`](skills/sap-sto-create/README.md) for full setup, environment configuration, and JCo library placement.

---

## Installation

```bash
git clone https://github.com/shrek-abaper/sap-functional-skill.git

# Install the knowledge skill
cp -r sap-functional-skill/skills/sap-trench-skill ~/.agents/skills/

# Install the execution skill
cp -r sap-functional-skill/skills/sap-sto-create ~/.agents/skills/
```

Claude Code discovers and loads skills automatically at conversation startup.

---

## Project Structure

```
sap-functional-skill/
└── skills/
    ├── sap-trench-skill/          # Knowledge skill — SAP field troubleshooting
    │   ├── SKILL.md               # Trigger layer (routing table + keywords)
    │   ├── README.md
    │   ├── CONTRIBUTING.md
    │   ├── evals/
    │   │   └── golden-set.yaml    # 7 Q&A eval cases
    │   └── references/            # 14 knowledge files
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
    └── sap-sto-create/            # Execution skill — STO order creation via OData
        ├── SKILL.md               # Trigger layer + tool routing
        ├── README.md
        ├── .env.example           # Environment config template
        ├── evals/
        │   └── evals.json
        └── scripts/
            ├── sap_sto_cli.py     # CLI entry point
            ├── requirements.txt
            └── lib/
                ├── create_sto_odata.py   # Core OData logic
                └── java/
                    ├── SapDeliveryCreator.java
                    ├── sapjco3.jar
                    └── lib/              # Platform-specific JCo native libs
                        ├── linux/
                        ├── macos/
                        └── windows/
```

---

## Contributing

Contributions of real SAP field experience are welcome. See [CONTRIBUTING.md](skills/sap-trench-skill/CONTRIBUTING.md) for the knowledge card format.

Every knowledge card follows a fixed structure: **Phenomenon → Root Cause → Solution → Experience Summary** — ensuring AI agents can accurately parse and reference the content.

---

## Compatible Platforms

Both skills follow the standard SKILL specification and are compatible with any supporting framework:

- [Claude Code](https://claude.ai/code)
- [OpenCode](https://github.com/opencode-ai/opencode)

---

## License

MIT — Knowledge should flow, not sleep.
