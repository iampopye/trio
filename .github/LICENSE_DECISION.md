# trio.ai — License Strategy Decision

**Status**: 🟡 Decision pending (currently on MIT)
**Owner**: Karan Garg (@iampopye)
**Last reviewed**: 2026-04-10

---

## TL;DR

trio.ai is currently **MIT licensed**, the most permissive open source license. This means anyone can fork it, sell it commercially, rebrand it, and never contribute back. To prevent this, you should consider switching to **AGPL-3.0** (cleanest legal protection while staying fully open source) or **BSL 1.1** (lets you set commercial-use limits).

**Recommendation**: **Switch to AGPL-3.0** for v1.0 release. It's a one-line change in `LICENSE` and `pyproject.toml`, and it gives you legal recourse against commercial freeloaders without losing the "100% open source" badge.

---

## The Problem

You said:
> "esa na ho koi bhi aye apna push kre mera projject khda ka khde reh jae"
> "make sure no one comes and pushes their stuff and stalls my project"

There are **two separate concerns** here:

1. **Push protection** — preventing bad PRs from breaking the repo
   → Solved by branch protection + CODEOWNERS + CLA (already done)

2. **Code theft / commercial competitors** — preventing someone from forking trio.ai and selling it as their own product
   → **Not** solved by branch protection. Needs a license change.

This document is about #2.

---

## Current License: MIT

