# Scoring rubric (100 points)

The pass mark and the maximum number of rewrites come from the project settings (`quality.pass_mark`, default 80; `quality.max_rewrites`, default 2).

Score the current draft honestly. A score is only useful if a mediocre draft gets a mediocre number. For each criterion write the score, one line of evidence (quote the draft), and the concrete fix if it lost points.

## Hard fails (the draft fails regardless of total)

1. Any statement about the product that isn't supported by `context/product.md`, or contradicts its "does NOT exist" list. Includes wrong tier or platform labels, stated prices beyond the pricing line, and links other than the official ones.
2. Any claim in the topics listed in `context/factcheck.md` without an inline approved source checked during this run. (On a YMYL site, this includes any money, health, legal or safety claim.)
3. Any invented statistic, testimonial, quote, user count, rating, or "we tested" claim.
4. Wrong intent: the draft doesn't answer the brief's one question in the first 60 words, or delivers a different format than the SERP demands (e.g. no actual file on a file-intent keyword).
5. The scanner reports any hard failure.

## Weighted criteria

| # | Criterion | Points | What full marks looks like |
|---|---|---|---|
| A | Sounds like a human | 30 | Reads like the voice in `context/voice.md`. Varied rhythm, specific details, no pass-1 or pass-2 patterns. You couldn't point to a sentence and say "that's AI". |
| B | Product claims are true | 25 | Every product mention maps to a line in the product definition; tier and platform limits labelled; one honest limitation included; no overselling. (A false claim is already a hard fail; partial marks are for vagueness, overselling tone or missing labels.) |
| C | Answers the intent, helpfully | 15 | Short answer is correct and direct; sections cover what the SERP shows people need; the reader can act immediately; nothing padded. |
| D | Facts and sources | 10 | Claims cited to approved or first-party pages; region scope clear; last-reviewed line and disclaimer where needed. |
| E | Structure | 10 | Follows `article-structure.md`: title, short answer, longer answer, clear H2s, product section, 4 to 6 FAQs, CTA, internal links. |
| F | Originality / information gain | 5 | At least two of the brief's information-gain items delivered. |
| G | On-page SEO | 5 | Keyword in title, short answer and meta; meta 140 to 160 characters; no stuffing; descriptive anchors. |

## Scorecard format (`scorecard-N.md`)

```
Draft: draft-N.md
Hard fails: none | list each with the offending sentence
A Human voice: 24/30: "evidence". Fix: ...
B Product truth: 25/25: ...
C Intent: 13/15: ...
D Facts/sources: 9/10: ...
E Structure: 10/10
F Originality: 4/5: ...
G SEO: 5/5
Total: 90/100 → PASS | FAIL (needs ≥ pass mark and no hard fails)
Top fixes for next draft (if failing): 1. ... 2. ... 3. ...
```
