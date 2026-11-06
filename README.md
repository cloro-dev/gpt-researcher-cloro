# gpt-researcher-cloro

[cloro](https://cloro.dev/?utm_source=gpt-researcher-cloro&utm_medium=byok) retrievers for
[GPT Researcher](https://github.com/assafelovic/gpt-researcher). The package adds two retrievers:

| `RETRIEVER` | cloro endpoint | Returns | Credits per search |
|---|---|---|--:|
| `cloro` | `POST /v1/monitor/google` | Google organic results (about 10 links per search) | 5 |
| `cloro_aimode` | `POST /v1/monitor/aimode` | The Google AI Mode answer, then the sources it cites | 6 |

GPT Researcher (0.16.1 or later) finds the retrievers through the `gpt_researcher.retrievers`
entry point. You do not change GPT Researcher.

## Setup

1. Get an API key at [dashboard.cloro.dev](https://dashboard.cloro.dev/api-keys?utm_source=gpt-researcher-cloro&utm_medium=byok).
   The free plan includes 500 credits each month.
2. Install the package in the same Python environment as GPT Researcher:

```bash
pip install gpt-researcher-cloro
export CLORO_API_KEY="your-cloro-key"
export RETRIEVER=cloro            # or cloro_aimode, or cloro,cloro_aimode
```

You can combine the retrievers with built-in retrievers, for example `RETRIEVER=cloro_aimode,arxiv`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `CLORO_API_KEY` | unset | Required. Sent as `Authorization: Bearer <key>`. |
| `CLORO_COUNTRY` | `US` | ISO 3166-1 alpha-2 country code for the Google or AI Mode location. |

## Behaviour

`cloro`:

- Each result is `{"title", "href", "body"}`. `body` is the Google snippet, cut to 500 characters.
  The retriever sets `requires_scraping = True`, so GPT Researcher scrapes each page.
- One search returns one page of Google results. `MAX_SEARCH_RESULTS_PER_QUERY` above 10 gives no more results.
- With `query_domains`, the query gets `site:` filters joined with `OR`.
- Results with an empty link or a Google redirect (`google.com/goto`) link are skipped.

`cloro_aimode`:

- The first result is the AI Mode answer (Markdown) under `raw_content`. GPT Researcher uses this text
  without a scrape. Its `href` is the Google AI Mode URL for the query
  (`https://www.google.com/search?udm=50&q=...`), so the report cites it as Google AI Mode.
- The next results are the sources that the answer cites. They have no `raw_content`, so GPT Researcher
  scrapes them. The retriever sets `requires_scraping = False` for this reason.
- `max_results` counts the answer and the sources together.
- `query_domains` is accepted but not applied.
- An AI Mode answer can take 15 seconds or more. The request timeout is 180 seconds.

Both retrievers:

- Each search is one cloro request. With the default `MAX_ITERATIONS=3`, a `research_report` makes
  5 searches per retriever (1 initial search, 3 sub-queries and the original query). That is 25 credits
  with `cloro` and 30 credits with `cloro_aimode`. Other report types can make more searches.
- A missing key, a network error, an HTTP error (for example `INSUFFICIENT_CREDITS`) or a response that
  cannot be read is logged and gives `[]`. One failed provider does not stop a research run.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv build
```

The tests replace `requests.post` with a stub and do not call the cloro API.

## License

MIT
