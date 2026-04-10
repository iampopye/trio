# Contributing to trio.ai

Thanks for your interest in contributing to trio.ai. Please read this entire document before opening a pull request.

> **trio.ai is an open source project owned and maintained by Karan Garg.**
> Contributions are welcome, but they must follow this process. PRs that don't follow these rules will be closed without review.

---

## Before You Start

### 1. Open an issue first

For anything beyond a typo fix or minor doc change, **open a discussion or issue first** to confirm the change fits the project's direction. This saves everyone time.

We don't accept PRs that:
- Rewrite large parts of the codebase
- Change the license, branding, or trademarks
- Add new providers, channels, or tools without prior discussion
- Bundle multiple unrelated changes
- Have no associated issue

### 2. Sign the CLA

All contributors must sign the **Contributor License Agreement (CLA)** before their first PR is merged. This is required to keep trio.ai's IP clean and allow future license changes.

The CLA bot will automatically prompt you on your first PR. By signing, you agree that:
- Your contribution is your own original work
- You grant Karan Garg (the project owner) a perpetual, worldwide, royalty-free license to use, modify, sublicense, and distribute your contribution
- You will not assert moral rights against the project
- Your employer (if any) has authorized the contribution

**No CLA = no merge.** No exceptions.

### 3. Read the Code of Conduct

Be respectful, professional, and constructive. Personal attacks, harassment, spam, or trolling result in an immediate ban.

---

## Pull Request Process

### 1. Fork and clone

```bash
git clone https://github.com/<your-username>/trio.git
cd trio
git remote add upstream https://github.com/iampopye/trio.git
```

### 2. Create a branch

Branch from `main`:

```bash
git checkout main
git pull upstream main
git checkout -b fix/short-description
```

Branch naming:
- `feat/` — new features
- `fix/` — bug fixes
- `docs/` — documentation only
- `refactor/` — code restructuring
- `test/` — test additions/updates
- `chore/` — maintenance

### 3. Make your changes

- **Keep PRs small and focused** — one feature or fix per PR
- **Don't reformat unrelated code** — only touch what you need to change
- **Match the existing style** — no new linters, no new conventions
- **Add tests** for new features and bug fixes
- **Update docs** if you change user-facing behaviour

### 4. Test locally

```bash
python -m pytest                     # Run all tests
trio doctor                           # Verify environment
trio agent -m "test"                  # Smoke test
```

All tests must pass before you submit. PRs with failing tests will be closed.

### 5. Commit

Use [Conventional Commits](https://www.conventionalcommits.org/):

```bash
git commit -m "fix: handle empty config in load_config()"
git commit -m "feat: add /skill list slash command"
git commit -m "docs: clarify provider setup in INSTALL.md"
```

**Sign your commits** (DCO):

```bash
git commit -s -m "fix: ..."
```

This adds a `Signed-off-by:` line that confirms you're the author.

### 6. Open the PR

- **Title**: clear and descriptive (`fix: handle empty config in load_config()`)
- **Description**: explain *what* and *why*. Reference the issue (`Closes #123`)
- **Checklist**: complete every item in the PR template
- **One PR = one concern**

### 7. Code review

A maintainer (currently only **@iampopye**) must approve before merge. We may:
- Request changes — address them, push, comment when ready
- Close the PR — if it doesn't fit the project direction
- Merge — usually after at least one round of review

**Do not push to main directly.** All changes go through PRs.

---

## What Gets Auto-Rejected

Your PR will be closed without review if it:

1. **Has no associated issue or discussion** (for non-trivial changes)
2. **Bundles unrelated changes** (split into separate PRs)
3. **Rewrites large portions of existing code** without prior agreement
4. **Adds new providers/channels/tools** without prior discussion
5. **Changes the license, branding, copyright headers, or trademarks**
6. **Modifies CI/CD, GitHub Actions, security policies, or release pipelines**
7. **Removes or weakens security controls** (guardrails, sandboxes, encryption)
8. **Includes generated AI code without your own review and testing**
9. **Has merge conflicts** that you haven't resolved
10. **Has failing tests or linting errors**
11. **Violates the CLA or Code of Conduct**
12. **Is spam, joke PRs, or self-promotion**

---

## What Makes a Good PR

✅ **Good**:
- Closes an existing issue
- One clear, focused change
- Tests added or updated
- Docs updated
- Clean commit history
- Passes CI
- Easy to review (under 400 lines of diff)

❌ **Bad**:
- "Refactored everything" with no issue
- 50 files changed for one feature
- No tests, no docs
- Mixed concerns ("fix auth and add new tool and refactor X")
- Force-pushed over review history
- AI-generated slop with no human review

---

## Restricted Areas

These parts of the codebase have **stricter review** and require explicit approval from @iampopye:

| Area | Why |
|------|-----|
| `trio/core/` | Core agent loop and routing logic |
| `trio/shared/guardrails.py` | Security filters — can't be weakened |
| `trio/shared/pairing.py` | Channel security |
| `trio/core/config.py` | Secrets encryption |
| `trio/web/app.py` | Web API auth and rate limiting |
| `trio/tools/shell.py` | Shell sandbox |
| `trio/tools/file_ops.py` | Filesystem sandbox |
| `trio/plugins/loader.py` | Plugin code loader |
| `trio_model/` | LLM training engine |
| `trio/providers/` | Provider integrations |
| `pyproject.toml` | Dependencies and packaging |
| `LICENSE`, `NOTICE` | Legal documents |

PRs touching these files may take longer to review and may be rejected if they don't fit the security/quality bar.

---

## Reporting Security Issues

**Never** report security vulnerabilities via public issues or PRs. See [SECURITY.md](SECURITY.md) for the responsible disclosure process. Email **karangarg.dev@gmail.com** directly.

---

## Development Setup

```bash
git clone https://github.com/iampopye/trio.git
cd trio
python -m venv .venv
source .venv/bin/activate          # Linux/Mac
.venv\Scripts\activate             # Windows
pip install -e ".[dev,model]"
trio doctor
```

Run the test suite:

```bash
python -m pytest -v
```

Run the security scanner:

```bash
pip install bandit
bandit -r trio/ trio_model/ --severity-level high
```

---

## Code Style

- **Python 3.10+ syntax** (use `|` instead of `Union`, `list[str]` instead of `List[str]`)
- **Type hints** on public functions
- **Docstrings** on classes and public functions
- **No new dependencies** without prior discussion
- **Match existing patterns** — don't introduce new ones

---

## Communication

- **Bug reports**: GitHub Issues (use the bug template)
- **Feature requests**: GitHub Discussions
- **Questions**: GitHub Discussions
- **Security**: karangarg.dev@gmail.com (private)
- **Sensitive matters**: karangarg.dev@gmail.com

---

## Credits

trio.ai is owned by **Karan Garg** ([@iampopye](https://github.com/iampopye)). Contributors are credited in commit history and the GitHub contributors page.

**Thank you for helping make trio.ai better.**
