# Kahoo — product research

Updated: September 2026

## Product position

Kahoo should be a search and discovery layer for Iranian social shops: shoppers describe what they want, find relevant stores, inspect fresh content, and continue to the merchant. It should not imitate a full marketplace before it has reliable product, price, inventory, and fulfillment data.

## Benchmarks worth using

| Product / research | Useful pattern | Apply to Kahoo |
|---|---|---|
| [Torob](https://torob.com/) | Search-first marketplace with familiar category navigation | Keep search primary and the GS1 tree secondary. Preserve the compact, information-dense result style. |
| [ShopMy](https://shopmy.us/home/creators) | A creator gets one organized, shoppable storefront instead of scattered links | Give every merchant a stable Kahoo profile with collections and searchable descriptions. |
| [LTK](https://company.shopltk.com/en-gb/how-it-works-creators) | Existing social content becomes a shop; tagging and analytics create merchant value | Import content automatically, then add lightweight product tagging and merchant analytics. |
| [Pinterest visual search](https://help.pinterest.com/en/article/use-visual-search-features) | Discovery continues from an image through similar items and keyword refinements | Later, let users select a post or upload an image to find visually similar shops. Do this only after the catalog is large enough. |
| [GS1 GPC Browser](https://gpc-browser.gs1.org/) | Maintained Segment → Family → Class → Brick product hierarchy | Keep GS1 codes as the internal backbone, but show shorter Persian labels and only locally relevant branches. |

## Search direction

Baymard’s [2026 search benchmark](https://baymard.com/research-articles/ecommerce-search-query-types) reports that 56% of evaluated sites still have mediocre-or-worse search UX. The important gap is not the search box; it is understanding product type, features, themes, compatibility, and natural-language combinations.

For Kahoo:

1. Match merchant name, description, captions, products, and every parent category.
2. Maintain Persian aliases and spelling normalization: `ي/ی`, `ك/ک`, half-spaces, informal spellings, and common transliterations.
3. Show category scopes inside autocomplete, such as `لباس خواب در پوشاک`. Category-scoped suggestions improve product finding according to [Baymard’s scope research](https://baymard.com/research-articles/search-scope).
4. Explain each result with a short matched snippet: `مرتبط با: لباس زنانه، پوشاک راحتی`. Contextual snippets help users understand why a result appeared ([Baymard](https://baymard.com/blog/search-snippets)).
5. Never end at an empty page. Offer a broader category, corrected query, or close synonym.

## Merchant onboarding

The production flow should be Instagram OAuth → profile → avatar → recent media → suggested category → merchant confirmation. No username or image entry should be required.

Use Meta’s current [Instagram API collection](https://www.postman.com/meta/instagram/collection/6yqw8pt/instagram-api) as the implementation reference. It supports professional Business and Creator accounts. Public-page extraction is acceptable for this prototype, but it is not a dependable synchronization contract.

Trust rules:

- Store the source and last synchronization time for every merchant.
- Treat “verified by Kahoo” separately from Instagram’s verified badge.
- Never publish an OAuth-imported shop until its handle matches the authenticated account.
- Provide a visible “report incorrect shop” action.

## Recommended roadmap

### Now

- Autocomplete with query and category suggestions.
- Matched-reason snippets on store cards.
- Real Instagram OAuth and scheduled media refresh.
- Merchant page with description, categories, recent posts, city, and last-updated time.
- Remove or demote shops whose account disappears or becomes stale.

### Next

- Extract product candidates from captions: title, category, price, availability, and order method.
- Let merchants confirm extracted products in one tap instead of completing forms.
- Rank using relevance, freshness, profile completeness, and user engagement—not follower count alone.
- Add saved shops and recently viewed shops.

### Later

- Visual similarity search. Pinterest’s 2025 multimodal-search experiment reported materially higher shopping engagement and click-through than comparable text-only paths ([paper](https://www.pinterestcareers.com/media/554n4aaq/introducing-multi-modal-search-at-pinterest-a-new-user-experience.pdf)).
- Cross-posting to multiple marketplaces, inspired by the “write once, publish everywhere” model.
- Merchant analytics: discovery queries, profile visits, outbound clicks, and content freshness.

## What to measure

- Search-to-profile click rate.
- Zero-result rate and reformulation rate.
- Time from query to first merchant click.
- OAuth start-to-completion rate.
- Percentage of merchants refreshed within the target interval.
- Repeat visits and saved-shop return rate.

Establish a baseline before setting absolute targets; prioritize relative improvement per experiment.
