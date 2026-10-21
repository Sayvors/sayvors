# Conversation Categorisation

Every inbound conversation gets two things: a **category** (what it is
about) and a **priority** (how much it needs a human). The inbox ranks
on them and the tenant filters on them, so the rules have to mean the
same thing wherever the conversation came from — a WhatsApp thread and a
Google review are ranked by the same ruler.

`categorize_message()` in `app/modules/channels/service.py` is the only
writer.

## One priority scale

`urgent` > `high` > `normal` > `low`, for every source.

| Source | Rule | Category | Priority |
|--------|------|----------|----------|
| Google review | rating ≤ 1 | complaint | urgent |
| Google review | rating = 2 | complaint | high |
| Google review | rating = 3 | feedback | normal |
| Google review | rating ≥ 4 | feedback | low |
| Chat (WhatsApp / Instagram / Facebook) | contains a complaint keyword | complaint | high |
| Chat | contains an urgent keyword | important | urgent |
| Chat | otherwise | normal | normal |

A Google review carries a rating, which is the one honest signal about
how much it matters, and it is mapped onto the **same** scale the chat
path uses. A review with no rating falls through to the keyword rules.

The keyword lists are deliberately small (16 complaint words, 9 urgent
words) and split on whitespace. That is the known weak point: "my order
never arrived" reads as `normal`. Google reviews are triaged by the LLM
review engine (`app/modules/review_engine/`), which classifies properly —
the chat path has no equivalent yet.

## "Important" is derived, not stored

```python
is_important(priority, category)
    = priority in ("urgent", "high") or category == "complaint"
```

One rule, every source. A one-star Google review and an angry WhatsApp
customer are the same kind of thing: they need a human now. A five-star
review does not.

It is **derived** rather than stored because it is a question about the
conversation — storing the answer would mean three writers keeping it
in step with the priority and category they also write.

Note this is a different thing from the Leads board's "important"
(`Lead.priority`), which means "the AI could not resolve this thread"
and is set by AI-miss escalation. Two vocabularies, two meanings:
`ChannelMessage.priority` is about the content, `Lead.priority` is about
who is handling it.

## A Google reviewer gets their own thread

A Google reviewer has no phone number, so without an identity of their
own every review on a channel collapsed into the catch-all `unknown`
thread — one bucket, no reviewer names, nothing that could be flagged
or answered.

`_google_reviewer_key()` derives a namespaced identity from the
reviewer's Google profile URL, falling back to their display name and
then to the review id. The digest is stored in `contact_phone` (encrypted)
and `contact_phone_hash`, which is what the inbox groups threads by. The
`google:` prefix means it can never collide with a real phone number.

A reviewer who leaves three reviews is therefore one conversation.

## A Google review is not replyable from the inbox

`can_reply` is false for a Google review thread. A review is a public
post answered through the review-reply flow (`ReviewReply` + the reviews
worker), not through the inbox's message-send path — which would try to
send a WhatsApp message to the synthetic key.

## Overrides

`PATCH /api/v1/inbox/threads/{channel_id}/{contact_phone}/category`
sets the category and priority of every message in a thread, so the
tenant can correct the automatic guess. The threads endpoint accepts
`?category=`, `?priority=` and `?important=` filters.
