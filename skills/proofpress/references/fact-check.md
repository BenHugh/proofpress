# Fact-checking

The project's own rules are in `context/factcheck.md`: whether the site is YMYL, which claims must be verified, the approved sources, extra rules and the disclaimer. This file explains how to apply them. The rule is simple: **if it can't be verified today against an approved source, it doesn't go in the article.**

## What needs a citation

- Anything in the "claims that must be verified" list in `context/factcheck.md`.
- On a YMYL site: any statement about money, taxes, health, legal rights or obligations, safety, deadlines, thresholds, form numbers, official programmes or penalties.
- Facts about other products: features, prices, platforms (cite their own page).
- Statistics of any kind.

General, non-factual advice doesn't need a citation ("writing it down the same day is easier than reconstructing it a month later").

## Sources

- **Approved sources** are listed in `context/factcheck.md`. If none are listed, use official government or regulator sites and the first-party page of whatever is being described.
- Secondary sources (news, blogs, forums, AI answers) can point you to the official page but are never the citation for the rule itself.

## Procedure

1. List every claim the outline needs in `sources.md`.
2. For each, search and fetch the source page **in this run**. Record: claim, URL, page title, the relevant wording paraphrased, date checked.
3. Write the claim in your own words with the inline link. Don't copy long passages.
4. If the page is ambiguous, out of date, or can't be fetched: drop the claim, or say plainly that the reader should check with the agency or a professional. Never fill the gap from memory.
5. Numbers, caps, dates and years: say which year or period they apply to. If a rule is temporary or new, say so and when it ends, per the source.
6. Articles touching these topics end with the "Last reviewed" line and the disclaimer from `context/factcheck.md`.

## Region hygiene

- Don't mix regions in one sentence; the rules and the vocabulary differ.
- Use each region's own terms and currency in examples.

## Your product and regulated topics

Describe what the product does with the reader's information, never what it does for their legal or financial position, unless `context/product.md` says so explicitly. "A clean record you can hand to whoever does your taxes" is honest; "keeps you audit-proof" is not.
