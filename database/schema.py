"""
Where dashboard data lives in MongoDB, and the shape of each document.

Every route uses these constants instead of typing database / collection
names by hand. Dates are stored as ISO-8601 UTC strings ("2026-11-17T09:30:00Z")
unless noted, so they sort correctly and serialise without conversion.

    (DATABASE, COLLECTION)

USERS / PERM_USERS  (existing) one document per account; the same email can
    have one account per role.
    _id, email, user_type ("Creator" / "Brand" / "Event Partner" from sign-in,
    or "creator" / "brand" / "event_partner"; always read via helpers_.role_of),
    last_logout_time (datetime, existing)
    -- added for the dashboard --
    status: "active" | "pending" | "suspended" | "deactivated"
            (missing on old accounts = "active")
    verified: bool
    profile: dict              creator: legalName, displayName, city, niche, niche2,
                               format, audience, phone
                               brand: company, industry, contact, designation, city,
                               website, gstin, about, signatory, workEmail
    onboarding: {step, data, completedAt, agreementVersion, checks}
    signature: {mode, dataUrl | typed, consentVersion, at}
    socials: [{platform, handle, followers, verified, verifiedOn, pending}]
    iis: int, iisFactors: {engagement, quality, reliability, growth}
    notes: [{by, at, text}]    team-only
    flags: int                 number of moderation flags
    joined, lastActive
    otp_ok_until               profile edits allowed until this time (after OTP)

USERS / OTP           {email, purpose, code_hash, expires, attempts}
DEALS / CAMPAIGNS     {_id, code, brandAccountId, brandName, name, status, budget,
                       platforms, creators, cirs, deadline, brief, createdAt, updatedAt}
DEALS / REVEALS       {campaignId, brandAccountId, creatorAccountId, brandName,
                       creatorName, creatorHandle, since, until, status, note}
DEALS / DEALS         {_id, code, campaignId, brandAccountId, creatorAccountId,
                       campaignName, brandName, creatorName, creatorHandle,
                       deliverable, platform, budget, ris, stage, deadline, signedOn,
                       graceStartedOn, graceEndsOn, submissions, revisions,
                       flaggedChat, updatedAt}
DEALS / DISPUTES      {_id, code, dealId (deal code), campaign, brand, creator,
                       raisedBy, raisedByAccountId, reason, held, opened, status,
                       evidence, outcome, note, resolvedBy}
CHAT / CONVERSATIONS  {_id, members: [{accountId, name, type}], subject, dealId,
                       flagged, suspended, lastAt, unread: {accountId: int}}
CHAT / MESSAGES       {_id, conversationId, fromAccountId ("system" for OPC),
                       text, at, flagged}
CHAT / FLAGS          {_id, conversationId, conversation, messageId, fromAccountId,
                       from, fromType, message, reason, at, status}
SUPPORT / TICKETS     {_id, code, accountId, from, fromType, category, subject,
                       body, priority, status, assignee, opened, replies}
NOTIFY / NOTIFICATIONS {accountId, text, at, read}
ADMIN / TEAM          {email, name, role, lastActive, invited}
ADMIN / AUDIT         {actor, action, target, at}       insert-only
ADMIN / VERIFICATION  {_id, personId, name, type, kind ("account" | "social"),
                       platform, handle, submitted, checks: [{label, ok, detail}]}
                       Instagram / Facebook DM codes add: method "dm-code", code_hash,
                       codeExpiresAt (12 h), attempts, followers, codeSentBy
ADMIN / INVITES       {_id, token_hash, platform "instagram", handle, name, followers,
                       note, createdBy, createdAt, expiresAt (7 days), usedAt, usedBy,
                       usedByName, revokedAt}       single-use sign-up links
ADMIN / ALERTS        {_id, brand, creator, windowEnds, detected, evidence,
                       confidence, status, reportedBy}
ADMIN / COUNTERS      {_id: name, seq}                   for readable codes
MEET / TIMINGS        (existing, admin_meet_controls) [{time_slots: ["10:00", ...]}]
MEET / SCHEDULED_MEETS (existing) {date, time_slot, name?, email?, type?, blocked?}
MEET / EXTRA_SLOTS    {date, time_slot}                  slots added for one day
WEBSITE / CONTACT_MESSAGES {_id, name, email, subject, message, receivedAt,
                       status ("new" | "replied" | "closed"), replies: [{by, at, text}]}
WEBSITE / NEWSLETTER  {_id, email (lower case, unique), subscribedAt, source,
                       status ("subscribed" | "unsubscribed"), removedAt, removedBy}
EVENTS / REGISTERED_EVENTS (existing) {name, start_date, end_date, organizer, location,
                       poc_email, poc_name, poc_phone}
                       -- added for the team console --
                       receivedAt, status ("new" | "contacted" | "listed" | "declined"),
                       note, updatedBy, updatedAt
DEALS / CAMPAIGNS     -- added for the team console --
                       status may also be "paused" or "closed" (set by the OPC team);
                       statusBefore (to resume), teamReason, teamBy, teamAt
"""

USERS = ("USERS", "PERM_USERS")
OTP = ("USERS", "OTP")
CAMPAIGNS = ("DEALS", "CAMPAIGNS")
REVEALS = ("DEALS", "REVEALS")
DEALS = ("DEALS", "DEALS")
DISPUTES = ("DEALS", "DISPUTES")
CONVERSATIONS = ("CHAT", "CONVERSATIONS")
MESSAGES = ("CHAT", "MESSAGES")
FLAGS = ("CHAT", "FLAGS")
TICKETS = ("SUPPORT", "TICKETS")
NOTIFICATIONS = ("NOTIFY", "NOTIFICATIONS")
TEAM = ("ADMIN", "TEAM")
AUDIT = ("ADMIN", "AUDIT")
VERIFICATION = ("ADMIN", "VERIFICATION")
ALERTS = ("ADMIN", "ALERTS")
INVITES = ("ADMIN", "INVITES")
COUNTERS = ("ADMIN", "COUNTERS")
MEET_TIMINGS = ("MEET", "TIMINGS")
MEET_BOOKINGS = ("MEET", "SCHEDULED_MEETS")
MEET_EXTRA = ("MEET", "EXTRA_SLOTS")
CONTACT_MESSAGES = ("WEBSITE", "CONTACT_MESSAGES")
NEWSLETTER = ("WEBSITE", "NEWSLETTER")
REGISTERED_EVENTS = ("EVENTS", "REGISTERED_EVENTS")