**What MIT allows anyone to do**:
- ✅ Fork the code
- ✅ Modify it
- ✅ Sell it as a commercial product
- ✅ Build a closed-source SaaS on top of it
- ✅ Rebrand it (as long as they don't use the name "trio.ai")
- ✅ Not contribute back

**What MIT prevents**:
- ❌ Removing your copyright notice from copies of the code
- ❌ Holding you liable for damages (no warranty)
- ❌ Using the name "trio.ai" without trademark (separate protection)

**Verdict**: MIT is great for trust and adoption, but provides almost zero protection against commercial exploitation. If you don't care about that, keep MIT.

---

## Option 1: Apache 2.0

**What changes**: Same as MIT but adds an explicit patent grant. Slightly more legal clarity.

**Verdict**: ✅ Good for protecting yourself from patent lawsuits, ❌ doesn't solve the freeloader problem.

**Use if**: You want MIT-like permissiveness with patent safety.

---

## Option 2: AGPL-3.0 (RECOMMENDED)

**What changes**: Anyone running trio.ai as a network service (SaaS) **MUST** make their modifications publicly available under AGPL-3.0. They can't keep their improvements proprietary.

**What it protects against**:
- ✅ Commercial competitors building closed-source SaaS on your code
- ✅ Companies forking trio.ai, improving it secretly, and competing with you
- ✅ Big tech embedding trio.ai in proprietary products

**What it still allows**:
- ✅ Anyone using trio.ai for personal/educational purposes
- ✅ Companies using trio.ai internally (no obligation to release)
- ✅ Anyone running modified versions, AS LONG AS they share the source
- ✅ Other AGPL projects integrating with trio.ai

**Real-world examples of AGPL projects**:
- **MongoDB** (originally AGPL, switched to SSPL)
- **Nextcloud** — major open source SaaS competitor protection
- **Mastodon** — federated social network
- **Grafana** — observability stack

**How to switch**:
1. Replace `LICENSE` file with the AGPL-3.0 text from https://www.gnu.org/licenses/agpl-3.0.txt
2. Update `pyproject.toml`:
   ```toml
   license = {text = "AGPL-3.0-or-later"}
   classifiers = [
     "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)",
   ]
   ```
3. Update copyright headers in all `.py` files (replace MIT line)
4. Add notice to README:
   > This program is free software: you can redistribute it and/or modify
   > it under the terms of the GNU Affero General Public License v3.0.
   > If you modify this program and make it available over a network, you
   > must make the complete source code available under the same license.

**Cost**: Free, but...

**⚠️ Caveat**: Once you switch FROM MIT, you can switch BACK. But contributors who submitted code under MIT may need to re-sign under AGPL. This is why we **need a CLA in place BEFORE** switching licenses. The CLA gives you the right to relicense their contributions.

---

## Option 3: BSL 1.1 (Business Source License)

**What changes**: trio.ai becomes "source available" with commercial restrictions. After a fixed time period (e.g., 4 years), each version automatically becomes Apache 2.0 / MIT.

**What it protects against**:
- ✅ Commercial use beyond a defined limit (e.g., "free for <10 users")
- ✅ Competitors selling trio.ai-based products

**Trade-offs**:
- ❌ NOT considered "open source" by OSI definition
- ❌ Some companies have legal policies that block BSL-licensed software
- ❌ Reduces community adoption and contributions
- ✅ Lets you sell commercial licenses for revenue

**Real-world examples**:
- **MariaDB** — original BSL author
- **CockroachDB**
- **Sentry** (switched to BSL → FSL)
- **Couchbase**
- **HashiCorp Terraform** (switched in 2023, caused major community backlash)

**How to set up**:
1. Replace `LICENSE` with BSL 1.1 template from https://mariadb.com/bsl11/
2. Define **Additional Use Grant**:
   > "You may use the Licensed Work for free, including for production use,
   > as long as your use is limited to internal evaluation or personal
   > non-commercial use. Commercial use beyond [10 users / $10K revenue]
   > requires a paid license."
3. Define **Change Date**: e.g., "4 years after each version's release date"
4. Define **Change License**: e.g., "Apache 2.0"

**Cost**: Free to set up. You'd need to handle commercial license sales yourself.

**Verdict**: Best for monetization, worst for community growth. The HashiCorp BSL switch in 2023 caused a major fork (OpenTofu) — a cautionary tale.

---

## Option 4: Dual License (AGPL + Commercial)

**What changes**: You release trio.ai under **two licenses simultaneously**:
- **AGPL-3.0** for everyone (free, open source)
- **Commercial License** for companies who don't want AGPL obligations

**How it works**: Companies that want to use trio.ai in a closed-source product can either:
- (a) Comply with AGPL (open-source their changes), or
- (b) Pay you for a commercial license (no obligations)

**Real-world examples**:
- **MySQL** (oracle, dual GPL + commercial)
- **Qt** (LGPL + commercial)
- **Sequel Pro**
- **Ghostscript** (AGPL + commercial)

**How to set up**:
1. Set primary license to AGPL-3.0 (Option 2 above)
2. Add `COMMERCIAL.md` describing the commercial license terms
3. Add a "Need a commercial license?" section to README pointing to your email
4. Optionally use a service like https://tidelift.com/ to monetize

**Cost**: Free to set up, but requires you to handle commercial license sales (or use Tidelift, which takes a cut).

**Verdict**: ✅ Best of both worlds. ✅ Maximum legal protection. ✅ Monetization path. ❌ More work to set up.

---

## Comparison Matrix

| Criterion | MIT (current) | Apache 2.0 | AGPL-3.0 | BSL 1.1 | Dual (AGPL + Commercial) |
|-----------|:-------------:|:----------:|:--------:|:-------:|:------------------------:|
| 100% open source | ✅ | ✅ | ✅ | ❌ | ✅ |
| OSI approved | ✅ | ✅ | ✅ | ❌ | ✅ |
| Prevents commercial freeloaders | ❌ | ❌ | ✅ | ✅ | ✅ |
| Allows monetization | ❌ | ❌ | ⚠️ | ✅ | ✅ |
| Easy to switch from MIT | — | ✅ | ✅* | ⚠️ | ✅* |
| Community-friendly | ✅ | ✅ | ⚠️ | ❌ | ⚠️ |
| Big-tech adoption | ✅ | ✅ | ⚠️ | ❌ | ⚠️ |
| Legal protection | ❌ | ⚠️ | ✅ | ✅ | ✅✅ |

*Requires CLA from all contributors first.

---

## My Recommendation

**Switch to AGPL-3.0** (Option 2) for v1.0 release. Reasons:

1. **Solves your core problem**: prevents commercial freeloaders without losing "open source" status
2. **One-line change**: just replace `LICENSE` and update `pyproject.toml`
3. **Doesn't affect personal/educational users**: trio.ai still free for individuals, students, hobbyists
4. **Future-proof**: you can always add a commercial license later (Option 4) if you want monetization
5. **Trending**: many AI projects are switching to AGPL (Mastodon, MinIO, etc.) precisely to prevent OpenAI / Google / Microsoft from absorbing their work

**When to switch**: After you have a CLA in place. The CLA is what gives you the legal right to relicense contributions, so set up the CLA first, then switch the license.

---

## Decision Action Items

If you agree with the AGPL-3.0 recommendation:

- [ ] **Step 1**: Set up CLA Assistant (see `REPO_PROTECTION.md` Step 5)
- [ ] **Step 2**: Wait until you have at least 1 CLA-signed contributor in the system (or just be the only contributor for now)
- [ ] **Step 3**: Replace `LICENSE` with AGPL-3.0 text
- [ ] **Step 4**: Update `pyproject.toml` license classifier
- [ ] **Step 5**: Update copyright headers in all `.py` files (script in `scripts/`)
- [ ] **Step 6**: Update `README.md` license section
- [ ] **Step 7**: Add migration notice to next release notes
- [ ] **Step 8**: Tag v1.0.0 with the new license

If you prefer a different option, document the choice and reasoning at the top of this file.

---

## Trademark Strategy (Always Required)

**Regardless of which license you pick**, you should ALSO:

1. Trademark "trio.ai" and "triobot" at IP India
2. File in Class 9 (software) and Class 42 (SaaS)
3. Cost: ₹18,000 for individual/startup
4. This is what stops anyone from using your name commercially, even if they fork the code

License protects code. Trademark protects brand. **You need both.**

See the Indian trademark filing guide in your earlier conversation history for step-by-step instructions.

---

## Questions?

This is a major decision. Before changing the license:

- Talk to a lawyer (especially if you have any existing contributors)
- Consider community impact (announce on Discussions before switching)
- Plan the migration carefully (CLA must come first)

**Reach out**: karangarg.dev@gmail.com
