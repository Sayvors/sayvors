# Google review → reply → ticket / sales lead

This document describes the implemented flow from a Google Business Profile
review to either a **review ticket** or a **WhatsApp sales lead**.

> **SERP meaning:** Sayvors reads reviews through the Google Business Profile
> API. It does not scrape the rendered Google search results page.

## 1. End-to-end flow

```mermaid
flowchart LR
    A([Customer leaves a Google review]) --> B[Reviews worker polls the connected Google location]
    B --> C{Is this a new or edited review?}
    C -- No --> Z1[Nothing changes]
    C -- Yes --> D[Store inbound review and enqueue analytics event]

    D --> E[AI reads the review text]
    E --> F[Extract category, subcategory, intent, sentiment, urgency, customer request]
    F --> G[Apply needs_attention and handoff policy]

    G --> H{Needs attention?}
    H -- Yes: complaint, refund, negative, high or urgent --> I[Create ReviewIssue]
    I --> J[Assign per-tenant ticket number TK-...]
    J --> K{Private resolution recommended?}
    K -- Yes --> L[Mint 6-character handoff code]
    K -- No --> M[No handoff code]

    H -- No: praise or neutral --> N[Create unticketed ReviewIssue]
    H -- No: pricing, plan or product question --> O[Keep unticketed]

    L --> P[Generate the public Google reply]
    M --> P
    N --> P
    O --> Q{Sales or information question?}
    Q -- Yes --> R[Append generic WhatsApp sales link without a ticket code]
    Q -- No --> S[No WhatsApp link]
    P --> R
    P --> S

    R --> T{Approval policy}
    S --> T
    T -- Approval mode or rating below min_rating_auto --> U[Queue reply for merchant approval]
    T -- Otherwise --> V[Publish reply publicly on Google]

    U --> W[Merchant approves]
    W --> V

    V --> X{Reviewer clicks the WhatsApp link?}
    X -- Ticket link --> Y[WhatsApp opens with handoff code prefilled]
    X -- Sales link --> ZA[WhatsApp opens a normal conversation]
    X -- No --> ZB[Reviewer may continue interacting with the public listing]
```

## 2. Classification and `if / else` decision tree

```mermaid
flowchart LR
    A[Review text] --> B{Intent?}

    B -- Refund request --> C[request_refund]
    B -- Complaint --> D[complaint]
    B -- Asks a question --> E[ask_question / information_request]
    B -- Suggests a change --> F[request_change]
    B -- Praises --> G[praise]
    B -- Other --> H[report_problem / ask_question]

    C --> I{Attention rule}
    D --> I
    H --> I
    E --> J{Commercial question?}
    F --> J
    G --> K[Positive praise only]

    I -- High or urgent, negative sentiment, complaint or refund --> L[needs_attention = true]
    I -- Otherwise --> M[needs_attention = false]

    J -- Pricing, plans, Premium, availability or product information --> N[Generic WhatsApp sales link]
    J -- No buying or information intent --> O[Public reply only]

    K --> P[No ticket and no WhatsApp link]
    M --> Q{Sales or information question?}
    Q -- Yes --> N
    Q -- No --> O

    L --> R[Ticket TK-...]
    R --> S{Ticket handoff eligible?}
    S -- Yes --> T[Handoff code + code-bearing WhatsApp link]
    S -- No --> U[Ticket without a handoff link]
```

### Attention rules

```text
needs_attention = true when:
    priority is high or urgent
    OR sentiment is negative
    OR intent is complaint
    OR intent is refund request

A positive praise-only review cannot be escalated into a ticket.
The star rating is a co-input; it is never the classifier or link gate.
```

## 3. Which link is used?

