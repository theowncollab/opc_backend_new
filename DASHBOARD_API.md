# Dashboard API contract

The API that `opc_frontend/dashboard-app` calls. Response shapes match the TypeScript types in
`dashboard-app/src/data/types.ts` (creators and brands) and `dashboard-app/src/admin/types.ts` (team console).
Storage is described in `database/schema.py`.

## Conventions

| Topic | Rule |
|---|---|
| Sign-in | Token from `Authorization: Bearer <accessToken>` or the `accessToken` cookie (`utils/deps_.py`). |
| Role | Routes scoped to an account take `?role=creator` or `?role=brand`, meaning that account of the signed-in email. |
| Errors | Real HTTP status codes, with a body of `{ "detail": "Plain sentence the dashboard can show." }`. |
| Field names | camelCase JSON. Dates are ISO strings (UTC). |
| Payments | Off (`utils/fees_.py: PAYMENTS_LIVE = False`). No route asks for bank details or moves money. Money amounts are informational. |
| Email | Always sent with `utils.email_.send_email_async`, called as `email_.send_email_async(...)` so tests can capture it. |
| Audit | Team actions write an `ADMIN/AUDIT` entry via `helpers_.audit()`, with a reason when one is given. |

---

## A. Account and onboarding (`routes/users.py`)

**`GET /api/users/me?role=`**

Returns one of two shapes, depending on the role.

*Creator* (`CreatorProfile` plus `status` and `onboarded`):
- `id, legalName, displayName, email, phone, city, niche, secondaryNiche`
- `memberSince, iis, iisFactors: {engagement, quality, reliability, growth}`
- `engagementRate`: 0 until known
- `rating`: 0 until known
- `socials: SocialAccount[]`
- `payout`: always `{}` while payments are off
- `signatureOnFile`
- `status`
- `onboarded`: bool

*Brand* (`BrandProfile` plus `status` and `onboarded`):
- `id, companyName, industry, workEmail, contactName, designation, phone, city`
- `website, gstin, verified, memberSince, signatoryName, status, onboarded`

**`GET /api/users/me/onboarding?role=`** returns `{ step, data, completed }`.

**`PUT /api/users/me/onboarding?role=`**
- Body: `{ step: int, data: {...} }`.
- Saves progress and copies known keys into `profile`:
  - creator: `legalName, displayName, city, niche, niche2, format, audience`
  - brand: `company, industry, contact, designation, city, website, gstin, about, signatory`
- Returns `{ step }`.

**`POST /api/users/me/signature?role=`**
- Body: `{ mode: 'draw'|'type', dataUrl?, typed?, consentVersion }`.
- `dataUrl` must be `data:image/png;base64,...` and at most 200 KB. `typed` must be non-empty for `mode: 'type'`.
- Returns `{ ok: true }`.

**`POST /api/users/me/onboarding/complete?role=`**
- Body: `{ agreementVersion, checks: bool[] }`.
- Requires:
  - every check `true`,
  - a signature on file,
  - the required profile fields,
  - creator: at least one social account that's `verified` or `pending`,
  - brand: work email verified.
- Then:
  - sets `onboarding.completedAt`,
  - sets `status: 'pending'` and `verified: false`,
  - creates an `ADMIN/VERIFICATION` request with `kind: 'account'`.
- Returns `{ status: 'pending' }`. Fails with 422 and a `detail` saying what's missing.

**Profile edits**
- `POST /api/users/me/otp`: body `{}`. Emails a 6-digit code to the account email. Returns `{ sent: true }`. Limited to 5 a day.
- `POST /api/users/me/otp/verify`: body `{ code }`. Returns `{ ok: true }` and allows profile edits for 10 minutes on every account of that email. Wrong code: 400. After 5 attempts: 429.
- `PUT /api/users/me?role=`: body is any of these:
  - creator: `legalName, displayName, city, niche, phone`
  - brand: `company, industry, website, gstin, contact, designation, phone, signatory`

  Without a fresh OTP it returns 403 "Confirm with the code we emailed you first." Otherwise it returns the same shape as `GET /api/users/me`.

