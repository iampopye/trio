<!--
Thank you for contributing to trio.ai!

⚠️ READ BEFORE SUBMITTING ⚠️
1. PRs without a related issue/discussion will be CLOSED for non-trivial changes
2. You must sign the CLA on your first PR
3. PRs that bundle unrelated changes will be CLOSED
4. PRs that touch security-critical files require explicit owner approval
5. See CONTRIBUTING.md for the full rules
-->

## Related Issue

Closes #<!-- issue number — required for non-trivial changes -->

## Type of Change

<!-- Pick ONE -->
- [ ] 🐛 Bug fix
- [ ] ✨ New feature
- [ ] 📝 Documentation
- [ ] ♻️ Refactor (no behaviour change)
- [ ] 🧪 Test addition / update
- [ ] 🔧 Maintenance / chore

## Summary

<!-- One paragraph: what does this PR do and why? -->

## Changes

<!-- Bullet list of specific changes -->
-

## Testing

<!-- How did you test this? Be specific. -->
-

## Pre-Submission Checklist

- [ ] I have **read [CONTRIBUTING.md](../CONTRIBUTING.md)**
- [ ] I have **signed the CLA** (the bot will prompt me on first PR)
- [ ] My PR is **focused on one concern** (not bundling unrelated changes)
- [ ] I have **opened an issue first** for non-trivial changes
- [ ] My code **follows existing conventions** (no new linters, no reformatting)
- [ ] I have **added/updated tests** for my changes
- [ ] I have **updated documentation** if behaviour changed
- [ ] **All tests pass locally** (`python -m pytest`)
- [ ] **`trio doctor` passes** in my dev environment
- [ ] No **secrets, API keys, or personal data** are included
- [ ] No **AI-generated code** without my own review and testing

## Security Impact

<!-- Required if you touched any of these files -->
- [ ] This PR does NOT touch `trio/shared/guardrails.py`, `trio/tools/shell.py`, `trio/tools/file_ops.py`, `trio/core/config.py`, `trio/web/app.py`, `trio/plugins/loader.py`, or `trio/plugins/manifest.py`
- [ ] If it does, I have explained the security impact below:

<!-- Security explanation here, if applicable -->

## Breaking Changes

- [ ] This PR has **no breaking changes**
- [ ] If it does, I have documented the migration path:

<!-- Breaking change details, if applicable -->

---

By submitting this PR, I confirm:
- My contribution is my own original work
- I grant Karan Garg a perpetual license to use, modify, and distribute it
- I am not submitting code I don't have rights to
- I understand this PR may be closed if it doesn't follow the rules