```mermaid
flowchart LR
    A[Public Google reply] --> B{WhatsApp link enabled and number connected?}

    B -- No --> C[Reply without a WhatsApp link]
    B -- Yes --> D{Ticket handoff code exists?}

    D -- Yes: problem or complaint --> E[Append code-bearing ticket link]
    E --> E1["https://wa.me/NUMBER?text=HANDOFF_CODE"]

    D -- No --> F{Sales, pricing or plan question?}
    F -- Yes --> G[Append generic sales link]
    G --> G1["https://wa.me/NUMBER"]

    F -- No: praise or neutral feedback --> H[No link]
```

| Review situation | Ticket | Handoff code | WhatsApp behavior |
|---|---:|---:|---|
| Complaint, refund, unresolved service problem | Yes | Yes | Agent opens the ticket with full context |
| High-priority problem on a 5-star review | Yes | Yes | Agent opens the ticket with full context |
| “Great service, what does Premium cost?” | No | No | Normal WhatsApp sales conversation; becomes a lead |
| Product availability or plan information question | No | No | Normal WhatsApp sales conversation; becomes a lead |
| Praise only | No | No | Public reply only |
| Neutral feedback with no request | No | No | Public reply only |

## 4. Google reply publishing policy

Classification and link selection happen before the merchant publishing decision.

```mermaid
flowchart LR
    A[AI-generated Google reply] --> B{Does the reply need approval?}
    B -- Approval mode is enabled --> C[Status: pending_approval]
    B -- Rating is below min_rating_auto --> C
    B -- Otherwise --> D[Publish through Google API]
    C --> E[Merchant edits or approves]
    E --> F[Publish through Google API]
    D --> G[Confirm reply is live on the listing]
    F --> G
```

A queued reply contains the correct ticket or sales link, but the customer does
not see it until the merchant approves and it is published.

## 5. WhatsApp continuation: ticket path

```mermaid
flowchart LR
    A[Reviewer clicks link with handoff code] --> B[WhatsApp opens with code prefilled]
    B --> C[Inbound WhatsApp message is stored]
    C --> D[Capture lead conversation]
    D --> E{Resolve review ticket}

    E -- Handoff code --> F[Load ReviewIssue and ticket]
    E -- Ticket number mentioned --> F
    E -- No match --> G[Normal new WhatsApp enquiry]

    F --> H{Is this only a status check on a finished ticket?}
    H -- Yes --> I[Send templated status reply with zero LLM calls]
    H -- No --> J[Inject original review classification into AI context]
    J --> K[AI acknowledges the issue and guides the customer]
    K --> L[Continue until resolved]
```

### Ticket lifecycle

```mermaid
stateDiagram-v2
    [*] --> New: needs_attention review created
    New --> Open: customer returns via code or ticket number
    Open --> InProgress: merchant or agent starts work
    InProgress --> Resolved: fix confirmed
    Resolved --> Closed: ticket closed
    Closed --> [*]

    note right of Resolved
        A later status-only message
        gets a templated reply
        and consumes no LLM call.
    end note
```

## 6. WhatsApp continuation: sales path

```mermaid
flowchart LR
    A[Reviewer clicks generic sales link] --> B[WhatsApp opens without a ticket code]
    B --> C[Inbound WhatsApp message is stored]
    C --> D[Capture or update Lead]
    D --> E[AI reads the databank and business context]
    E --> F[AI answers Premium, pricing or availability question]
    F --> G{Lead qualifies?}
    G -- Yes --> H[Schedule follow-up if needed]
    G -- Conversion --> I[Mark lead converted]
    G -- No response --> J[Follow-up or eventually lost]
```

### Lead lifecycle

```mermaid
stateDiagram-v2
    [*] --> New: customer messages WhatsApp
    New --> Qualified: buying intent detected
    Qualified --> FollowUp: answer sent, waiting for customer
    FollowUp --> Qualified: customer replies
    Qualified --> Converted: purchase or conversion recorded
    Qualified --> Lost: no interest or invalid lead
    Converted --> [*]
    Lost --> [*]
```

## 7. Ticket and lead are deliberately different

