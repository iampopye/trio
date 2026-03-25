---
name: github
description: Search GitHub repositories, manage issues and PRs
alwaysLoad: false
---

# GitHub Skill

You can help users interact with GitHub using shell commands via the `gh` CLI tool.

Common operations:
- Search repos: `gh search repos <query>`
- View repo: `gh repo view <owner/repo>`
- List issues: `gh issue list -R <owner/repo>`
- Create issue: `gh issue create -R <owner/repo> -t "title" -b "body"`
- View PR: `gh pr view <number> -R <owner/repo>`
- Clone repo: `gh repo clone <owner/repo>`

Always use the shell tool to execute these commands.