**Closing an account**
- `POST /api/users/me/deactivate?role=`: body `{ reason, feedback? }`. Sets `status: 'deactivated'`. Returns `{ status }`.
- `DELETE /api/users/me?role=`: body `{ reason, feedback?, confirm: 'DELETE MY ACCOUNT' }`. Marks `deletionRequestedAt` and `status: 'deactivated'`; the actual erasure happens after active deals finish. Returns `{ status: 'deletion-requested' }`.

**`POST /api/users/me/socials/manual-check?role=`**
- Body: `{ platform, handle }`.
- Adds a `{ pending: true }` social and creates an `ADMIN/VERIFICATION` request with `kind: 'social'`.
- Returns `{ socials: SocialAccount[] }`.

**Brand work email**
- `POST /api/verification/business-email?role=brand`: body `{ email }`. Rejects free email domains with 422. Emails a code. Returns `{ sent: true }`.
- `POST /api/verification/confirm-email?role=brand`: body `{ email, code }`. Sets `profile.workEmail` and `emailVerified: true`. Returns `{ verified: true }`.

## B. Campaigns and deals (`routes/deals.py`)

**`Deal` shape:**
- `id` (contract code, e.g. `OPC-2026-1117-001`), `campaignName, brandName, creatorName, creatorHandle`
- `deliverable, platform, budget, ris, stage`
- `deadline, signedOn` (`''` until signed)
- `graceEndsOn?, graceDay?` (day number since content was submitted, starting at 1)
- `flaggedChat`

**Deals**
- `GET /api/deals?role=` returns `Deal[]` where you're a party, newest first.
- `GET /api/deals/{code}?role=` returns `Deal`, or 404 if you're not a party.
- `POST /api/deals/{code}/submit-content?role=creator`
  - Body: `{ link, note? }`. The link must start with `https://`.
  - Moves the deal to `stage: 'review'`. Sets the grace start, and `graceEndsOn` from the RIS tier's `holdDays`.
  - Notifies the brand. Returns `Deal`.
- `POST /api/deals/{code}/approve?role=brand`
  - Only from `review`, else 409.
  - Moves the deal to `stage: 'verify'`, notifies the creator, returns `Deal`.
- `POST /api/deals/{code}/request-revision?role=brand`
  - Body: `{ note }`. Only from `review`.
  - One revision per deal; a second returns 409 "This deal's one revision has been used."
  - Moves the deal back to `stage: 'scriptApproved'`, records the revision, notifies the creator, returns `Deal`.
- `POST /api/deals/{code}/dispute?role=`
  - Body: `{ note }` (at least 10 characters).
  - Creates `DEALS/DISPUTES`: code `DSP-NNN`, `status: 'open'`, `held` = the split's hold.
  - Returns `{ disputeId }`.

**Campaigns**

Input (`CampaignInput`) has the dashboard form's keys:
- `objective, name, description, age, gender, cities, persona, product, price, usp`
- `budget` (string or number)
- `payType, contentType`
- `creators` (count band, e.g. `'2–3'`)
- `tier, niche, deadline, kpi, kpiValue, notes`
- `platforms: string[]`
- `status: 'draft'|'matching'`

The **readiness score (CIRS) is computed on the server** with the same formula as `PostCampaign.tsx`:
- objective 10
- audience: 4 age + 4 gender + 4 cities + 3 persona
- budget: 13 if the budget is over 0, + 7 for payType
- deliverables: 6 for platforms + 5 contentType + 4 creators
- metrics: 8 deadline + 7 kpi + 5 kpiValue
- capped at 100

`status: 'matching'` needs a CIRS of at least 40, else 422.

`Campaign` response: `{ id, name, status, budget, platforms, creators: int, cirs, deadline }`. `creators` is the low end of the band.

| Route | What it does |
|---|---|
| `POST /api/campaigns?role=brand` | Create |
| `PUT /api/campaigns/{id}?role=brand` | Update (only `draft` or `matching`) |
| `GET /api/campaigns?role=brand` | List |

