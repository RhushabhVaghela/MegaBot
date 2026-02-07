# MegaBot: Web Search Providers

MegaBot supports multiple web search providers, ranging from genuinely unlimited local metasearch to high-performance AI-optimized cloud APIs.

## 1. Local Unlimited Search (SearXNG)
- **Status**: Default
- **Benefits**: No API keys, no quotas, 100% private.
- **Config**: Set `active_provider: "searxng"`.

## 2. Perplexity (AI Reasoning Search)
- **Status**: Supported
- **Benefits**: Real-time AI synthesized answers with citations.
- **Config**:
  ```yaml
  web_search:
    active_provider: "perplexity"
    providers:
      perplexity:
        api_key: "pplx-..."
  ```

## 3. Brave Search
- **Status**: Supported
- **Benefits**: Privacy-focused native web index.
- **Config**:
  ```yaml
  web_search:
    active_provider: "brave"
    providers:
      brave:
        api_key: "..."
  ```

## 4. Google Custom Search
- **Status**: Supported
- **Benefits**: Comprehensive search results.
- **Config**:
  ```yaml
  web_search:
    active_provider: "google"
    providers:
      google:
        api_key: "..."
        cx: "..."
  ```

## 5. Tavily (AI Optimized)
- **Status**: Supported
- **Benefits**: Optimized for LLM agents (JSON only, clean content).
- **Config**:
  ```yaml
  web_search:
    active_provider: "tavily"
    providers:
      tavily:
        api_key: "..."
  ```

## 🧪 Switching Providers
Simply change the `active_provider` field in `mega-config.yaml` and restart MegaBot.
