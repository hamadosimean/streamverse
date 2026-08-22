# StreamVerse — Logical Database Schema

**What this document is:** the *logical* model — entities, the meaning of their
attributes, how they relate, and the rules the data must obey. It is written to
be readable without opening the code.

**What it is not:** the physical layout. Column types, index definitions and
exact table names live in [DATABASE.md](./DATABASE.md). When the two disagree,
the migrations in `backend/apps/*/migrations/` win.

**Engine:** PostgreSQL 18 · **Owner:** Django 5.2 migrations · **Money:** integer
FCFA (XOF) everywhere — never a float.

---

## Table of Contents

1. [Conceptual Overview](#1-conceptual-overview)
2. [Subject Areas](#2-subject-areas)
3. [Entity Catalogue](#3-entity-catalogue)
   - [3.1 Identity](#31-identity)
   - [3.2 Taxonomy](#32-taxonomy)
   - [3.3 Content](#33-content)
   - [3.4 Engagement](#34-engagement)
   - [3.5 Personal Library](#35-personal-library)
   - [3.6 Live](#36-live)
   - [3.7 Monetization](#37-monetization)
   - [3.8 Governance](#38-governance)
4. [Relationship Matrix](#4-relationship-matrix)
5. [Identity & Key Strategy](#5-identity--key-strategy)
6. [State Machines](#6-state-machines)
7. [Business Rules & Invariants](#7-business-rules--invariants)
8. [Derived Data Contract](#8-derived-data-contract)
9. [Lifecycle & Retention](#9-lifecycle--retention)
10. [Deliberate Modelling Choices](#10-deliberate-modelling-choices)

---

## 1. Conceptual Overview

Nine subject areas hang off one central entity — **User** — and one content
entity — **Video**. Everything else is either a description of those two, a
relationship between them, or a record of something that happened to them.

```
                            ┌──────────────────┐
              ┌─────────────│       USER       │─────────────┐
              │             └────────┬─────────┘             │
              │ owns                 │ acts on               │ is subject of
              ▼                      ▼                       ▼
      ┌───────────────┐     ┌────────────────┐      ┌─────────────────┐
      │     VIDEO     │     │  ENGAGEMENT    │      │   GOVERNANCE    │
      │  renditions   │◄────│  view / like   │      │  sanction       │
      │  thumbnails   │     │  comment       │      │  moderation act │
      │  upload sess. │     │  report ───────┼─────►│  audit log      │
      └───────┬───────┘     └────────────────┘      └─────────────────┘
              │                      ▲
     classified by                   │ about
              ▼                      │
      ┌───────────────┐     ┌────────┴───────┐      ┌─────────────────┐
      │   TAXONOMY    │     │    LIBRARY     │      │  MONETIZATION   │
      │  category     │     │  history       │      │  plan / sub     │
      │  tag          │     │  bookmark      │      │  transaction    │
      └───────┬───────┘     │  follow        │      │  campaign / imp │
              │             └────────────────┘      └────────┬────────┘
              │ targets                                      │ targets
              └──────────────────────────────────────────────┘

      ┌───────────────┐   recording   ┌──────────────┐  becomes  ┌───────┐
      │  LIVE CHANNEL │──────────────►│LIVE RECORDING│──────────►│ VIDEO │
      │  (1 per user) │               │ (= session)  │           └───────┘
      └───────┬───────┘               └──────┬───────┘
              │                              │ scopes
              └──────────► LIVE CHAT MESSAGE ◄┘
```

Two entities are addressed by generic (polymorphic) reference rather than a
typed foreign key — **Report** and the two governance logs — because a moderator
works one queue regardless of whether the target is a video or a comment.

---

## 2. Subject Areas

| # | Area | Entities | Owns the question |
|---|---|---|---|
| 1 | Identity | User | Who is this, and what may they do? |
| 2 | Taxonomy | Category, Tag | How is content classified? |
| 3 | Content | Video, VideoRendition, VideoThumbnail, UploadSession | What has been published, and in what forms? |
| 4 | Engagement | View, Like, Comment, Report | How did the audience react? |
| 5 | Personal Library | WatchHistoryEntry, Bookmark, Follow | What is *mine* as a viewer? |
| 6 | Live | LiveChannel, LiveRecording, LiveChatMessage | What is broadcasting right now? |
| 7 | Monetization | SubscriptionPlan, UserSubscription, Transaction, WebhookEvent, AdCampaign, AdImpression | Who paid, and what was served? |
| 8 | Governance | ModerationAction, UserSanction, AuditLog | What was decided, by whom, and why? |
| 9 | Framework | Django auth/session/contenttype, Celery beat/results, JWT blacklist | Plumbing — see [DATABASE.md §2.10](./DATABASE.md) |

---

## 3. Entity Catalogue

Attribute lists below are *logical*: the meaningful ones, with their domain and
the rule attached. Bookkeeping columns (`created_at`, `updated_at`) are omitted
unless they carry meaning.

### 3.1 Identity

#### User

The account, the creator, and the public channel — one entity, because the
channel handle *is* the username and splitting them would create a second
identity to keep in sync.

| Attribute | Domain | Rule |
|---|---|---|
| `email` | email, unique | Login identifier. Lower-cased on write. |
| `username` | 3–30 chars, `^[a-z0-9][a-z0-9_-]{2,29}$`, unique | Public channel handle in `/c/<username>`. Stable — changing it breaks shared links. |
| `display_name` | ≤ 80 chars | Defaults to `username` when blank. |
| `bio` | ≤ 1000 chars | Channel description. |
| `avatar` | image reference | Stored in the **public** bucket. |
| `role` | `user` \| `moderator` \| `admin` | Coarse platform-wide capability. Admin inherits every moderator capability. |
| `is_active` | boolean, default **false** | Becomes true only after email activation. |
| `is_suspended` | boolean | Independent of `is_active`. Gate is enforced on *every* request, not just at login. |
| `suspension_reason`, `suspended_at` | text, timestamp | Always written together with `is_suspended`. |
| `follower_count`, `following_count` | derived counts | See [§8](#8-derived-data-contract). |
| `preferred_language` | `fr` \| `en` | FR is the platform default. |

> A suspended user's public content disappears from every feed, search result
> and channel listing — enforced in the `publicly_listed()` query, not by
> updating rows, so lifting a suspension restores everything atomically.

### 3.2 Taxonomy

#### Category

A curated, ordered classification. **One canonical label per row** — there are no
parallel `name_fr` / `name_en` columns. The frontend translates by `slug`
(`catalog.category.<slug>`) and falls back to the stored `name`, so an admin can
add a category without a code deploy.

| Attribute | Domain | Rule |
|---|---|---|
| `name` | ≤ 80 chars | Canonical label / fallback. |
| `slug` | unique | Translation key. **Immutable after creation.** |
| `icon` | Lucide icon name | Rendered by the category chips. |
| `accent_color` | hex `#rrggbb` | |
| `display_order`, `is_active` | integer, boolean | Ordering and soft retirement. |

#### Tag

Free-text, user-supplied, normalised on write: trimmed, lower-cased, truncated
to 50 chars, then get-or-created by slug — so `Musique`, `musique ` and `MUSIQUE`
resolve to one tag rather than three.

`usage_count` is denormalised so "popular tags" needs no aggregate.

### 3.3 Content

#### Video

The catalogue entry. Exists only once a file has fully landed and passed
validation — a half-transferred upload is an `UploadSession`, not a `Video`.

| Group | Attributes | Rule |
|---|---|---|
| Ownership | `uploader` → User | Cascade: deleting an account deletes its catalogue. |
| Descriptive | `title` (≤200), `description` (≤5000), `category` (optional), `tags` (M:N) | Category is `SET NULL` — retiring a category must not delete videos. |
| Lifecycle | `status`, `processing_stage`, `processing_progress` (0–100), `failure_reason`, `transcode_attempts` | See [§6.1](#61-video-lifecycle). |
| Visibility | `visibility` ∈ `public` \| `unlisted` \| `private`, default **private** | Nothing is published by accident. |
| Source facts | `duration_seconds`, `source_width/height`, `source_resolution`, `source_video_codec`, `source_audio_codec`, `has_audio` | Filled by `ffprobe`; never client-supplied. |
| Original file | `original_key`, `original_filename`, `original_size_bytes`, `original_mime_type` | Always in the **private** bucket, whatever the visibility. |
| Derived assets | `storage_bucket`, `hls_master_path`, `poster_path`, `sprite_path`, `thumbnail_vtt_path`, `sprite_meta` | `storage_bucket` moves when visibility crosses the public/private line. |
| Counters | `view_count`, `like_count`, `dislike_count`, `comment_count` | Derived — [§8](#8-derived-data-contract). |
| Moderation | `takedown_reason`, `taken_down_at` | A takedown always carries a reason. |
| Timing | `uploaded_at`, `published_at` | `published_at` is set when it first becomes publicly visible, and drives feed ordering. |
| Format | `is_short` | **System-derived only** — [§7 R-6](#7-business-rules--invariants). |
| Search | `search_vector` | Weighted tsvector — [§8](#8-derived-data-contract). |

#### VideoRendition

One rung of the adaptive-bitrate ladder: `label` (240p…1080p), `width`,
`height`, `video_bitrate_kbps`, `audio_bitrate_kbps`, `hls_playlist_path`,
`file_size`, `segment_count`, `codecs` (RFC 6381).

Unique per (video, label). The ladder **never upscales**: a 480p source produces
240p/360p/480p and stops. Portrait sources apply the rung to the *short* side,
so a 1080×1920 phone clip yields 720×1280 for the "720p" rung.

#### VideoThumbnail

Either the poster frame (`is_poster = true`, no sprite coordinates) or one tile
of the scrubbing sprite sheet (`timestamp_offset` plus `sprite_x/y/width/height`).

#### UploadSession

Server-side state of one tus resumable upload: `filename`, `upload_length`,
`offset`, `status`, client `metadata`, `scratch_path`, `expires_at`, and an
optional 1:1 link to the `Video` it eventually produced.

Deliberately *not* merged into `Video`: a `Video` row should mean "a video
exists", and a partially transferred byte stream is not that.

### 3.4 Engagement

#### View

One viewing *session* — not one page load. Identity is the signed-in user, or,
for anonymous viewers, an opaque client id plus a salted SHA-256 IP hash. **The
raw IP is never stored.** That identity is deliberately weak: strong enough to
deduplicate, too weak to profile.

| Attribute | Rule |
|---|---|
| `viewer` | Null for anonymous. `SET NULL` on account deletion — the creator's history stays intact. |
| `session_key`, `ip_hash` | Anonymous identity material. |
| `watched_seconds` | Accumulated watch time for the session. |
| `counted` | Flips true once the threshold is crossed; only then does the row count toward `view_count`. |
| `dedup_key` | `sha256(video : identity : time-bucket : secret)`. Unique per (video, dedup_key). |

Qualification threshold: `VIEW_MIN_SECONDS` (30 s), or 30 % of the video when
that is shorter — a 10-second clip can never accumulate 30 seconds, so a flat
threshold would make short videos permanently uncountable.

#### Like

One row per (video, user), with `is_like` distinguishing like from dislike.
Modelled as one row rather than two tables so switching sides is an **update**,
not a delete-plus-insert that could interleave badly with counter maintenance.

#### Comment

`content` (≤2000), `author`, `video`, optional `parent_comment`.

**Exactly one level of nesting** — a reply may not itself have a parent.
Deletion is soft (`is_deleted`, `deleted_by`, `deletion_reason`): removing the
row would orphan replies, and a moderator needs the original text to justify the
action afterwards. `reply_count` is denormalised on the parent.

#### Report

A user's complaint about a **video or a comment**, addressed generically
(`content_type` + `object_id`) so the moderation queue is one list.

`reason` ∈ spam · harassment · violence · sexual · copyright · misinformation ·
other. `status` ∈ pending → actioned \| dismissed, with `reviewed_by`,
`reviewed_at`, `resolution_note`.

> This is also the platform's **only** copyright-takedown mechanism. It is
> manual. There is no automated content-ID matching.

### 3.5 Personal Library

Three entities with the same shape — a row per (user, thing) plus a timestamp —
and one audience: the signed-in viewer's own data.

#### WatchHistoryEntry

`progress_seconds` (the **furthest** point reached, not the last position, so
seeking backwards near the end does not lose the fact they nearly finished),
`completed`, `watch_count`, `first_watched_at`, `last_watched_at`. Unique per
(user, video). Derived: `progress_percent`, and `is_resumable` — offered only
between 5 % and 95 %, because resuming a video at 98 % is noise.

#### Bookmark

Unique per (user, video), with an optional private `note` (≤200 chars) visible
only to its author.

#### Follow

A directed edge `follower → channel`, both User. Unique per pair, and
**self-follow is forbidden** by a check constraint.

A follow affects the follower's own feed and nothing else. There are **no
notifications**: nobody is emailed or pushed when a channel uploads.

### 3.6 Live

#### LiveChannel

Exactly one per user (1:1). Separate from `Video` because a live stream has no
renditions, no duration and no storage prefix until it ends.

| Attribute | Rule |
|---|---|
| `slug` | Unique, **public** — it appears in the HLS URL every viewer fetches. |
| `stream_key` | Unique, secret, 32-byte URL-safe token. A bearer credential for *publishing*. Never shown to anyone but the owner; rotation takes effect immediately. |
| `status` | `offline` \| `live` \| `ended` — [§6.2](#62-live-session-lifecycle). |
| `current_viewer_count`, `peak_viewer_count`, `all_time_peak_viewers`, `total_sessions` | Derived counters. |
| `is_enabled` | Moderator switch: blocks new broadcasts without deleting the channel. |
| `chat_enabled`, `record_sessions` | Owner policy. |

> The stream key travels in the RTMP **query string**, never in the path. The
> path is what ends up in the public HLS URL.

#### LiveRecording

One broadcast session *and* the file it produced: `started_at`, `ended_at`,
`peak_viewer_count`, `chat_message_count`, `recorded_file` (path on the shared
volume), `recorded_size_bytes`, optional `converted_video` → Video, and
`conversion_error`.

It doubles as the session record so that chat can hang off it — a new broadcast
starts with a clean chat rather than yesterday's conversation.

#### LiveChatMessage

`content` (≤500), scoped to a channel and (normally) to a session. Persisted
rather than fire-and-forget: a viewer joining mid-stream gets the recent
backlog, and moderation needs the record. Soft-deleted via `is_deleted` +
`deleted_by`.

### 3.7 Monetization

#### SubscriptionPlan

`name`, `slug` (unique), `price` (**integer FCFA**), `billing_period` ∈ monthly
(30 d) \| quarterly (90 d) \| yearly (365 d), `ad_free` flag, `benefits` (list of
display labels), `is_active`, `display_order`.

Benefits are a *flag* (`ad_free`) plus decorative labels — so the ad selector can
ask a precise question instead of parsing marketing copy.

#### UserSubscription

`user`, `plan` (**restricted** delete — a plan with subscribers cannot be
deleted), `status` ∈ pending → active → cancelled \| expired,
`started_at`, `current_period_end`, `cancelled_at`, `auto_renew`,
`renewal_failures`.

At most **one open** (pending or active) subscription per user. Cancelled and
expired rows accumulate freely as history.

`auto_renew = false` means "runs to the end of the paid period, then stops" —
cancelling never confiscates time already paid for.

#### Transaction

One payment **attempt**; failed attempts keep their row.

| Attribute | Rule |
|---|---|
| `user` | Restricted delete — a paid-for account cannot vanish from the ledger. |
| `plan`, `subscription` | What was being bought. |
| `provider` | orange_money \| moov_money \| wave \| card \| mock |
| `type` | subscription \| renewal |
| `status` | pending → completed \| failed \| cancelled |
| `amount` | Integer FCFA, ≥ 1. `currency` defaults to XOF. |
| `idempotency_key` | **Unique in the database.** This is what makes a double-submitted checkout return the existing transaction rather than charge twice. |
| `provider_reference` | The provider's own id for this payment. |
| `payer_identifier` | Mobile-money number or the last 4 card digits. **Never a full PAN.** |
| `provider_payload` | Raw callback body, kept for reconciliation and disputes. |

#### WebhookEvent

Every inbound provider callback, recorded **before** it is acted on:
`provider`, `event_id`, `event_type`, optional `transaction`, `payload`,
`signature_valid`, `processed`, `processed_at`, `processing_error`.

Unique per (provider, event_id) — the replay guard. Providers retry until they
get a 2xx, so the same event *will* arrive more than once, and processing it
twice would extend a subscription twice.

#### AdCampaign

`advertiser_name`, `title`, `creative` (image or short video, **public** bucket —
it is shown to every viewer anyway), `creative_is_video`, `click_url`,
`placement` ∈ pre_roll \| mid_roll, `duration_seconds`,
`skippable_after_seconds` (0 = not skippable), `mid_roll_position` (fraction of
the video), `start_date`/`end_date`, `impression_cap` (0 = unlimited),
`weight` (relative rotation share), `status` ∈ draft \| active \| paused \| ended,
optional `categories` (M:N; empty = all categories), and the derived counters
`impression_count`, `completed_count`, `click_count`.

Targeting is intentionally minimal: first-party rotation only — no VAST, no
exchange, no auction.

#### AdImpression

One ad play: `campaign`, optional `video` and `viewer`, `session_key`,
`placement`, `played_at`, `completed`, `skipped`, `watched_seconds`, `clicked`.
Written at selection time and updated when the play finishes.

### 3.8 Governance

#### ModerationAction

The record of what was **decided** — immutable once written. The *queue* is
`Report`; duplicating it here would create two sources of truth for one workflow.

`moderator` (nullable — the person may later be deleted), `action` (taken down ·
restored · comment removed · report dismissed · warned · suspended · reinstated ·
live channel disabled/enabled), generic `target` plus `target_repr` snapshot,
`affected_user` (the owner of the content acted on, so a moderator can see
someone's history without a three-way join), mandatory `reason`, optional
originating `report`, and free-form `metadata`.

#### UserSanction

`user`, `moderator`, `type` ∈ warning \| suspension \| ban, `reason`,
`starts_at`, `expires_at` (null for a permanent ban or a warning), `lifted_at`,
`lifted_by`, optional `report`.

Kept as history rather than only a boolean on `User`: "repeated violations" is
the trigger for escalation, and you cannot count repeats against a flag that
gets overwritten.

A sanction is *active* when it has not been lifted and either has no expiry
(permanent ban) or its expiry is in the future. A **warning is never active** —
it restricts nothing; it is a record.

#### AuditLog

Append-only trail across every sensitive path: `actor` (null for system/Celery
actions), `action` (a closed vocabulary spanning video, account, live,
engagement, campaign and payment events), generic `target` plus an
`object_repr` snapshot (the target row may later be deleted), `reason`,
`metadata`, `ip_address`, `created_at`.

---

## 4. Relationship Matrix

| Parent | Child | Card. | On parent delete | Note |
|---|---|---|---|---|
| User | Video | 1:N | CASCADE | Deleting an account removes its catalogue. |
| User | UploadSession | 1:N | CASCADE | |
| User | LiveChannel | 1:1 | CASCADE | Optional — created on first use. |
| User | View | 1:N | SET NULL | View survives; creator stats stay intact. |
| User | Like / Comment / Bookmark / WatchHistoryEntry | 1:N | CASCADE | The viewer's own data goes with them. |
| User | Follow (as follower) | 1:N | CASCADE | |
| User | Follow (as channel) | 1:N | CASCADE | |
| User | Report (reporter) | 1:N | CASCADE | |
| User | Report (reviewed_by) | 1:N | SET NULL | The decision outlives the reviewer's account. |
| User | UserSubscription | 1:N | CASCADE | At most one open at a time. |
| User | Transaction | 1:N | **PROTECT** | The ledger blocks the delete. |
| User | UserSanction (subject) | 1:N | CASCADE | |
| User | ModerationAction / AuditLog (actor) | 1:N | SET NULL | Log entry survives; "systeme" is displayed. |
| Video | VideoRendition | 1:N | CASCADE | Unique per (video, label). |
| Video | VideoThumbnail | 1:N | CASCADE | Exactly one poster in practice. |
| Video | View / Like / Comment | 1:N | CASCADE | |
| Video | Bookmark / WatchHistoryEntry | 1:N | CASCADE | |
| Video | AdImpression | 1:N | SET NULL | Impression history survives the video. |
| Video | UploadSession | 1:1 | SET NULL | Optional back-reference. |
| Video | LiveRecording (converted_video) | 1:1 | SET NULL | Optional. |
| Category | Video | 1:N | SET NULL | Retiring a category must not delete content. |
| Category | LiveChannel | 1:N | SET NULL | |
| Category | AdCampaign | M:N | — | Empty set = target everything. |
| Tag | Video | M:N | — | |
| Comment | Comment (replies) | 1:N | CASCADE | **Max depth 1.** |
| LiveChannel | LiveRecording | 1:N | CASCADE | |
| LiveChannel | LiveChatMessage | 1:N | CASCADE | |
| LiveRecording | LiveChatMessage | 1:N | CASCADE | Nullable — scopes chat to a session. |
| SubscriptionPlan | UserSubscription | 1:N | **PROTECT** | |
| SubscriptionPlan | Transaction | 1:N | **PROTECT** | |
| UserSubscription | Transaction | 1:N | SET NULL | |
| Transaction | WebhookEvent | 1:N | SET NULL | An event may arrive before it can be matched. |
| AdCampaign | AdImpression | 1:N | CASCADE | |
| Report | ModerationAction / UserSanction | 1:N | SET NULL | Links a decision back to what triggered it. |

**Polymorphic (generic) references** — `content_type` + `object_id`, no FK
enforcement, resolved in application code:

| Entity | Valid targets |
|---|---|
| Report | Video, Comment |
| ModerationAction | Video, Comment, User, LiveChannel |
| AuditLog | any model |

---

## 5. Identity & Key Strategy

| Key type | Used by | Why |
|---|---|---|
| **UUID** | Video, UploadSession, Transaction, AdImpression | Publicly addressable. Sequential integers would leak catalogue size and make *unlisted* videos trivially enumerable by counting up. |
| **Auto integer** | everything else | Never appears in a URL a stranger holds. |
| **Natural, unique** | `User.email`, `User.username`, `Category.slug`, `Tag.slug`, `LiveChannel.slug`, `Transaction.idempotency_key`, `LiveChannel.stream_key` | Addressed or matched by these values directly. |

Composite uniqueness that carries a business rule:

| Entity | Unique on | Meaning |
|---|---|---|
| View | (video, dedup_key) | One view per identity per time bucket. |
| Like | (video, user) | One opinion per person per video. |
| Bookmark | (user, video) | Saved once. |
| WatchHistoryEntry | (user, video) | One history row, updated in place. |
| Follow | (follower, channel) | No duplicate edges. |
| VideoRendition | (video, label) | One encode per ladder rung. |
| Report | (reporter, content_type, object_id) **where status = pending** | Partial: a user cannot flood the queue with duplicates, but may report again after the first is resolved. |
| UserSubscription | (user) **where status ∈ {pending, active}** | Partial: one live subscription, unlimited history. |
| WebhookEvent | (provider, event_id) | Replay guard. |

---

## 6. State Machines

### 6.1 Video lifecycle

```
                  upload completes + validation passes
                                 │
                                 ▼
    ┌──────────────────────  processing  ───────────────────────┐
    │  stage: queued → probing → transcoding → packaging        │
    │         → thumbnails → publishing → done                  │
    └───────────────┬─────────────────────────┬─────────────────┘
                    │ success                 │ ffmpeg/probe error
                    ▼                         ▼
                  ready ◄──── retry ───────  failed
                    │
                    │ moderator takedown (reason mandatory)
                    ▼
                taken_down  ──── restore ────► ready
```

`processing_stage` is a fine-grained position *inside* `status = processing`,
streamed to the uploader over WebSocket so the progress bar means something.
`transcode_attempts` increments on each retry.

Visibility is an orthogonal axis and changes freely at any time:

```
private ⇄ unlisted ⇄ public
   │                    │
   └── crossing this line relocates the whole videos/<uuid>/ prefix
       between the private and public buckets; the original never moves
```

### 6.2 Live session lifecycle

```
offline ──RTMP publish authorised──► live ──publisher disconnects──► ended
   ▲                                                                   │
   └─────────────────── next broadcast ────────────────────────────────┘

  live  ─► LiveRecording created (session opens, chat scoped to it)
  ended ─► recording settles → Celery converts fMP4 → new Video (VOD pipeline)
```

A `reconcile_live_state` task polls MediaMTX's control API every two minutes,
because the "not ready" hook is best-effort — if MediaMTX is killed it never
fires, and the channel would advertise a stream nobody can watch.

### 6.3 Subscription & payment

```
checkout ─► Transaction(pending) + UserSubscription(pending)
               │
     provider callback (WebhookEvent recorded first)
               │
      ┌────────┴────────┐
      ▼                 ▼
 completed          failed / cancelled
      │                 │
      ▼                 ▼
 subscription      subscription stays pending until the sweeper
   active            fails it, so the user can retry
      │
      │ period end approaches (RENEWAL_LEAD_HOURS)
      ▼
 renewal ─► a NEW pending Transaction, exactly like a first purchase
      │
      ├─ user cancels ─► cancelled (runs to current_period_end)
      └─ period ends unpaid ─► expired
```

### 6.4 Report → decision

```
pending ──► moderator reviews ──┬─► actioned  (+ ModerationAction, + AuditLog,
                                │              possibly + UserSanction)
                                └─► dismissed (+ ModerationAction, + AuditLog)
```

---

## 7. Business Rules & Invariants

| # | Rule | Enforced by |
|---|---|---|
| **R-1** | A video is publicly listed only when `status = ready` **and** `visibility = public` **and** its uploader is not suspended. Unlisted is reachable by direct link only. | Query layer (`publicly_listed()` / `visible_to()`) |
| **R-2** | New videos default to `private`. Nothing is published without an explicit act. | Column default |
| **R-3** | A comment may be a reply, but a reply may not have replies. | Application + serializer |
| **R-4** | Every removal — video, comment, account — carries a reason, and that text is what the author is told. | Serializer **and** service layer |
| **R-5** | Every moderation decision writes an `AuditLog` row. | Service layer |
| **R-6** | `is_short` is derived at transcode time from duration **and** aspect ratio (≤ `SHORTS_MAX_DURATION_SECONDS` **and** aspect ≤ `SHORTS_MAX_ASPECT_RATIO`). Both, not either. Never accepted from the uploader. | Pipeline |
| **R-7** | A user cannot follow themselves. | DB check constraint |
| **R-8** | At most one pending report per (reporter, target). | Partial unique index |
| **R-9** | At most one open subscription per user. | Partial unique index |
| **R-10** | A payment amount is a positive integer in FCFA. No floats anywhere in the ledger. | Column type + validator |
| **R-11** | One `idempotency_key` = one charge. Enforced by the database, not by an application check that races. | Unique constraint |
| **R-12** | A provider event is processed at most once. | Unique (provider, event_id) |
| **R-13** | A view counts only after `VIEW_MIN_SECONDS`, or 30 % of the duration when shorter. Server-side; the client cannot talk a counter up. | Service layer |
| **R-14** | Repeat views from one identity inside `VIEW_DEDUP_WINDOW_SECONDS` collapse into one row. | Unique (video, dedup_key) |
| **R-15** | Raw viewer IPs are never stored — only a salted SHA-256 hash. | Model helper |
| **R-16** | A stream key never appears in an RTMP path or an HLS URL. | Path/key split by design |
| **R-17** | Rotating a stream key invalidates the old one immediately, not at the next stream. | Service layer |
| **R-18** | The uploaded original stays in the private bucket regardless of visibility. | Pipeline |
| **R-19** | The ABR ladder never upscales past the source. | `services/ladder.py` |
| **R-20** | A card PAN is never stored — at most the last four digits. | Field contract |

---

## 8. Derived Data Contract

Denormalised values are a **cache over the source rows**, never the truth. Each
has a defined source, a write path, and a reconciliation job — because a crash
mid-write must not leave a counter permanently wrong.

| Value | Source of truth | Maintained by | Reconciled by |
|---|---|---|---|
| `Video.view_count` | View rows where `counted` | `F()` increment on qualification | `engagement.reconcile_counters` (hourly) |
| `Video.like_count` / `dislike_count` | Like rows | `F()` on toggle | `engagement.reconcile_counters` |
| `Video.comment_count` | Comment rows not soft-deleted | `F()` on create/delete | `engagement.reconcile_counters` |
| `Comment.reply_count` | Child comments | `F()` on create/delete | — (not covered by the reconciler) |
| `User.follower_count` / `following_count` | Follow rows | **Recomputed** from rows on every toggle, not incremented — so it cannot drift | — |
| `Tag.usage_count` | Video–Tag rows | Recomputed for each tag attached on video save | — (a tag *removed* from a video is not recomputed, so it can drift high) |
| `AdCampaign.impression_count` / `completed_count` / `click_count` | AdImpression rows | `F()` at play/complete/click | `monetization.aggregate_ad_stats` |
| `LiveChannel.*viewer_count`, `total_sessions` | WebSocket group membership / sessions | Live consumer | `live.reconcile_live_state` |
| `LiveRecording.chat_message_count` | LiveChatMessage rows | On message | — |
| `Video.search_vector` | title (A) + tags (B) + description (C) | Inline on save / M2M change | `engagement.rebuild_search_index` (every 4 h) |

`engagement.reconcile_counters` recomputes the four `Video` counters from the
source rows, writes only the rows that actually drifted — so a healthy database
does zero writes — and scans the **5 000 most recently uploaded videos** per run.
Drift on an older video is corrected only if it is touched by another path.

> Why `impression_count` is denormalised at all: ad selection runs on **every**
> playback and cannot afford a `COUNT` over the largest table in the schema.

---

## 9. Lifecycle & Retention

| Data | Retention | Swept by |
|---|---|---|
| Abandoned `UploadSession` + scratch chunks | `UPLOAD_SESSION_TTL_HOURS` (24 h) | `videos.maintenance.cleanup_abandoned_uploads` (every 30 min) |
| Transcode work directories | Until swept | `videos.maintenance.cleanup_stale_workdirs` (every 6 h) |
| Raw `View` rows | 180 days | `engagement.prune_view_rows` (daily 04:00) |
| Raw live recordings on disk | `LIVE_RECORDING_RETENTION_DAYS` (7 d) after conversion | `live.cleanup_old_recordings` (daily 04:30) |
| Stale pending payments | `PAYMENT_PENDING_TIMEOUT_MINUTES` (30 min) | `monetization.sweep_stale_payments` (every 10 min) |
| Expired subscriptions | Swept hourly, rows kept as history | `monetization.expire_subscriptions` |
| Ended campaigns | Status flipped, rows kept | `monetization.expire_campaigns` |
| `AuditLog`, `ModerationAction`, `UserSanction`, `Transaction`, `WebhookEvent` | **Never pruned** | — |

> **Interaction worth knowing:** `View` rows are the reconciler's source of
> truth for `view_count`, and `engagement.prune_view_rows` deletes rows older
> than 180 days. For a video still inside the reconciler's 5 000-row scan
> window, the next `reconcile_counters` run therefore recomputes `view_count`
> from the *surviving* rows and revises it downward. Videos outside that window
> keep their counter. If lifetime view counts must be permanent, the counter
> needs its own durable source — a rolled-up daily total — rather than a
> recount over a pruned table.

**Soft delete** (row kept, flag set) applies to `Comment` and `LiveChatMessage`
— replies would be orphaned and moderators need the original text. `Video`
takedown is likewise a status change, not a delete. Everything else is a hard
delete.

---

## 10. Deliberate Modelling Choices

| Choice | Reason |
|---|---|
| **`View` and `WatchHistoryEntry` are separate** | They answer different questions and have different lifetimes. `View` is analytics: deduplicated, anonymous rows included, pruned at 180 days. `WatchHistoryEntry` is the viewer's own record: one row per video, updated in place, **deletable by the user**. Deriving history from `View` would mean clearing your history silently decrements someone else's view count. |
| **`Like` is one row with a boolean, not two tables** | Switching from like to dislike becomes an update rather than a delete-plus-insert that can interleave badly with counter maintenance. |
| **`Report` uses a generic reference** | Moderators work one queue, not two parallel ones. |
| **`ModerationAction` does not duplicate the queue** | `Report` is the queue; this is the decision record. Two tables for one workflow means two sources of truth. |
| **`UploadSession` is not part of `Video`** | A `Video` row means "a video exists". A half-transferred stream is not that. |
| **`LiveChannel` is not a `Video`** | No renditions, no duration, no storage prefix until the broadcast ends and its recording goes through the normal VOD pipeline. |
| **`LiveRecording` doubles as the session record** | Chat scoped to it means a new broadcast starts with a clean chat. |
| **One canonical label per Category, no `*_fr` / `*_en` columns** | Translation is a frontend concern keyed by `slug`; an admin can add a category without a code deploy and it still renders in both languages. |
| **Postgres FTS instead of a search service** | A stored, GIN-indexed `tsvector` turns search into an index lookup with no extra service to run. Trade-off: stemming, not typo tolerance — "Djngo" finds nothing. A trigram fallback catches near-misses; real fuzzy search means Meilisearch or Elasticsearch, which is a different capability, not a tuning knob. |
| **UUID keys only where they are public** | Enumeration resistance where it matters, cheap integer keys everywhere else. |
| **Integer FCFA** | XOF has no minor unit, so there is nothing to round — but the general reason holds: a ledger that disagrees with the provider by a rounding error is worse than one that fails loudly. |

---

## See also

- [DATABASE.md](./DATABASE.md) — physical schema: columns, types, index and constraint definitions
- [ARCHITECTURE.md](./ARCHITECTURE.md) — services, pipelines and request flow
- [CONFIGURATION.md](./CONFIGURATION.md) — the settings referenced above (`VIEW_MIN_SECONDS`, `SHORTS_*`, retention windows)
- [API.md](./API.md) — the endpoints that read and write these entities