**`GET /api/campaigns/{id}/matches?role=brand`**
- Returns `CreatorMatch[]`, up to 10, highest CIFS first:
  - `id` (creator account id), `alias` ("Creator A", "Creator B"…)
  - `niche, topCity, followers` (sum of verified socials), `engagementRate, iis`
  - `cifs`: 0–100 = 35 % IIS + 20 niche match + 15 city match + 15 budget fit + 15 % × CIRS
  - `revealed?: { name, handle }`
- Only active, verified creators are matched.

**`POST /api/discover/creators/{creatorId}/reveal?role=brand`**
- Body: `{ campaignId }`.
- Creates a `DEALS/REVEALS` entry (6-month window from now).
- Creates a `Deal` in `stage: 'selected'`, with `ris` from `fees_.ris_for_budget`.
- Opens a conversation (`helpers_.open_conversation`) and notifies the creator.
- Returns `{ name, handle, dealId }`.

**`GET /api/monitor/active?role=brand`** returns `MonitoredCreator[]`: `{ id, name, handle, since, until, status, note }`.

**`GET /cron/deals/auto-approve`**
- Needs `Authorization: Bearer $CRON_SECRET`.
- Approves deals in `review` whose `graceEndsOn` has passed.
- Returns `{ approved: n }`.

## C. Chat, support and notifications (`routes/chat.py`)

