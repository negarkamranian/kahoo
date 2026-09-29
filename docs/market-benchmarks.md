# Kahoo — market benchmarks

Updated: 29 September 2026

## Summary

Kahoo should remain a discovery and trust layer, not become a checkout marketplace yet. The useful pattern across successful products is:

**intent → relevant shortlist → seller proof → low-friction handoff**

Search quality, current merchant data and a fast Instagram handoff matter more than adding social features or decorative UI.

## Benchmarks

| Platform | Evidence | What Kahoo should borrow |
|---|---|---|
| Etsy | 86.5M active buyers, 5.6M active sellers and $10.5B marketplace GMS in 2025. Its strategy combines search, human sellers and trust. [Annual report](https://investors.etsy.com/sec-filings/all-sec-filings/content/0001370637-26-000019/etsy-20251231.htm) | Strong query matching, visible seller identity and repeat-visit metrics. |
| Depop | 2025 GMS grew 36.3% to $1.075B; 92% was transacted in-app. 59% of sellers who sold also bought. [Annual report](https://investors.etsy.com/sec-filings/all-sec-filings/content/0001370637-26-000019/etsy-20251231.htm) | Visual merchant profiles and compact social proof without turning the feed into entertainment. |
| Pinterest | Reported 600M+ monthly users and 80B+ monthly searches in 2026. [Company announcement](https://investor.pinterestinc.com/news-and-events/press-releases/press-releases-details/2026/Pinterest-Announces-1-Billion-Strategic-Investment-from-Elliott-and-2-Billion-of-Near-Term-Share-Repurchases/default.aspx) | Visual similarity and saved collections after Kahoo has enough clean media. |
| TikTok Shop | US sales grew 120% year over year in early 2025; more than one-third of monthly US purchases in 2024 went to small businesses. [TikTok](https://newsroom.tiktok.com/tiktok-shop-is-where-shoppers-come-to-discover?lang=en) | Treat posts as product-discovery surfaces and keep the path to the seller short. |
| ShopMy | Reports 300K+ creators and 47K+ commission-paying brands; discovery uses fit and sales data rather than follower count alone. [ShopMy](https://shopmy.us/home/brands/discover) | Imported storefronts, natural-language matching and outcome-based merchant analytics. |

Company-reported scale and growth figures are directional; they are not comparable conversion-rate benchmarks.

## Kahoo flows

- **Shopper:** Persian query → category-aware results → merchant modal → Instagram.
- **Merchant:** Instagram OAuth → automatic profile/media import → suggested category → confirmation → scheduled refresh.

## Build next

1. Explain why every search result matched.
2. Show source and refresh time for trust data.
3. Add saved shops and recent searches.
4. Extract product, price and availability from captions for merchant confirmation.
5. Add visual search only after media freshness is reliable.

Measure search-to-modal rate, modal-to-Instagram rate, zero-result rate, query reformulation, repeat visits, OAuth completion and stale-merchant rate.
