---
name: deep_research
---

# Deep Research

Produce thorough, cited research reports from multiple web sources.

## When to Use

- Researching any topic in depth
- Competitive analysis, technology evaluation, or market sizing
- Due diligence on companies, investors, or technologies
- Any question requiring synthesis from multiple sources
- User says "research", "deep dive", "investigate", or "what's the current state of"

## Workflow

### Step 1: Understand the Goal

Ask 1-2 quick clarifying questions:
- "What's your goal -- learning, making a decision, or writing something?"
- "Any specific angle or depth you want?"

If the user says "just research it" -- proceed with reasonable defaults.

### Step 2: Plan the Research

Break the topic into 3-5 sub-questions. Example for "Impact of AI on healthcare":
- What are the main AI applications in healthcare today?
- What clinical outcomes have been measured?
- What are the regulatory challenges?
- What companies are leading this space?
- What's the market size and growth trajectory?

### Step 3: Execute Multi-Source Search

For each sub-question:
- Use `web_search` with 2-3 different keyword variations
- Mix general and news-focused queries
- Aim for 15-30 unique sources total
- Prioritize: academic, official, reputable news > blogs > forums

### Step 4: Deep-Read Key Sources

For the most promising URLs, fetch full content using `web_search` or `file_ops`. Read 3-5 key sources in full for depth. Do not rely only on search snippets.

### Step 5: Synthesize and Write Report

```markdown
# [Topic]: Research Report
*Generated: [date] | Sources: [N] | Confidence: [High/Medium/Low]*

## Executive Summary
[3-5 sentence overview of key findings]

## 1. [First Major Theme]
[Findings with inline citations]
- Key point ([Source Name](url))
- Supporting data ([Source Name](url))

## 2. [Second Major Theme]
...

## Key Takeaways
- [Actionable insight 1]
- [Actionable insight 2]
- [Actionable insight 3]

## Sources
1. [Title](url) -- [one-line summary]
2. ...

## Methodology
Searched [N] queries. Analyzed [M] sources.
Sub-questions investigated: [list]
```

### Step 6: Deliver

- **Short topics:** Full report in chat
- **Long reports:** Executive summary + key takeaways in chat, full report saved to file

## Quality Rules

1. **Every claim needs a source.** No unsourced assertions.
2. **Cross-reference.** If only one source says it, flag as unverified.
3. **Recency matters.** Prefer sources from the last 12 months.
4. **Acknowledge gaps.** If you couldn't find good info, say so.
5. **No hallucination.** If you don't know, say "insufficient data found."
6. **Separate fact from inference.** Label estimates, projections, and opinions clearly.

## Examples

```
"Research the current state of nuclear fusion energy"
"Deep dive into Rust vs Go for backend services"
"Research the best strategies for bootstrapping a SaaS business"
"Investigate the competitive landscape for AI code editors"
```