**`Conversation` shape** (from the signed-in account's point of view):
- `id`
- `title`: the other member's name
- `subtitle`: subject
- `unread, flagged, suspended, lastAt`
- `messages: [{ id, from: 'me'|'them'|'system', text, at, flagged }]`

**Chat routes**
- `GET /api/chat/conversations?role=` returns `Conversation[]`, newest first.
- `GET /api/chat/conversations/{id}?role=` returns `Conversation`, or 404 if you're not a member.
- `POST /api/chat/conversations/{id}/read?role=` clears your unread count. Returns `{ ok: true }`.
- `POST /api/chat/conversations/{id}/send?role=`
  - Body: `{ text }` (1–2000 characters). Returns 423 if the conversation is suspended.
  - **The server scans each message** for phone numbers, emails, street addresses, WhatsApp, Telegram, `wa.me`, and words from the abuse list.
  - If something matches, the message is stored with `flagged: true`. The conversation is set `flagged` and `suspended`, and a system message is added. A `CHAT/FLAGS` document is created and the sender's `flags` goes up by one.
  - Returns `Conversation` in both cases.

**Support and notifications**
- `GET /api/support/tickets?role=` returns `Ticket[]`: `{ id (TKT-NNN), subject, status ('open'|'closed'; 'waiting' shows as 'open'), date }`.
- `POST /api/support/tickets?role=`
  - Body: `{ category, subject, body }` (body at least 20 characters).
  - Priority is `high` for Payment and Paused chat, `normal` otherwise.
  - Emails support. Returns `Ticket`.
- `GET /api/notifications?role=` returns `[{ id, text, at, read }]`, newest first, up to 50.
- `POST /api/notifications/read?role=` marks all as read.

## D. Team console (`routes/admin.py`, `routes/admin_meetings.py`)

All routes need `staff_member` and the listed permission (`utils/permissions_.py`). Actions take a `reason` where marked ✱ and write the audit log.

**Who you are and the overview**
- `GET /api/admin/me` returns `{ name, email, role, permissions }`.
- `GET /api/admin/overview` (`people.view`) returns:
  - `queues: { verification, disputes, moderation, payouts: 0, support }`
  - `totals: { creators, brands, eventPartners, dealsInProgress }`
  - `signupsByWeek: [{ label, value }]` for the last 5 weeks
  - `recent`: the 6 newest audit entries

**People**

`GET /api/admin/people?type=&status=&q=` (`people.view`) returns `Person[]`:
- `id` (account id), `name, sub` (handle or contact), `type, email, city, status, verified`
- `joined, lastActive, deals` (count), `flags, iis?`
- `socials?: [{ platform, handle, followers }]`
- `notes`

| Route | Permission | Body | Returns |
|---|---|---|---|
| `GET /api/admin/people/{id}` | `people.view` | | `Person` plus `deals: AdminDeal[]` |
| `POST /api/admin/people/{id}/suspend` | `people.suspend` | `{ reason }` ✱ | `Person`. Also emails the person. |
| `POST /api/admin/people/{id}/reactivate` | `people.suspend` | `{ reason }` ✱ | `Person` |
| `POST /api/admin/people/{id}/notes` | `people.edit` | `{ text }` | `Person` |
| `POST /api/admin/people/{id}/email` | `people.edit` | `{ subject, body }` | `{ sent: true }` |
| `PATCH /api/admin/people/{id}/socials` | `verification.decide` | `{ platform, handle, followers }` | `Person`. Records a manual check: `verified: true`, `verifiedOn: today`. |

**Verification**

`GET /api/admin/verification` (`verification.decide`) returns `VerificationRequest[]`.

| Route | Body | What it does |
|---|---|---|
| `POST .../{id}/approve` | `{ reason }` ✱ | Account: `status: 'active'`, `verified: true`. Social: marks that social verified. Removes the request and notifies the person. |
| `POST .../{id}/reject` | `{ reason }` ✱ | Account: `status: 'deactivated'`. Social: removes the pending social. Removes the request and emails the reason. |
| `POST .../{id}/request-info` | `{ reason }` ✱ | Emails the person. The request stays in the queue. |

**Deals**
- `GET /api/admin/deals` (`deals.view`) returns `AdminDeal[]`: `{ id, campaign, brand, creator, budget, ris, stage, escrow: null, updated }`. `escrow` is `null` while payments are off.
- `POST /api/admin/deals/{code}/stage` (`deals.manage`): body `{ stage }`, which must be one of the 11 stages. Moving to `signed` sets `signedOn`. Returns `AdminDeal`.

**Disputes**
- `GET /api/admin/disputes` (`disputes.resolve`) returns `Dispute[]`.
- `POST /api/admin/disputes/{code}/resolve` (`disputes.resolve`)
  - Body: `{ outcome: 'release'|'refund'|'split', creatorShare: 0-100, note }` (note at least 10 characters).
  - Records the decision only, because no money moves while payments are off.
  - Notifies both parties. Returns `Dispute`.

**Payouts**
- `GET /api/admin/payouts` (`payouts.release`) returns `[]` while payments are off.

**Moderation**

`GET /api/admin/moderation/flags` (`moderation.act`) returns `ChatFlag[]`.

| Route | Body | What it does |
|---|---|---|
| `POST .../flags/{id}/dismiss` | `{ reason? }` | Status `dismissed`; un-suspends the conversation. |
| `POST .../flags/{id}/warn` | `{ reason }` ✱ | Status `warned`; emails the sender. |
| `POST .../flags/{id}/suspend` | `{ reason }` ✱ | Status `suspended`; suspends the sender's account. |

**Off-platform alerts**

`GET /api/admin/alerts` (`moderation.act`) returns `MonitorAlert[]`.

| Route | Body | What it does |
|---|---|---|
| `POST /api/admin/alerts` | `{ brand, creator, evidence, confidence?, windowEnds? }` | The team reports an alert; there are no automatic scans after the one-time verification decision. |
| `POST .../alerts/{id}/false-positive` | `{ reason }` ✱ | Updates the status |
| `POST .../alerts/{id}/investigate` | `{ reason }` ✱ | Updates the status |
| `POST .../alerts/{id}/penalise` | `{ reason }` ✱ | Status `penalised`. Suspends the brand and creator accounts whose names match. |

**Support tickets**
- `GET /api/admin/tickets` (`support.reply`) returns `AdminTicket[]`.
- `PATCH /api/admin/tickets/{code}`: body `{ assignee?, status?, priority? }`. Returns `AdminTicket`.
- `POST /api/admin/tickets/{code}/reply`: body `{ text }`. Sets status `waiting`, emails the person, returns `AdminTicket`.

**Team** (`team.manage`, except the list)
- `GET /api/admin/team` returns `TeamMember[]`. Every staff member can see it.
- `POST /api/admin/team/invite`: body `{ email, name?, role }`. Only `@theowncollab.com` addresses, and the role can't be `Owner`. Emails the invite. Returns `TeamMember`.
- `PATCH /api/admin/team/{id}`: body `{ role }`. You can't change an Owner's role or your own.
- `DELETE /api/admin/team/{id}`: you can't remove an Owner or yourself.

**Audit log**
- `GET /api/admin/audit?q=&actor=&format=json|csv` (`audit.view`) returns `AuditEntry[]` newest first, or a CSV file.

**Meetings** (`meetings.manage`). Same `MEET` database as `admin_meet_controls`, which these routes replace.
- `GET /api/admin/meetings?date=YYYY-MM-DD` returns `MeetingSlot[]`: `{ time, status: 'open'|'booked'|'blocked', with?: { name, email, type } }`.
  - The day's slots are `TIMINGS[0].time_slots` plus `EXTRA_SLOTS` for that date.
  - A booking with a person is `booked`; a booking without a person, or with `blocked: true`, is `blocked`.

| Route | Body | What it does |
|---|---|---|
| `POST /api/admin/meetings/block` | `{ date, time }` | Blocks the slot |
| `POST /api/admin/meetings/reopen` | `{ date, time }` | Reopens it |
| `POST /api/admin/meetings/cancel` | `{ date, time, reason }` ✱ | Deletes the booking and emails the person |
| `POST /api/admin/meetings/add-slot` | `{ date, time }` | Adds a slot for that day |
| `POST /api/admin/meetings/email` | `{ to, subject, body }` | Sends the email |

## E. Instagram and Facebook verification (`routes/social_verify.py`)

These replace platform sign-in for Instagram and Facebook. Moj was removed from verification. YouTube, X and LinkedIn still use the (not yet built) one-time sign-in.

**DM codes**

The code works for 12 hours, with 5 tries. Only a hash of it is stored.

1. **The person asks for a code.** `POST /api/users/me/socials/request-code?role=`
   - Body: `{ platform: 'instagram'|'facebook', handle }`. Instagram handles and profile links become `@name`; Facebook accepts a profile link, username or ID.
   - Adds a pending social and creates an `ADMIN/VERIFICATION` request with `method: 'dm-code'`.
   - Returns `{ socials }`. Each pending social has `codeStatus: 'requested'|'sent'|'expired'` and `codeExpiresAt`.
2. **The team generates it.** `POST /api/admin/verification/{id}/code` (`verification.decide`)
   - Body: `{ followers? }`, the count the team saw.
   - Returns `{ code, expiresAt, message, platform, handle }`. The code is shown once; the team DMs it from OPC's account.
   - Making a new code replaces the old one and resets the tries.
3. **The person enters it.** `POST /api/users/me/socials/confirm-code?role=`
   - Body: `{ platform, code }`.
   - Success: the account is verified, with `via: 'dm-code'` and the team's follower count.
   - Errors:
     - 409: no code sent yet.
     - 410: expired.
     - 400: wrong code (shows tries left).
     - 429: too many tries.

`GET /api/admin/verification` items for DM checks also carry `method`, `codeStatus`, `codeExpiresAt` and `codeSentBy`.

**Instagram invite links**

Single use, valid for 7 days. Only a hash of the token is stored.

| Route | Who | What it does |
|---|---|---|
| `POST /api/admin/invites` | `verification.decide` | Body `{ handle, name?, followers?, note? }`. Returns `{ invite, token }`. The token is only returned here. The link is `<dashboard>/invite/<token>`. |
| `GET /api/admin/invites` | `verification.decide` | Returns `Invite[]`, each with `status: active\|used\|expired\|revoked`, `usedBy` and `usedAt`. |
| `POST /api/admin/invites/{id}/revoke` | `verification.decide` | Body `{ reason }` ✱. Only for active invites. |
| `GET /api/invites/{token}` | Public | Returns `{ handle, name, expiresAt, status }` for the invite page. |
| `POST /api/invites/{token}/redeem` | Signed-in creator | Verifies that Instagram on the account with `via: 'invite'`, and marks the invite used. |

Redeeming fails with:
- 410 if the invite is used, expired or revoked.
- 409 if that handle is already verified on another account.
- 404 if the person has no creator account.

### YouTube (`routes/youtube_verify.py`)

`POST /api/users/me/socials/youtube?role=creator|brand` with body `{ "access_token": "…" }` returns `{ socials }`.

1. The dashboard opens Google's popup, which asks for read-only YouTube access (`youtube.readonly`).
2. The browser sends the access token Google returns to this endpoint.
3. The backend checks with Google that the token is live, was issued to `GOOGLE_CLIENT_ID`, and includes the YouTube permission.
4. It reads `channels?part=snippet,statistics&mine=true` and saves YouTube as verified with `via: 'google'`. The handle comes from `customUrl`, falling back to the channel name. The subscriber count is saved as `followers`, and is 0 if the channel hides it.
5. It then revokes the token. The token is never stored.

Running it again refreshes the numbers.

It fails with:
- 400 if Google doesn't accept the token, the token was made for another app, or the person unticked YouTube.
- 422 if that Google account has no channel.
- 409 if the channel is already verified on someone else's OPC account. The same person's creator and brand accounts can share a channel.
- 502 if Google can't be reached.
- 503 if the daily YouTube allowance is used up, or `GOOGLE_CLIENT_ID` isn't set.

## F. Schedule a meet (`routes/meetings.py`, `routes/admin_meetings.py`)

This replaces the Google Apps Script (`GSCRIPT_URL` is gone).
- Visitors can only book **tomorrow, in India time (IST)**, in 30-minute slots from **9:00 am to 11:00 pm IST**. The rules live in `utils/meetings_.py`.
- **Nothing is sent automatically.** The team emails the meeting link, then marks it sent.

**Website routes (public)**
- `GET /api/meetings/slots` returns `{ date, timezone: 'Asia/Kolkata', slots: [{ time, end, label, available }] }`. A slot is unavailable when it's booked, or blocked by the team.
- `POST /api/meetings/book` takes `{ name, email, phone?, userType: creator|brand|event_partner|other, company?, topic, date, time, website? }`.
  - `website` is a hidden field that only bots fill in.
  - It stores the request in `MEET/SCHEDULED_MEETS` and emails the team inbox (`SMTP_USER`) about it.
  - It returns `{ date, time, label, fromEmail, message }`. `fromEmail` comes from `MEET_FROM_EMAIL`, or `SMTP_USER` if that isn't set.
  - It's refused when:
    - the date isn't tomorrow in IST, or the slot is taken (409),
    - the time is outside the hours, or a field is invalid (422),
    - the same email books more than 2 meetings for the same day (429),
    - the hidden `website` field is filled in (400).

**Team console** (`meetings.manage`)

| Route | What it does |
|---|---|
| `GET /api/admin/meetings/bookings?status=pending\|sent\|all` | Returns the requests, soonest first: `{ id, date, time, label, name, email, phone, userType, company, topic, bookedAt, linkSent, linkSentAt, linkSentBy, meetLink }` |
| `POST /api/admin/meetings/bookings/{id}/link-sent` | Body `{ meetLink? }` (must start with `https://`). Records who marked it sent and when. |
| `POST /api/admin/meetings/bookings/{id}/link-not-sent` | Undoes the above. |

The day view (`GET /api/admin/meetings?date=`) also uses the 9:00 am to 11:00 pm slots, and each booked slot includes its `booking`.

`backend/admin_meet_controls`, the old Flask tool, is now redundant and has no sign-in. Retire it.
