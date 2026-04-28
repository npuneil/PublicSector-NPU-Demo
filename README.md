# Public Sector — On-Device AI Showcase 🏛️

A showcase application demonstrating hybrid on-device + cloud AI capabilities for public sector agencies, running on the NPU (Neural Processing Unit) via Microsoft Foundry Local with optional Azure OpenAI cloud routing. Optimized for Snapdragon X (QNN runtime).

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

- **Windows 11 Copilot+ PC** with Snapdragon X NPU
- **Python 3.10+** (ARM64-native recommended for Snapdragon)
- **Foundry Local** installed (`winget install Microsoft.FoundryLocal`)
- **Azure OpenAI** (optional — for hybrid cloud routing)

## Snapdragon X Optimization

This app is optimized for ARM64 Snapdragon X devices:
- **WMI-based silicon detection** — correctly identifies Snapdragon under x64 emulation
- **No warmup on Snapdragon** — QNN runtime loads on first real request
- **NPU-first model chain**: qwen2.5-1.5b → phi-3-mini-4k → phi-3.5-mini → qwen2.5-7b
- **CPU fallback** when no NPU model is available

## Features

| Tab | Description |
|-----|-------------|
| **Home** | Overview of on-device AI for public sector |
| **Counter Service Copilot** | AI-assisted citizen service counter with PII detection routing |
| **Policy & Ordinance Analyzer** | Analyze municipal policies, bylaws, and ordinances |
| **Disaster Response** | Emergency response planning and coordination assistant |
| **Permit & Inspection** | Building permit and inspection workflow assistant |
| **Hybrid Dashboard** | Live metrics showing local vs. cloud routing decisions |

## Architecture

- **Privacy-first routing** — PII detection routes sensitive requests to on-device NPU
- **Fail-closed design** — defaults to local processing when cloud is unavailable
- **Hybrid decisioning engine** — complexity and sensitivity determine NPU vs. cloud

## Demo Experience

See `START_HERE.txt` for setup instructions and `DEMO_SCRIPT.txt` for a guided demo walkthrough.

**The key demo moment:** Show how PII-containing requests automatically stay on-device while non-sensitive complex queries route to cloud. Toggle airplane mode — everything keeps working locally.
