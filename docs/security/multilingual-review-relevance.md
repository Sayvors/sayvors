# Multilingual Review Understanding (Arabic / English / Urdu)

## What it does

The review engine now identifies, understands, and answers in **Arabic, English, and
Urdu** (including Roman Urdu). Language identification, semantic intent, tenant
relevance, and factual answerability are kept as separate concerns throughout the
pipeline.

## Components

### Language identification — `app/core/language.py`

`detect_language(text)` returns `{code, script, confidence, is_rtl}`.

- Script detection (Arabic / Latin / CJK / other) is the first signal.
- For Arabic-script text, Arabic vs Urdu vs Persian is decided by **function-word
  frequency + character markers** (`ٹ ڈ ڑ ں ھ ے ک گ چ پ ژ`), never by script alone.
- For Latin text, English vs Roman Urdu is decided by function words
  (`kya, hai, nahi, bohat, ...`).
- Low-confidence verdicts defer to the LLM's label.

### Text normalization — `app/core/text.py`

Shared Unicode tokenizer (`normalize_text`, `tokens`, `term_hit`, `contains_phrase`).
Replaces the duplicated `[a-z0-9]` regexes that silently dropped every non-Latin
script. Used by relevance, domain vocabulary, offer matching, and the validator.

### Analysis — `app/modules/review_engine/understanding.py`

- Prompt now lists `en|ar|ur|ur-Latn|…` and explicitly distinguishes Urdu from
  Arabic (Urdu uses the Arabic script but is not Arabic).
- The blanket `analysis.language = "ar"` override for Arabic-script text was
  removed and replaced with the detector (authoritative for the Arabic-script
  family, where the LLM most often mislabels Urdu as Arabic).
- `_rule_based_analysis` uses the detector.
- `looks_like_question` covers Arabic, Urdu, and Roman Urdu interrogatives.

### Relevance — `app/modules/review_engine/relevance.py`

- Unicode tokenizer.
- Deterministic same-language match + English pivot (additive only).
- Cross-language fallback: `judge_relevance_llm()` receives the **original**
  review text and the tenant's business context (in whatever language it is
  configured in). No English translation is required as the foundation.
- Fail-closed: `off_topic` → `needs_review`; `uncertain` + concrete product +
  sparse domain → `needs_review` behind a config flag.

### Generation — `app/modules/review_engine/generator.py`

- `_LANGUAGE_NAMES` includes `ur` and `ur-Latn`.
- Urdu quality block (natural Urdu, `آپ`, no Hindi/Sanskritized vocabulary,
  Roman Urdu when the review is Roman Urdu).
- The Arabic dialect block is gated on `eff == "ar"` — previously an Urdu
  review with a Saudi dialect configured got contradictory instructions.

### Links — `app/modules/channels/review_reply.py`

- Link-line selection uses the shared detector, not `_ARABIC_SCRIPT`.
- Urdu and Roman Urdu handoff/sales lines added.
- Sales link restricted to `pricing_promotions` questions only; never
  appended to off-topic replies.

### Validator — `app/modules/review_engine/validator.py`

- `language_match` check (detector-based; script-only for short replies).
- Unicode overlap (replaces `[a-z]`-based counts).
- Off-topic echo guard.

### Config / UI — `channels/schemas.py`, `apps/web/.../settings/page.tsx`

- `reply_language` accepts `match|en|ar|ur|ur-Latn`.
- Settings UI offers Urdu and Roman Urdu; the Arabic dialect selector is
  disabled for non-Arabic languages.

## Tests

`tests/test_multilingual.py` — 28 tests covering language detection, question
detection, rule-based analysis language, relevance (Arabic/Urdu/English), and
three end-to-end pipeline tests (Urdu pizza → `needs_review`, Arabic hours
question, English praise) with a mocked LLM.

## Rollout

Phases A–C are implemented and tested. Remaining work:
- Hours/location sync (Localith `openingHours` → `LocationProfile`) for factual
  answerability of hours questions.
- Complaint aggregation (per-location, 30-day trend).
- Dialect auto-detection (currently tenant-configured).
- Full production rollout with metrics and a feature flag.