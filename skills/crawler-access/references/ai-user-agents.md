# AI User-Agent Token Map

Last verified: 2026-08-30

This is the token map the `robots-citation-bot-block` and `robots-wildcard-catchall` checks use. The core distinction: **citation/search bots** fetch pages to answer user questions live (blocking them removes the brand from that assistant's answers), while **training-only bots** collect data to train models (blocking them is a legitimate, common opt-out that we never flag as a problem).

## Citation / search bots (blocking HURTS citation — flag when Disallowed)

| Token | Operator | Role |
|---|---|---|
| `OAI-SearchBot` | OpenAI | Surfaces sources in ChatGPT search results |
| `ChatGPT-User` | OpenAI | Live fetch when a user's ChatGPT prompt needs a page |
| `PerplexityBot` | Perplexity | Indexes pages for Perplexity answers |
| `Perplexity-User` | Perplexity | Live user-initiated fetch |
| `Claude-SearchBot` | Anthropic | Search indexing behind Claude's citations |
| `Claude-User` | Anthropic | Live user-initiated fetch |
| `Googlebot` | Google | Core index behind Google Search + AI Overviews |
| `Bingbot` | Microsoft | Core index behind Bing + Copilot |
| `Applebot` | Apple | Index behind Siri / Spotlight / Apple Intelligence |
| `Amazonbot` | Amazon | Index behind Alexa / Amazon answers |
| `DuckDuckBot` | DuckDuckGo | Index behind DuckDuckGo / DuckAssist |

## Training / bulk-corpus bots (blocking is a LEGITIMATE opt-out — never flag as a problem)

| Token | Operator | Role |
|---|---|---|
| `GPTBot` | OpenAI | Training-data crawler |
| `Google-Extended` | Google | Gemini training opt-out token (no fetch of its own) |
| `CCBot` | Common Crawl | Open crawl corpus used for training |
| `anthropic-ai` | Anthropic | Legacy training crawler token |
| `ClaudeBot` | Anthropic | Bulk training/corpus crawler (not a live citation fetcher) |
| `meta-externalagent` | Meta | Bulk training/corpus crawler for Meta AI |
| `Applebot-Extended` | Apple | Training opt-out extension of Applebot |
| `Bytespider` | ByteDance | Training crawler |

## Rules for the checks
- Only citation bots produce a problem finding. A training-only Disallow is at most informational — do NOT report it as a defect.
- Resolve each verdict with Protego's `can_fetch(homepage, token)` (RFC 9309 group selection + longest-match), and quote the resolved per-bot verdict in the evidence.
- Only run these checks when the homepage is a real 200 with genuine content (guards against flagging deliberately private/staging sites).
- Token matching is case-insensitive and prefix-based on the product token; Protego handles this. See `robots-semantics.md`.
