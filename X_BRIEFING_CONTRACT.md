# Private market-context companion

The existing X briefing producer adds one UTF-8 JSON attachment to its existing
private email, named `portfolio-market-context-YYYY-MM-DD.json` (briefing date in
Singapore). It preserves the existing briefing, recipients, schedule and send
guards. This contract changes neither trading rules nor the portfolio engine.

Only generic code and this contract may enter the public repository. Real
companions, message metadata, commentary, PDFs and screenshots stay private:
local ignored `data/`, ephemeral runner files and the existing private mailboxes.
No rendered content is uploaded as GitHub Actions artifacts.

## Version 1

The JSON object has exactly these top-level keys:

```json
{
  "schema_version": 1,
  "privacy": "private",
  "status": "complete",
  "briefing_date": "YYYY-MM-DD",
  "market_session": "YYYY-MM-DD",
  "window_start_utc": "ISO-8601 with timezone",
  "cutoff_utc": "ISO-8601 with timezone",
  "generated_at_utc": "ISO-8601 with timezone",
  "developments": [
    {
      "title": "Short development, at most 55 characters",
      "event_time_utc": "ISO-8601 with timezone",
      "summary": "What changed, at most 280 characters",
      "interpretation": "Evidence-based interpretation or uncertainty, at most 160 characters",
      "portfolio_relevance": "Qualitative transmission to named exposures, at most 160 characters",
      "affected_tickers": ["existing model ticker"],
      "confidence": "corroborated",
      "sources": [
        {
          "url": "https://original-source.example/article",
          "publisher": "Source name",
          "published_at_utc": "ISO-8601 with timezone",
          "type": "primary"
        }
      ]
    }
  ]
}
```

- `market_session` is the latest completed NYSE session at the cutoff, including
  holidays and early closes. `briefing_date` is the cutoff's Singapore date.
- The window must cover that session's close and span at most 36 hours. Generation
  follows the cutoff. All source publications and event timestamps precede cutoff;
  each event falls within the window. Post-close events are labelled separately
  by the consumer and cannot explain the preceding close.
- Include 1–3 developments, ranked by material portfolio relevance, with at most
  180 words across titles, summaries, interpretations and relevance fields.
- Confidence is `corroborated`, `reported` or `uncertain`. Corroborated requires
  at least two independently originated sources; syndicated duplicates do not
  count. Source type is `primary`, `market_data`, `report` or `social`.
- Each development has 1–3 original HTTPS source links, no credentials or private
  mailbox links. Do not include images, full articles, recipient names/addresses,
  credentials, instructions or executable markup. Quotes should be avoided.
- `affected_tickers` contains at most eight existing model identifiers. Broad
  commodities are not treated as pure oil exposure. Use an empty list for general
  context. The consumer supplies current holdings and official contribution data.
- Do not include estimated portfolio P&L, portfolio weights, risk shares, assumed
  trade triggers, proposed trades or unsupported causal explanations. Preserve
  unverified claims as uncertain; omit unverified event-calendar times.
- If adequate source evidence is unavailable, omit the companion and report the
  exception through the existing briefing process. Never recycle yesterday's JSON.
- Validate JSON, dates, source links and word limits before attaching. Confirm the
  existing email contains both the PDF and the correctly named JSON before send.

## Consumer

The morning job searches its existing Gmail inbox read-only for the configured
sender, subject prefix and exact attachment name. It checks sender authentication,
session, cutoff, age, schema and bounds, then uses the companion only in the
private email/PDF. Missing, malformed or mismatched context does not hold up a
fresh quantitative report; the report states that market context is unavailable.
An unavailable quantitative report retains the existing freshness gate and delay
notice. The market note never replaces official NAV or attribution.

The producer runs Monday-Saturday around 07:00 Singapore time, including the
Friday US close for the Saturday portfolio review. Generate the companion from
the existing briefing evidence only: at most three developments and 180 words,
without a second research run. Missing context is never replaced with stale news.
