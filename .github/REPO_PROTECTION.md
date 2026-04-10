# trio.ai — Repository Protection Guide

This document explains how trio.ai's GitHub repository is protected against:
- Unauthorized code changes
- Malicious or low-quality PRs
- Force pushes / history rewriting
- Forks for commercial competitors
- Brand misuse

**Audience**: Repository owner (Karan Garg / @iampopye). Some steps require manual configuration in GitHub Settings.

---

## Protection Layers

| Layer | What it does | Status |
|-------|-------------|--------|
| 1. CODEOWNERS | Auto-requests owner review on every PR | ✅ Configured |
| 2. CLA bot | Forces all contributors to sign legal agreement | 🔧 Manual setup |
| 3. Branch protection | Blocks direct pushes to `main`, requires reviews | 🔧 Manual setup |
| 4. Signed commits | Verifies commit author identity | 🔧 Optional |
| 5. Required CI checks | Tests must pass before merge | 🔧 Manual setup |
| 6. Secret scanning | Auto-scans for leaked credentials | ✅ Free on public repos |
| 7. Dependabot | Auto-updates vulnerable dependencies | 🔧 Manual setup |
| 8. Security policy | Documents vulnerability reporting | ✅ SECURITY.md exists |
| 9. Trademark + License | Legal protection against forks | 🔧 External (IP India) |
| 10. Private dev branch | Internal work not exposed publicly | 🔧 Optional |

---

## Step-by-Step Setup

### Step 1 — Enable Branch Protection on `main`

This is the **most important** step. It prevents anyone (including you) from accidentally pushing broken code to `main`.