```mermaid
flowchart LR
    A[Google review] --> B{What does the customer need?}

    B -- Someone must fix or answer a problem --> C[ReviewIssue + ticket]
    C --> C1[Owner: reviews/support]
    C1 --> C2[Lifecycle: new → open → in progress → resolved → closed]
    C1 --> C3[Identifier: TK-...]
    C1 --> C4[WhatsApp link carries handoff code]

    B -- Customer may buy or ask about plans --> D[Lead]
    D --> D1[Owner: sales]
    D1 --> D2[Lifecycle: new → qualified → follow up → converted/lost]
    D1 --> D3[Identifier: contact thread]
    D1 --> D4[WhatsApp link has no ticket code]
```

They may be linked operationally when a complaint later becomes a purchase
enquiry, but they are not merged: their owners, lifecycles, and identifiers are
different.

## 8. Live ticket updates and notifications

A ticket's life happens where nobody is watching: the poll loop classifies a
review and opens a ticket, and the customer walks back in on WhatsApp minutes
or hours later. Two channels, deliberately different.

```mermaid
flowchart LR
    A[Ticket lifecycle change] --> B{publish_review_issue_event}

    B -- every change --> C[Redis inbox channel]
    C --> D[Open ticket queue refetches]
    C --> E[Dashboard ticket card refetches]

    B --> F{notify_review_issue}

    F -- created --> G[Bell: new ticket]
    F -- customer_returned --> H[Bell: customer came back]
    F -- updated: status or attention moved --> I[Bell: ticket updated]
    F -- updated: re-categorised --> J[Silent]
    F -- owner changed own ticket --> K[Silent]
    F -- tickets preference off --> L[Silent]
    F -- handoff code minted --> M[Realtime only]
```

| Event | Realtime | Bell entry |
| --- | --- | --- |
| `created` — review needs attention, ticket opened | yes | yes |
| `handoff_minted` — customer got a code to quote | yes | no |
| `customer_returned` — customer messaged the code on WhatsApp | yes | yes |
| `updated` — ticket edited | yes | only when status or `needs_attention` moved |
| classified review with nothing to action (praise, question) | no | no |

Rules the implementation holds to:

- **Praise is never a ticket**, so it is never announced — otherwise merchants
  learn to ignore ticket alerts.
- **A handoff code is realtime-only.** It is minted seconds after the ticket is
  created, so a second bell entry would be the same news twice.
- **The owner never notifies themselves.** An employee editing a ticket does
  alert the workspace; the owner who clicked the button does not.
- **Events are published after the commit** (the customer-return path after the
  flush the caller owns), so a queue never redraws from a rolled-back change.
- **Publishes are best-effort.** Redis down costs a refresh; `notify()` writes
  in a savepoint, so a failed bell entry cannot roll back a review pipeline or a
  customer's reply.
- **The browser refetches on the event** rather than rendering the event
  payload — it carries the ticket's identity only, never the review text.
- **Event bursts are coalesced** (400 ms): one new ticket arrives as `created`
  plus `handoff_minted`, and a customer returning chains further updates.
- **The bell's 45 s poll stays** as the fallback for a dropped socket; realtime
  is the fast path, not the only path.

## 9. Safety and data boundaries

```mermaid
flowchart LR
    A[AI reads review text] --> B[Review text is untrusted customer content]
    B --> C[Strip angle brackets and collapse whitespace]
    C --> D[Wrap in untrusted-review delimiters]
    D --> E[Inject structured classification into system context]
    E --> F[AI generates reply or WhatsApp guidance]

    G[WhatsApp history] --> H[Filter by channel plus contact phone]
    H --> I[Only this customer's inbound and outbound messages]
    I --> F

    J[Unknown contact] --> K[Empty history, never channel-wide history]
```

- Ticket and handoff codes are unique per tenant.
- Handoff codes use a 30-character alphabet with no ambiguous `0/O` or `1/I`.
- WhatsApp history is per conversation, never shared across customers.
- Synthetic dashboard tests never publish to Google or send a WhatsApp message.
- Ticket events and notifications are tenant-scoped, like the ticket itself.