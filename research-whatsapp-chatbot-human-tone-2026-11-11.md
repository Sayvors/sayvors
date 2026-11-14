# Research Report: Making a WhatsApp AI Customer-Service Bot Sound Human (WhatsApp, Arabic merchants)

Date: 2026-11-11. Goal: concrete engineering plan for rewriting a WhatsApp AI support bot's reply prompt + post-processing.

## Executive Summary

"Robotic" is measurable, not vibes. Empirical corpora (Pangram; Wikipedia's AI-signs catalog; Kobak et al. 2025) show bots fail on identifiable markers: over-formal phrasing, markdown/bullets in chat, em-dashes, cheerful assistant openers ("Certainly!"), sycophancy, over-apologizing. The strongest known fix (documented first-hand in Klarna's case study) is not a better persona adjective but testable rules + a few-shot sample bank of good replies organized by customer emotional state, plus a logging loop that converts every observed failure into a concrete rule. For Arabic, the highest-impact decision is register mirroring: customers type in dialect (Gulf/Egyptian/Levantine/Maghrebi) and code-switch Arabic/English; replying in Modern Standard Arabic (MSA) is the #1 "robotic" signal reported in MENA-focused sources. Warmth helps (empirically supported), but over-humanizing backfires after failures; aim for warm-and-honest, never fake-human.

## Angle 1 - Linguistic markers that make a bot sound robotic

### Empirical data (AI-vs-human frequencies)

Pangram, "9 Signs of AI Writing, Backed by Data" (pangram.com/signs-of-ai-writing, retrieved 2026-11-11), measured millions of documents. Per 10k words, AI-vs-human multipliers:
- Markdown in plain text: 12x (bold 43x) - bold, ## headers, inline code where humans type plain text.
- AI phrases: 12x - "delve into" (45x), "In today's fast-paced world" (35x), "crucial to note" (22x), "navigate the tapestry of".
- Em dashes: 10x (human baseline ~5/10k; OpenAI ~45/10k, Anthropic ~32/10k, Gemini 3 Pro 3/10k).
- Bullet lists where prose is natural: 9x - "Where a human would write apples, oranges, and bananas, a model reaches for a line break and a dash."
- Triads / forced rule-of-three: 4x.
- "Not just X but Y" negative parallelism: 3x.
- AI-style openers: "Certainly! Here's" = 70x (0 humans vs 94 AI per 10k); "Sure! Here's a" = 18x; "Here's what you need to know" = 11x; "I'd be happy to" = 5x.
- Emoji choice, not count: white check mark 167x, keycap digits 61-129x, check 64x, rocket 26x; humans favor faces (smiley 0.6x, heart 0.2x).

Kobak et al., Science Advances 2025 (arXiv:2406.07016), "Delving into LLM-assisted writing": first large-scale word-frequency evidence that "delve", "realm", "underscore" surged post-ChatGPT. Follow-up (ransomnews.com, 2026): AI tells expire in ~18 months - "delve" fell 94% from peak while dash use doubled. Implication: keep the ban-list versioned and re-measured.

Wikipedia:Signs of AI writing (WP:AISIGNS, retrieved 2026-11-11) - the canonical, actively maintained catalog. Chat-relevant patterns: puffery ("stands as a testament", "pivotal moment", "evolving landscape"); superficial "-ing" padding (", highlighting its importance", ", ensuring a seamless experience"); negative parallelisms; forced triads; avoidance of plain "is/are" in favor of "serves as/acts as"; collaborative assistant-speak ("Certainly!", "I hope this helps", "You're absolutely right!"); hedging disclaimers; over-apologizing.
### Customer-service-specific robotic markers (support-industry sources)

Gorgias, "Make AI Sound Less Robotic in Customer Support" (updated 2026-03-27) - generic-to-human replacement table:
- "We apologize for the inconvenience." -> "Sorry about that, we're working on it now." (friendly) / "Apologies for the trouble, we're on it." (professional)
- "Your satisfaction is our top priority." -> "We want to make sure this works for you."
- "Please be advised..." -> "Just a quick heads up..."
- "Your request has been received." -> "Got it, thanks for reaching out."
- "I will now review your request." -> "Let me take a quick look."

