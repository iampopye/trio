---
name: sales_funnel
description: Map conversion funnels, identify drop-off points, quantify friction, and recommend optimizations with revenue impact estimates
alwaysLoad: false
---

# Sales Funnel Analysis and Optimization

Map the complete conversion path from first visit to purchase, identify drop-off points, quantify friction, and recommend specific optimizations with revenue impact estimates.

## When to Use

- Analyzing a website's conversion funnel
- Identifying where visitors drop off
- Optimizing pricing pages, signup flows, and checkout
- Quantifying the revenue impact of funnel improvements

## Phase 1: Funnel Discovery

### Identify Funnel Type

| Funnel Type | Typical Steps | Key Metric |
|-------------|---------------|------------|
| Lead Gen | Landing -> Form -> Thank you -> Nurture -> Sales call | Lead-to-close rate |
| SaaS Trial | Homepage -> Pricing -> Signup -> Onboarding -> Upgrade | Trial-to-paid rate |
| SaaS Demo | Homepage -> Features -> Demo request -> Sales call | Demo-to-close rate |
| E-commerce | Product page -> Cart -> Checkout -> Upsell | Cart-to-purchase rate |
| Webinar | Opt-in -> Confirmation -> Reminder -> Live -> Offer | Webinar-to-sale rate |
| Content | Blog -> Email capture -> Nurture -> Premium -> Subscribe | Reader-to-subscriber rate |

### Map Every Step

For each page, document:
- URL, page type, primary action, next step
- Exit points (where users might leave)
- Friction elements (anything that slows or confuses)
- Trust elements (anything that builds confidence)

## Phase 2: Page-by-Page Scoring

Score each page on 5 dimensions (0-10):

| Dimension | What to Evaluate |
|-----------|------------------|
| **Clarity** | Is the page's purpose immediately obvious? |
| **Continuity** | Does it logically continue from the previous step? |
| **Motivation** | Does it give enough reason to take the next action? |
| **Friction** | How easy is it to complete the desired action? (10 = frictionless) |
| **Trust** | Are there adequate trust signals for this stage? |

### Common Drop-Off Fixes

**Homepage:**
- Unclear value prop -> Rewrite headline with specific outcome
- No clear CTA -> Single primary CTA above fold
- Slow load time -> Optimize images, defer non-critical JS

**Pricing Page:**
- Price shock -> Add value framing before prices
- Too many options -> Reduce to 3 plans, highlight recommended
- No social proof -> Add customer quotes near each plan
- Missing FAQ -> Address top 5 pricing objections

**Signup/Registration:**
- Too many fields -> Reduce to 3 or fewer
- No progress indicator -> Add step counter
- Social login missing -> Add Google/social SSO

**Checkout:**
- Surprise shipping costs -> Show shipping early
- Required account creation -> Guest checkout option
- Limited payment options -> Add PayPal, Apple Pay

## Phase 3: Funnel Metrics

### Key Metrics

```
Conversion Metrics:
  Visitor -> Lead: [X]% (benchmark: 2-5%)
  Lead -> MQL: [X]% (benchmark: 15-30%)
  MQL -> Opportunity: [X]% (benchmark: 30-50%)
  Opportunity -> Customer: [X]% (benchmark: 20-40%)
  Overall: [X]% (benchmark: 0.5-3%)

Revenue Metrics:
  Average Order Value (AOV): $[X]
  Customer Lifetime Value (LTV): $[X]
  Customer Acquisition Cost (CAC): $[X]
  LTV:CAC Ratio: [X]:1 (target: 3:1+)
  Revenue Per Visitor (RPV): $[X]
```

### Revenue Impact Calculation

```
RPV = Monthly Revenue / Monthly Visitors

Example:
  10,000 visitors x 2% conversion x $100 AOV = $20,000/month
  Improve to 2.5%: $25,000/month = $60,000/year lift
```

### Benchmarks by Funnel Type

| Funnel Type | Good | Great | Elite |
|-------------|------|-------|-------|
| Lead Gen form | 3-5% | 5-10% | 10-20% |
| SaaS Free Trial | 2-5% | 5-10% | 10-15% |
| Trial to Paid | 10-15% | 15-25% | 25-40% |
| E-commerce | 1-3% | 3-5% | 5-8% |
| Cart to Purchase | 50-60% | 60-70% | 70-80% |
| Demo to Close | 15-25% | 25-40% | 40-60% |

## Phase 4: Optimization Recommendations

### Prioritization Matrix

| Priority | Impact | Effort | When |
|----------|--------|--------|------|
| P1 (Do Now) | >10% lift | <1 day | This week |
| P2 (Plan) | >10% lift | 1-5 days | This month |
| P3 (Schedule) | 5-10% lift | <1 day | This month |
| P4 (Backlog) | 5-10% lift | 5+ days | This quarter |

### Funnel-Stage Optimizations

**Top of Funnel:** Headline A/B testing (10-30% lift), social proof placement (5-15%), page speed (5-20%)

**Middle of Funnel:** Case studies (10-20% lift), interactive demos (15-30%), retargeting sequences (10-25%)

**Bottom of Funnel:** Pricing page redesign (10-25%), checkout friction reduction (5-15%), risk reversal (10-20%), cart abandonment recovery (5-15% of abandoned)

**Post-Purchase:** Onboarding sequence (10-20% churn reduction), upsell on thank-you page (5-15% AOV lift), referral program (5-15% new customers)

### Pricing Page Audit Checklist

- [ ] Headline frames value, not cost
- [ ] 3 plans (or 3 + enterprise)
- [ ] One plan highlighted as recommended
- [ ] Annual pricing shown first with savings
- [ ] Features are benefit-oriented
- [ ] Social proof near pricing
- [ ] FAQ addresses top pricing objections
- [ ] Money-back guarantee prominently displayed
- [ ] CTA buttons use action language

## Phase 5: Email Integration

```
Funnel Stage          -> Email Sequence
------------------------------------------
Lead (opted in)       -> Welcome sequence (5-7 emails)
Engaged Lead          -> Nurture sequence (6-8 emails)
Trial User            -> Onboarding sequence (5-7 emails)
Inactive Trial        -> Re-engagement (3-4 emails)
Churned Customer      -> Win-back (3-4 emails)
```

## Output Structure

Deliver analysis covering:
1. Executive Summary with top 3 recommendations and revenue impact
2. Visual funnel map with conversion rates at each step
3. Page-by-page analysis with scores and fixes
4. Revenue impact calculations
5. Prioritized optimization recommendations
6. Pricing page assessment
7. Email nurture integration plan
