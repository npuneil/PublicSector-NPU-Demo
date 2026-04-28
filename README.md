# Public Sector Hybrid AI Demo 🏛️

A showcase application demonstrating hybrid on-device + cloud AI for public sector agencies, running on the Intel NPU via Microsoft Foundry Local with optional Azure OpenAI cloud integration. Runtime decisioning automatically routes requests based on privacy, connectivity, and cost.

## On-Device AI Prototypes & Sample Code

### Overview

This repository contains prototypes, demos, and sample code that illustrate patterns for building on-device AI solutions. The content is provided for educational and demonstration purposes only to help developers explore ideas and implementation approaches.

This repository does not contain Microsoft products and is not a supported or production-ready offering.

### Prototype & Sample Code Disclosure

- All code and demos are experimental prototypes or samples.
- They may be incomplete, change without notice, or be removed at any time.
- The contents are provided "as-is," without warranties or guarantees of any kind.

### No Product, Performance, or Business Claims

- This repository makes no claims about performance, accuracy, productivity, efficiency, cost savings, reliability, or security.
- Any example outputs, screenshots, or logs are illustrative only and should not be interpreted as typical or expected results.

### AI Output Variability

- AI and machine-learning outputs may be non-deterministic, incomplete, or incorrect.
- Example outputs shown here are not guaranteed and may vary across runs, devices, or environments.

### Responsible AI Considerations

- These samples are intended to demonstrate technical patterns, not validated AI systems.
- Developers are responsible for evaluating fairness, reliability, privacy, accessibility, and safety before using similar approaches in real applications.
- Do not deploy AI solutions based on this code without appropriate testing, human oversight, and safeguards.

### Data & Fictitious Content

- Any names, data, or scenarios used in examples are fictitious and for illustration only.
- Do not use real personal, customer, or confidential data without proper authorization and protections.

### Third-Party Components

- The repository may reference third-party libraries or tools.
- Use of those components is subject to their respective licenses and terms.

### No Support

Microsoft does not provide support, SLAs, or warranties for the contents of this repository.

### Summary

By using this repository, you acknowledge that it contains illustrative prototypes and sample code only, not supported or production-ready software.

---

## Quick Start

```powershell
# First time:
Setup.bat          # or: .\Setup.ps1

# Every time:
StartApp.bat       # opens browser to http://localhost:5000
```

## Prerequisites

- **Windows 11 Copilot+ PC** with Intel Core Ultra NPU
- **Python 3.10+**
- **Foundry Local** installed (`winget install Microsoft.FoundryLocal`)
- **Azure OpenAI** (optional, for hybrid cloud features)

## Hybrid Architecture

This demo implements a **runtime decisioning engine** that evaluates each request and routes it to the optimal processing location:

| Signal | Result |
|--------|--------|
| PII detected (SSN, phone, email, address, DOB) | → **Local only** (on-device) |
| Content marked sensitive | → **Local only** |
| Module policy (e.g., Disaster Response) | → **Local only** |
| Cloud unavailable / offline | → **Local only** |
| Large input (>3000 chars) | → **Local only** |
| Clean query + cloud available | → **Cloud** (Azure OpenAI) |
| Uncertain / default | → **Local only** (fail-closed) |

## Intel NPU Optimization

- **WMI-based silicon detection** — correctly identifies Intel Core Ultra
- **NPU-first model chain**: phi-4-mini → phi-3.5-mini → phi-3-mini-4k → qwen2.5-1.5b
- **Automatic warmup** on Intel (safe to pre-load, unlike QNN on Snapdragon)
- **CPU fallback** when no NPU model is available

## Modules

| Tab | Description | Routing Policy |
|-----|-------------|---------------|
| **Home** | Overview of hybrid AI for public sector | — |
| **Counter Service Copilot** | Citizen inquiry handling — front desk & call center | Cloud after PII-safe check |
| **Policy & Ordinance Analyzer** | Document analysis — summarize, extract, assess | Local-first; cloud for deep analysis |
| **Disaster Response** | Field briefings — offline situation reports & checklists | **Always local** |
| **Permit / Inspection** | Structured field extraction & report drafting | Local-first; cloud for analytics |
| **Hybrid Dashboard** | Routing decisions, cost savings, PII interceptions | — |

## Cloud Configuration (Optional)

```powershell
$env:AZURE_OPENAI_ENDPOINT = "https://your-resource.openai.azure.com"
$env:AZURE_OPENAI_KEY = "your-api-key"
$env:AZURE_OPENAI_DEPLOYMENT = "your-deployment-name"
```

The app works fully local without cloud configuration. When Azure OpenAI is configured, the header shows "Cloud Ready" and eligible requests can route to the cloud.

## Demo Experience

See `START_HERE.txt` for setup instructions and `DEMO_SCRIPT.txt` for a 90-second executive demo walkthrough.

**Key demo moments:**
1. **PII Interception** — Type a phone number or SSN in Counter Service → watch it force local
2. **Airplane Mode** — Turn off WiFi → Disaster Response still works perfectly
3. **Hybrid Routing** — Clean query routes to cloud; sensitive query forces local
4. **Cost Projection** — Dashboard calculator shows agency-scale savings

## Privacy & Security

- PII detection runs locally before any routing decision
- Fail-closed: if uncertain, always process locally
- No raw prompts or citizen data stored in telemetry — metadata only
- Routing decisions logged with audit reason codes
- Server-side enforcement — client cannot bypass PII checks