1. Go to **github.com/iampopye/trio/settings/branches**
2. Click **Add branch protection rule**
3. Branch name pattern: `main`
4. Enable these settings:

   - ☑ **Require a pull request before merging**
     - ☑ Require approvals: **1** (you, since you're the only owner)
     - ☑ Dismiss stale pull request approvals when new commits are pushed
     - ☑ Require review from Code Owners
     - ☑ Require approval of the most recent reviewable push

   - ☑ **Require status checks to pass before merging**
     - ☑ Require branches to be up to date before merging
     - Select: `pr-checks` (once you have CI set up)

   - ☑ **Require conversation resolution before merging**

   - ☑ **Require signed commits** (optional but recommended)

   - ☑ **Require linear history** (no merge commits — clean history)

   - ☑ **Do not allow bypassing the above settings**
     - This applies the rules to YOU as well — use a PR for everything

   - ☑ **Restrict who can push to matching branches**
     - Add only: `@iampopye`

   - ☑ **Allow force pushes**: ❌ DISABLED
   - ☑ **Allow deletions**: ❌ DISABLED

5. Click **Create**

> ⚠️ After enabling this, you can no longer `git push origin main` directly. You must:
> ```bash
> git checkout -b feat/my-change
> git push origin feat/my-change
> # Open a PR via GitHub
> # Self-approve and merge
> ```

### Step 2 — Disable Forking (Optional, Aggressive)

If you want to **prevent anyone from forking** trio.ai entirely:

1. Go to **github.com/iampopye/trio/settings**
2. Scroll to **Features**
3. Uncheck **☐ Allow forking**
4. Click **Save**

> ⚠️ This is aggressive. Most open source projects keep forking enabled because it's how contributions work. **Recommendation**: leave forking ENABLED but rely on license + trademark for legal protection.

### Step 3 — Set Up Dependabot

Auto-updates dependencies when CVEs are discovered.

1. Go to **github.com/iampopye/trio/settings/security_analysis**
2. Enable:
   - ☑ Dependabot alerts
   - ☑ Dependabot security updates
   - ☑ Dependabot version updates

3. Or commit `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    reviewers:
      - "iampopye"
```

### Step 4 — Enable Secret Scanning

Free for public repos. Catches leaked API keys, passwords, tokens.

1. Go to **github.com/iampopye/trio/settings/security_analysis**
2. Enable:
   - ☑ Secret scanning
   - ☑ Push protection (blocks commits with secrets BEFORE they're pushed)

### Step 5 — Set Up the CLA Bot

Forces every contributor to sign a Contributor License Agreement before their PR can be merged.

**Option A — CLA Assistant (free)**:
1. Go to https://cla-assistant.io/
2. Sign in with GitHub
3. Add a new CLA, paste the trio.ai CLA text
4. Link it to the `iampopye/trio` repo
5. Done. The bot now auto-prompts every PR.

**CLA template** (save as `CLA.md` in the repo):

```markdown
# trio.ai Contributor License Agreement

By submitting a contribution to trio.ai, I, the undersigned, agree to the
following:

1. I am the original author of this contribution, OR I have the legal right
   to grant the licenses below.
2. I grant Karan Garg (the project owner) a perpetual, worldwide,
   non-exclusive, no-charge, royalty-free, irrevocable copyright license to
   reproduce, prepare derivative works of, publicly display, publicly
   perform, sublicense, and distribute my contribution and any derivative
   works.
3. I grant Karan Garg a perpetual, worldwide, non-exclusive, no-charge,
   royalty-free, irrevocable patent license for any patents I hold that
   would be infringed by my contribution.
4. I agree not to assert moral rights against the project (where waivable
   by law).
5. If my employer has rights to my contribution, I have either:
   (a) received permission from my employer to make this contribution, or
   (b) my employer has waived such rights for this contribution.
6. I understand this agreement is governed by the laws of India and that
   courts in [Karan's jurisdiction] have exclusive jurisdiction.

Signed: <CONTRIBUTOR NAME>
GitHub: @<contributor>
Date: <YYYY-MM-DD>
```

### Step 6 — Set Up Required CI Checks

A ready-to-use workflow template is included in the repo at
**`.github/workflow-templates/pr-checks.yml.template`**.

To activate it:

```bash
mkdir -p .github/workflows
cp .github/workflow-templates/pr-checks.yml.template .github/workflows/pr-checks.yml
git add .github/workflows/pr-checks.yml
git commit -m "ci: enable pr-checks workflow"
git push origin main
```

> ⚠️ **Note**: Pushing files under `.github/workflows/` requires a token
> with the `workflow` scope. If `git push` fails with "OAuth App lacks
> workflow scope", run `gh auth refresh -s workflow` first, OR upload
> the file directly via the GitHub web UI (Add File → Create new file).

Here's what the workflow does:

```yaml
name: PR Checks

on:
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -e ".[dev]"
      - run: python -m pytest -v
      - run: pip install bandit && bandit -r trio/ trio_model/ --severity-level high

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install ruff
      - run: ruff check trio/ trio_model/
```

After committing this file, go to branch protection settings and add `test` and `lint` as required checks.

### Step 7 — Use a Private Development Branch (Advanced)

For work-in-progress features that you don't want public:

```bash
# Create a separate private repo for unreleased work
gh repo create iampopye/trio-internal --private

# Add it as a remote
cd trio
git remote add internal git@github.com:iampopye/trio-internal.git

# Push WIP work to private remote
git checkout -b wip/secret-feature
git push internal wip/secret-feature

# When ready to release, cherry-pick into public main
git checkout main
git cherry-pick <commit-hash>
git push origin main
```

> Alternative: keep one repo, use private branches with branch protection set to block public visibility. (GitHub doesn't support private branches in public repos directly — you need a separate private repo.)

---

## Legal Protection (License + Trademark)

Branch protection prevents bad PRs but **does NOT prevent forks or commercial competitors**. For that, you need:

### License Strategy

trio.ai is currently **MIT licensed**, which is the most permissive. Anyone can:
- Fork it
- Sell it as a commercial product
- Rebrand it
- Never contribute back

**To prevent commercial freeloaders**, consider switching to one of:

| License | Effect | Commercial use? |
|---------|--------|-----------------|
| **MIT** (current) | Anyone can do anything | Allowed |
| **Apache 2.0** | Same as MIT + patent grant | Allowed |
| **AGPL-3.0** | Anyone running it as a service must open-source their changes | Allowed but must contribute back |
| **BSL 1.1** | Free for non-commercial; commercial requires paid license | Restricted |
| **Custom commercial** | Pay for any use | Restricted |

**Recommendation**: Switch to **AGPL-3.0** or **BSL 1.1** if you want legal protection. See `LICENSE_DECISION.md` for the full analysis.

### Trademark Strategy

License only protects code. Brand protection requires a **trademark**:

1. File "trio.ai" and "triobot" as wordmarks at IP India
2. Class 9 (software) + Class 42 (SaaS)
3. Cost: ₹18,000 for individual/startup
4. Validity: 10 years (renewable)

Once registered, you can:
- Use ® symbol
- Send takedown notices to anyone using your name
- Block commercial competitors from calling their product "trio.ai"

See the [step-by-step Indian trademark guide in chat history] for details.

---

## Manual Setup Checklist

After committing this file, do these GitHub Settings actions:

- [ ] **Settings → Branches → Add rule for `main`** (Step 1)
- [ ] **Settings → Code security and analysis → Enable**:
  - [ ] Dependency graph
  - [ ] Dependabot alerts
  - [ ] Dependabot security updates
  - [ ] Secret scanning
  - [ ] Secret scanning push protection
- [ ] **CLA Assistant** (Step 5): https://cla-assistant.io/
- [ ] **Add `.github/workflows/pr-checks.yml`** (Step 6)
- [ ] **Restrict push access** (Step 1, sub-setting)
- [ ] **Optional: Disable forking** (Step 2)
- [ ] **Optional: Create `iampopye/trio-internal` private repo** (Step 7)

---

## What This Protects Against

| Threat | Protection |
|--------|-----------|
| Random PR breaks main | Branch protection + required reviews |
| Spam/joke PRs | PR template + auto-close rules in CONTRIBUTING.md |
| Malicious PR with hidden backdoor | CODEOWNERS + your manual review |
| Force-push to main | Branch protection (no force pushes allowed) |
| Accidental `git push main` by you | Branch protection (no direct pushes) |
| Leaked API key in commit | Secret scanning push protection |
| Vulnerable dependency | Dependabot |
| Someone uses "trio.ai" name commercially | Trademark (external) |
| Commercial fork | License change to BSL/AGPL (external) |
| Code theft for closed-source product | License change + trademark (external) |
| WIP code being public too early | Private dev repo (Step 7) |

---

## What This Does NOT Protect Against

- **Forks for personal/educational use** — anyone can clone and run trio.ai privately. This is what open source means.
- **Reading your code** — public repo means public code. You can't make it private without going closed-source.
- **Reimplementing your ideas** — no law prevents someone from building a similar product from scratch.
- **Foreign jurisdictions** — Indian trademarks only protect you in India. File internationally via Madrid Protocol if needed.

---

## Emergency Procedures

### Someone pushed bad code

1. Revert via PR (don't force-push):
   ```bash
   git revert <commit-hash>
   git push origin revert-branch
   # Open PR, merge
   ```

### A maintainer's account is compromised

1. Remove their access immediately:
   - **Settings → Access → Manage access → Remove**
2. Revoke all their access tokens
3. Audit recent commits and PRs from that account
4. Re-enable 2FA on your own account if not already

### A PR contains malicious code

1. Close the PR immediately (don't merge)
2. Block the contributor:
   - **Their profile → Block user**
3. Report to GitHub:
   - **Open PR → ... menu → Report content**

### Someone is using "trio.ai" name commercially

1. Document the infringement (screenshots, URLs)
2. If you have a registered trademark: file a takedown
3. Contact your IP lawyer
4. File complaint with the platform (GitHub, npm, PyPI, etc.)

---

## Need Help?

- **GitHub Branch Protection docs**: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- **CODEOWNERS docs**: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-security/customizing-your-repository/about-code-owners
- **CLA Assistant**: https://cla-assistant.io/
- **GitHub Security**: https://docs.github.com/en/code-security
