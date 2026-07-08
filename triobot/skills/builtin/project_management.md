---
name: "pm-skills"
description: "6 project management agent skills and plugins for Trio, Trio, Trio CLI, Trio, OpenClaw. Senior PM, scrum master, Jira expert (JQL), Confluence expert, Atlassian admin, template creator. MCP integration for live Jira/Confluence automation."
version: 1.0.0
license: MIT
tags:
  - project-management
  - jira
  - confluence
  - atlassian
  - scrum
  - agile
agents:
  - trio-code
  - codex-cli
  - openclaw
---

# Project Management Skills

6 production-ready project management skills with Atlassian MCP integration.

## Quick Start

### Trio
```
/read project-management/jira-expert/SKILL.md
```

### Trio CLI
```bash
npx agent-skills-cli add alirezarezvani/trio-skills/project-management
```

## Skills Overview

| Skill | Folder | Focus |
|-------|--------|-------|
| Senior PM | `senior-pm/` | Portfolio management, risk analysis, resource planning |
| Scrum Master | `scrum-master/` | Velocity forecasting, sprint health, retrospectives |
| Jira Expert | `jira-expert/` | JQL queries, workflows, automation, dashboards |
| Confluence Expert | `confluence-expert/` | Knowledge bases, page layouts, macros |
| Atlassian Admin | `atlassian-admin/` | User management, permissions, integrations |
| Atlassian Templates | `atlassian-templates/` | Blueprints, custom layouts, reusable content |

## Python Tools

6 scripts, all stdlib-only:

```bash
python3 senior-pm/scripts/project_health_dashboard.py --help
python3 scrum-master/scripts/velocity_analyzer.py --help
```

## Rules

- Load only the specific skill SKILL.md you need
- Use MCP tools for live Jira/Confluence operations when available