Also flagged across sources: "As an AI...", over-formal greetings ("Dear valued customer"), sycophantic openers ("Great question!"), replies "written like a policy document read aloud", and the failed persona prompt "bubbly, kind, like a friend they turn to" which one internal reviewer described as "clearly a robot, and it's cringey that it wants to be my friend" (Ben Davies-Romano, "Making an AI assistant actually sound like Klarna", bendaviesromano.com, 2026 - first-hand case study by Klarna's Head of UX Content Design).

## Angle 2 - Human-like conversational tone in customer support (channel + Arabic)

### Message shape on chat/WhatsApp (conversation-design consensus)

- One idea per message bubble; 15-35 words optimal; >80 words drops read rates to ~68% and response rates to ~48%; >40 words forces in-bubble scrolling on mobile (conferbot; fuselabcreative 2026; bothero.ai: >90 words = -48% read-through). These numbers are vendor-reported - directional only.
- Split long answers into 2-3 shorter bursts, staggered ~400-700 ms to mimic typing; put any question or CTA in the LAST message (BotHero UX playbook).
- One question per message, never two (conferbot; also Anthropic's published Claude 4 system prompt: "avoid overwhelming the person with more than one question per response").
- Prose, not bullets, in chat. Anthropic's own system prompt: Claude "responds in sentences or paragraphs and should not use lists in chit chat", "avoids markdown in casual conversation", "it's fine for responses to be short, e.g. just a few sentences" (via Simon Willison, 2025-05-25).
- Contractions, active voice, first person, short sentences (IBM conversation-design workshop materials; Botpress conversation-design principles).
- Acknowledge before acting (grounding): "Okay, got it", "One sec, checking", "Let me take a quick look" (beconversive: Acknowledge -> Confirm -> Prompt pattern, mirroring conversational-grounding linguistics).
- Timing feels human: 1-2 second delays before "looking up" order info, before confirming refunds, before emotional replies (Gorgias).
- Use context: referencing the customer's order/history is one of the strongest human signals; ignoring it and forcing customers to repeat themselves is the biggest frustration driver (Gorgias; Klarna's key metric was a 25% drop in repeat inquiries).
- Erika Hall (Conversational Design): brevity + unpredictability make chat feel alive; bots that are "too needy, too chatty, and trying too hard" break the illusion. Keep one consistent voice.
### Arabic: dialect vs MSA - the decisive factor for our users

- Vendors saying "we support Arabic" almost always mean MSA, "the formal register of news broadcasts and official documents"; "virtually nobody uses MSA in everyday conversation". Customers type Gulf ("shlonkom" rather than "kayf halokom"), Egyptian, Levantine, or Maghrebi Arabic; MSA-only bots miss colloquial vocabulary, morphology, and mixed Arabic/English messages, and "even if the bot grasps the question, the answer reads like an academic manual instead of a supportive human agent" (RevoplyAI blog, Feb 2026).
- Empirical support: Aljuraid (TechRxiv preprint, 2026) compares a GPT-4-based Arabic chatbot answering MSA vs dialect prompts and finds materially different performance. Pangeanic: an Arabic AI system is not production-ready just because it scores well on MSA. AramcoWorld (2024): systems can translate into MSA but "fall short in responses" for natural conversation.
- Trust framing: in MENA "purchasing decisions rest on trust and personal relationships"; 74% of customers buy again more readily when supported in their native language, reportedly higher in Arabic markets (RevoplyAI, citing industry surveys).
- Practical rules emerging from these sources: (1) reply in the register the customer used - dialect gets dialect, formal Arabic gets simple MSA; (2) handle code-switching (Arabic + English in one sentence) without comment; (3) never ship a machine-translated English template as an MSA reply; (4) keep output RTL-safe, free of markdown artifacts.
- Emoji norms: Arab digital-media users use emoji as a social-presence tool (Aljasir, Social Science Computer Review, 2024); in Arabic tweets emojis carry irony, intensity, humor, parallel emotion (Alharbi, PMC 2023). Emoji use is normal and warm in Arabic chat - the failure mode is WHICH emoji: bots favor UI glyphs (checks, crosses, rockets, keycaps) at 24-167x human rates while humans favor faces (Pangram). Guidance: sparse face emojis matching the customer's own emoji density; never checklist-style emoji.

## Angle 3 - Prompt-engineering techniques that reliably make LLM output conversational

### Klarna's content-design system (best public first-hand account)

Source: bendaviesromano.com/klarna-ai-assistant (Ben Davies-Romano led UX content design on Klarna's AI assistant; outcomes: 2-min avg resolution, -25% repeat inquiries, ~$40M saved).
1. Adjectives are not instructions. "Bubbly, kind, like a friend" produced cringe. Replace with checkable rules ("Do not use contractions. Start every sentence with subject + verb. Use modal verbs like can. No passive voice.") - each testable against any output by anyone.
2. Reverse-engineer the gap: ask the model to describe the tone of a sample output, diff against intended tone; the delta IS the missing instruction - a specific rule, not a vaguer adjective.
3. Log every failure in one shape: observation | model output | desired output | the specific prompt change. That log becomes the working document.
4. Sample bank beats rulebook: ~8 pre-written exemplars tagged to customer emotional state teach tone faster than descriptions. Shared pattern: LEAD WITH THE FACT, FOLLOW WITH THE FEELING - the opposite of the unguided model, which apologizes first and buries the answer. Examples (from the case study, illustrative of the sample library):
   - Angry, third time asking -> "You've asked about this three times and haven't had a straight answer. Here's what's actually happening with your refund, and what I can do right now."
   - Anxious about money -> "Your payment is due on 14 March. If that's difficult, you can move it back by 14 days without a fee. Nothing happens to your account in the meantime."
   - Confused by jargon -> "A pre-authorisation isn't a charge. It's the shop checking the money is there. It disappears from your balance within 7 days."
   - Embarrassed, missed a payment -> "It happens. Your payment is 3 days late and there's no fee yet. Pay it today and nothing else changes."
   - Being told no -> "I can't change the delivery address once the order is placed. The shop can, though - here's how to reach them."
   Key technique: NAME the customer's situation ("You've asked three times") instead of performing sympathy ("I'm so sorry!!!"). "Be empathetic without being obsequious" gets nothing usable; show eight examples and the model reproduces the pattern.
5. One consolidated system prompt + AI-specific voice guidelines, separate from the human style guide: "a model needs rules stated as constraints... otherwise clear is just another adjective."
6. Metric that mattered: repeat-inquiry rate, not resolution time.
### Intercom Fin - public guidance-writing manual ("Fin Guidance best practices", intercom.com, retrieved 2026-11-11)

- Address the agent as "you", direct imperative; complete commands, no fragments.
- One objective per guidance entry; several simple rules beat one complex rule; avoid contradictions; cap total rules (Fin: 100) because too many rules degrade quality and speed.
- EVERY negative instruction must carry a positive alternative: bad = "When a customer is angry, do not apologise."; good = "When a customer is angry, do not apologise. Instead, [do X]."
- If/then/when structure with concrete examples; conditions beat vibes.
- Critical rules in caps: "NEVER tell the customer to uninstall and reinstall the app."
- Verbatim dictation vs tone guidance: dictated strings are used as-is and are NOT translated - for multilingual products, guide the tone and let the model phrase it in-language; add a glossary for fixed terms ("When replying in Spanish, refer to X as Y").
- Real length guidance from the docs: "sentences should be short, at most 1-2 sentences per paragraph and no more than 100 words per answer (unless absolutely necessary)... break paragraphs into sentences with a newline"; for channel char-limits: "NEVER exceed 1000 characters... It is better to have a short, incomplete answer under the limit."
- Voice exemplars: "Use plain language - use easy instead of frictionless"; empathy template plus "Feel free to use different variations of this example" (variation avoids template-feel).
- Known limitation worth copying into design: guidance is checked BEFORE retrieval, so "if you don't know, escalate" does not work; escalate on explicit rules instead.

### Claude 4 published system prompt (patterns to copy)

- Casual/empathetic mode: "keeps its tone natural, warm, and empathetic... responds in sentences or paragraphs and should not use lists in chit chat... In casual conversation, it's fine for Claude's responses to be short."
- Anti-sycophancy, near-verbatim: "Claude never starts its response by saying a question or idea or observation was good, great, fascinating, profound, excellent, or any other positive adjective. It skips the flattery and responds directly."
- Question discipline: doesn't always ask questions; max one per response.
- Length matching: "concise responses to very simple questions... thorough responses to complex and open-ended questions."
- Refusals without lectures: "If Claude cannot or will not help... it does not say why or what it could lead to, since this comes across as preachy and annoying."
- Inside prose, lists are written in natural language ("some things include: x, y, and z") with no bullets, numbering, or newlines.
- Anthropic's character essay (June 2024): warm but honest - "I don't just say what I think [people] want to hear"; warmth without pretending to be human; people should know they are talking to a model, not an infallible person.
- Anthropic research: Claude still shows sycophancy in ~9% of guidance-seeking chats - sycophancy must be actively suppressed in the prompt; it will not disappear on its own.

### Negative vs positive instructions

Consensus across Fin docs and Anthropic practice: pair every ban with the replacement behavior; few-shot examples outperform descriptions; examples are the number-one prompting technique. Klarna: rules alone produce "correct and lifeless" copy - rules + sample bank together are the system.
## Angle 4 - Warmth vs competence, and the human-likeness uncanny valley

- Warmth and competence both drive outcomes: perceived warmth + competence raise purchase/recommendation expectations (Li et al., European Journal of Marketing 58(12), 2024, chatbot anthropomorphism); warmth + ability + social presence positively affect consumer responses (Deng, SAGE Open, 2025, n=303). Warmth signals are worth engineering.
- But human-likeness raises the stakes of failure: Crolic et al., "Blame the Bot: Anthropomorphism and Anger in Customer-Chatbot Interactions" (2021, ~1170 citations) - after a service failure, a more human-like bot is blamed AS IF HUMAN, producing more anger; the authors explicitly caution that anthropomorphism is not always beneficial (not a simple uncanny-valley story, but expectations-violation).
- Uncanny-valley findings: human-likeness can reduce trust and purchase intent, moderated by familiarity (Song & Han, IJHCI 2024, ~361 cites); increasing human-likeness can elicit negative affect in customers (Ekkelenkamp et al., 2021); response quality drives intent to switch to human agents (Cheng et al., 2022).
- Klarna's observed failure mode was trying too hard: friend-persona prompts read as cringey; Erika Hall: "too needy, too chatty, and trying too hard."
- Gorgias suggests LIGHT intentional imperfection - varied sentence lengths, occasional fragments, filler like "kinda", "just checking", "I think", idioms - while warning not to overdo it, and to be transparent: "AI that pretends to be human... backfires fast." Disclose on request, on escalation, and for consequential actions (refunds/cancellations).
- Right balance (synthesis): warm, casual, specific, honest. No fake typos, no fake "typing like a human", no forced jokes - and no "As an AI" disclaimers either. Answer first, acknowledge second, never fake capabilities ("let me call you back" from a bot is a lie). Short honest disclosure when asked: "I'm the store's AI assistant - I'll sort this out or get a human on it."

## Angle 5 - Best open-source repos / guides to reuse

1. haidrrrry/humanize-ai-writing (GitHub, MIT, 26 stars) - anti-AI-slop system prompt + Claude skill + zero-dependency CLI checker (bin/humanize-check.mjs) that scans text for AI tells with line numbers and fixes; 12 rules: no banned vocab (delve, tapestry, testament, underscore, additionally...), no fake significance, no present-participle padding, no negative parallelism, no forced triads, em-dash discipline, plain copulas (is/are, not "serves as"), specifics over hedging, no hollow conclusions, vary sentence rhythm, "allow repetition over synonym-cycling". Includes before/after EXAMPLES.md, CI templates, and an honest-scope note ("don't overcorrect; avoid CLUSTERS of tells"). Most directly reusable for our post-processing linter.
2. Wikipedia:Signs of AI writing (WP:AISIGNS) - the canonical, dated, actively maintained field guide with "words to watch" lists per pattern; best source for building a versioned ban-list. CC BY-SA (the repo above adapts it).
3. x1xhlol/system-prompts-and-models-of-ai-tools (GitHub) - full leaked system prompts of production AI tools (largest such repo); useful to see how real products phrase tone and formatting rules at scale. Alternative: jujumilk3/leaked-system-prompts.
4. anthropics/skills (official Anthropic repo) - reference for SKILL.md structure (front-matter, progressive disclosure into references/), includes skills/brand-guidelines and (in anthropics/knowledge-work-plugins) a brand-voice skill; good template if we ship our "WhatsApp voice" as an installable skill file.
5. SabrinaRamonov/prompts -> humanize_ai_writing.md (GitHub) - practical humanizer rewrite prompt; a decent scaffold, less rigorous than #1.
## Concrete engineering plan (for the WhatsApp reply prompt + post-processing)

### A. System prompt rewrite - structure, not adjectives
1. Role + honesty (2 lines): "You are the store's assistant on WhatsApp. Warm, quick, plain-spoken. If asked, say plainly that you are the store's AI assistant. Never claim to have done something you have not done."
2. Register rule (highest priority): "Reply in the same Arabic the customer wrote in: dialect -> same dialect, mixed Arabic/English -> same mix, formal Arabic -> simple MSA. NEVER answer a dialect message in news-style MSA." (Logic sourced from RevoplyAI, Pangeanic, Aljuraid 2026.)
3. Shape rules (testable): default 1-3 short sentences, <= 60 words; prose only; no bullets, no markdown, no headers, no numbered steps unless giving sequential instructions; if info is long, send the key fact + offer the rest ("Want the details?").
4. Openers/closers: never open with an apology, flattery, or "Certainly!"; answer first. Acknowledge before acting ("got it", "one sec"). Max one question per message.
5. Fact-before-feeling rule (Klarna): lead with the answer; acknowledge the situation in concrete terms ("you've asked twice already") instead of performing sympathy.
6. Emoji rule: at most one face emoji and only if the customer uses emojis; never checklist glyphs; never exceed the customer's own emoji density.
7. Banned list + preferred replacements (below); pair every ban with its substitute (Fin best practice).
8. Sample bank (the core): 8-12 few-shot exemplar exchanges written natively per target dialect, covering: angry-repeat, refund-anxious, confused-terminology, in-a-hurry, suspected fraud, missed payment, telling-no-with-alternative, delighted-close. Tag each with situation + tone.
9. Anti-sycophancy verbatim: never start by praising the question; skip "Great question" / "sual al-rai'" style flattery in any language; answer directly.
10. Uncertainty + handoff: one plain sentence about what you don't know; offer the human handoff once; no over-apologizing, no lectures.

### B. Ban-list -> replacement table (seed; re-measure quarterly)
English bans (all sourced above): "I apologize for the inconvenience" / "Certainly!" / "Sure! Here's" / "I'd be happy to" / "Great question" / "As an AI" / "Please be advised" / "Your satisfaction is our top priority" / "Your request has been received" / "I will now review" / delve, tapestry, testament, seamless, robust, landscape, "not just X but Y" / "In conclusion" / em dashes / bullets in chat / checklist emoji and keycaps.
English prefers: "Sorry about that, on it" / "Got it" / "One sec, checking" / "Let me take a quick look" / "Here's what's happening: ..." / "That one's on us, here's the fix".
Arabic bans (illustrative - MUST be validated by native speakers per market): default opener "natathir an al-izaj" in full MSA on every reply; "azizi al-ail al-karim" (dear valued customer); news-register MSA replies to dialect messages; formal closing blessings on every message.
Arabic prefers (illustrative): Gulf "tamam, la-hza wa-ashayyik lak"; Egyptian "mashi, thanya wa-ard alayk"; Levantine "hadir, dawiqa bas"; empathy-by-naming-situation rather than repeated "sorry". Final wording per dialect should come from native speakers and from real merchant chats in our own corpus.

### C. Post-processing pipeline (deterministic, after the LLM)
1. Lint (port of humanize-check.mjs, Arabic-aware): flag banned n-grams, markdown symbols, bullet characters at line start, em dashes, checklist emoji, MSA-register reply when the customer message was dialect (cheap lexical classifier), > 60 words, > 1 question mark, opener-apology patterns.
2. Fix or regenerate: automatic string replacements for mechanical items; LLM re-ask for register/shape violations ("rewrite: same information, chat voice, no lists").
3. Chunk + pace: split into 1-2 bubbles at clause boundaries; deliver with 400-700 ms stagger (or computed typing time); question last.
4. Variation guard: never reuse the same acknowledgment opener across consecutive turns (Fin docs: use variations); small rotation over an approved synonym set.
5. Failure log, Klarna-style: observed | produced | wanted | rule change; feed weekly into prompt + ban-list updates (tells expire in ~18 months; re-measure).

### D. Metrics
North-star: repeat-inquiry rate (Klarna's -25% metric). Secondary: CSAT, human-handoff rate, median reply length, ban-list hit rate, register-match rate (dialect in -> dialect out).
## Sources

| # | Source | Date | Type / notes |
|---|---|---|---|
| 1 | Pangram, "9 Signs of AI Writing, Backed by Data" (pangram.com/signs-of-ai-writing) | retrieved 2026-11-11 | Empirical corpus data |
| 2 | Wikipedia:Signs of AI writing (WP:AISIGNS) | retrieved 2026-11-11, actively maintained | Canonical tell catalog, CC BY-SA |
| 3 | Kobak et al., "Delving into LLM-assisted writing in biomedical publications", Science Advances / arXiv:2406.07016 | 2024/2025 | Peer-reviewed |
| 4 | Ransom News, "AI writing tells expire in 18 months" (ransomnews.com) | 2026 | Corpus analysis; single source, flagged |
| 5 | Ben Davies-Romano, "Making an AI assistant actually sound like Klarna" (bendaviesromano.com/klarna-ai-assistant) | 2026 | First-hand production case study |
| 6 | Intercom, "Fin Guidance best practices" (intercom.com/help/en/articles/10560969) | updated 2026 | Official product docs |
| 7 | Simon Willison, "Highlights from the Claude 4 system prompt" | 2025-05-25 | Analysis of primary system prompts |
| 8 | Anthropic, "Claude's character" | 2024-06-08 | Primary |
| 9 | Anthropic, "How people ask Claude for personal guidance" (sycophancy ~9%) | retrieved 2026-11-11 | Primary research |
| 10 | Gorgias, "Make AI Sound Less Robotic in Customer Support" | created 2026-01-14, updated 2026-03-27 | Industry guide with phrase-replacement table |
| 11 | RevoplyAI, "Arabic AI Customer Support: Why Most Chatbots Fail" | 2026-02 | Vendor blog, MENA-focused; directionally consistent with 12-13 |
| 12 | Pangeanic, "Arabic AI Evaluation: Why Modern Standard Arabic Is Not Enough" | retrieved 2026-11-11 | Vendor engineering blog |
| 13 | Aljuraid, TechRxiv, GPT-4-based Arabic chatbot: MSA vs dialect prompts | 2026 | Preprint, flagged; also AramcoWorld 2024 feature |
| 14 | Alharbi, "The pragmatic functions of emojis in Arabic tweets" (PMC10010193) | 2023 | Peer-reviewed |
| 15 | Aljasir, "Emoji as a Social Presence Tool Among Arab Digital Media Users" (SAGE) | 2024 | Peer-reviewed |
| 16 | Conversation-design sources: conferbot masterclass (2026), fuselabcreative chatbot UX guide (2026), bothero.ai UX playbook, Botpress "Conversation AI Design" (after Erika Hall), beconversive, chatbot.com best practices | 2025-2026 | Industry consensus; message-length numbers are vendor-reported, directional |
| 17 | Crolic et al., "Blame the Bot: Anthropomorphism and Anger in Customer-Chatbot Interactions" | 2021 | Peer-reviewed, ~1170 citations |
| 18 | Li et al., "How customers respond to chatbot anthropomorphism", European Journal of Marketing 58(12) | 2024 | Peer-reviewed |
| 19 | Deng, "The Effect of Perceived Warmth, Competence, and Social Presence", SAGE Open | 2025 | Peer-reviewed, n=303 |
| 20 | Song & Han, "Uncanny Valley Effects on Chatbot Trust, Purchase..." IJHCI; Ekkelenkamp 2021; Cheng et al. 2022 | 2024/2021/2022 | Peer-reviewed |
| 21 | GitHub: haidrrrry/humanize-ai-writing; x1xhlol/system-prompts-and-models-of-ai-tools; jujumilk3/leaked-system-prompts; anthropics/skills; anthropics/knowledge-work-plugins; SabrinaRamonov/prompts | retrieved 2026-11-11 | Repos |
| 22 | NYT, "The Single Word That Explains Why Chatbots Sound So Robotic" (greetings pragmatics) | 2025-08-28 | Paywalled; claim rests on headline/snippet only - a lead, not a citation |

## Confidence notes
- Klarna outcome numbers, chat-length read-rate percentages, and the 74% native-language stat are single-source industry claims - directional, not settled.
- Arabic ban/prefer examples and dialect openers in section B are model-generated illustrations, explicitly NOT sourced - validate with native speakers per market.
- Aljuraid is a preprint.
- The NYT article was not readable (paywall); included only as a lead.

## Open questions
- No public production system prompt exists for Fin or Klarna's assistant itself (their documentation and the first-hand case study are public); leaked-repo prompts cover other products.
- Emoji norms for merchant-customer WhatsApp conversations specifically (vs tweets/social media) lack dedicated studies.
- Whether customers prefer simple MSA for formal topics (refunds, complaints) even when they write in dialect is unresolved in the sources - A/B test it.
