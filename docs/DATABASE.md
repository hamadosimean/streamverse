# StreamVerse — Database Reference

**Engine:** PostgreSQL 18  
**ORM:** Django 5.2 (psycopg3 driver)  
**Schema owner:** Django migrations (`manage.py migrate`)

All monetary amounts are stored as `INTEGER` in FCFA (XOF). No floats anywhere in the payment ledger.

---

## Table of Contents

1. [Entity-Relationship Overview](#1-entity-relationship-overview)
2. [Tables by Domain](#2-tables-by-domain)
   - [accounts](#21-accounts)
   - [catalog](#22-catalog)
   - [videos](#23-videos)
   - [engagement](#24-engagement)
   - [library](#25-library)
   - [live](#26-live)
   - [monetization](#27-monetization)
   - [moderation](#28-moderation)
   - [audit](#29-audit)
   - [Django internals](#210-django-internals)
3. [Indexes](#3-indexes)
4. [Constraints](#4-constraints)
5. [Denormalised Counters](#5-denormalised-counters)
6. [Soft-Delete Pattern](#6-soft-delete-pattern)
7. [Full-Text Search Vector](#7-full-text-search-vector)

---

## 1. Entity-Relationship Overview

```
                    ┌─────────────┐
                    │    User     │
                    └──────┬──────┘
                           │ 1
          ┌────────────────┼─────────────────────────┐
          │ n              │ n                        │ 1
   ┌──────▼──────┐  ┌──────▼──────┐          ┌───────▼───────┐
   │  Video      │  │UploadSession│          │  LiveChannel  │
   └──────┬──────┘  └─────────────┘          └───────┬───────┘
          │ 1                                        │ 1
    ┌─────┼──────────────────┐               ┌───────▼───────┐
    │ n   │ n                │ n             │ LiveRecording │
┌───▼──┐ ┌▼──────────┐ ┌────▼────┐         └───────┬───────┘
│Rendi-│ │VideoThumb-│ │ View    │                 │ n
│tion  │ │nail       │ └─────────┘          ┌──────▼───────┐
└──────┘ └───────────┘                      │LiveChatMessage│
                                            └──────────────┘
    ┌─────────────────────────────────────────┐
    │  Video  ◄───────────────────────────────┤
    └──┬──────┘                               │
       │ n                              ┌─────▼──────┐
    ┌──▼──────┐ ┌──────────┐           │ AdImpression│
    │  Like   │ │ Comment  │           └────────────┘
    └─────────┘ └────┬─────┘
                     │ n
                ┌────▼────┐
                │  Report │
                └─────────┘

User ──follows──► User   (Follow table)
User ──bookmarks─► Video (Bookmark table)
User ──history──► Video  (WatchHistoryEntry table)
User ──subscribes─► SubscriptionPlan (UserSubscription table)
User ──pays──► Transaction
```

---

## 2. Tables by Domain

### 2.1 accounts

#### `accounts_user`

Primary key: `INTEGER` (auto, Django default)

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK, auto-increment |
| `password` | varchar(128) | NO | Argon2/PBKDF2 hash |
| `last_login` | timestamptz | YES | |
| `is_superuser` | boolean | NO | |
| `email` | varchar(254) | NO | UNIQUE, login field |
| `username` | varchar(30) | NO | UNIQUE, public channel handle |
| `display_name` | varchar(80) | NO | Defaults to username |
| `bio` | text | NO | max 1000 chars |
| `avatar` | varchar(100) | YES | Storage path |
| `role` | varchar(16) | NO | `user` / `moderator` / `admin` |
| `is_active` | boolean | NO | True after email activation |
| `is_staff` | boolean | NO | Django admin access |
| `is_suspended` | boolean | NO | Moderation flag |
| `suspension_reason` | text | NO | |
| `suspended_at` | timestamptz | YES | |
| `follower_count` | integer | NO | Denormalised |
| `following_count` | integer | NO | Denormalised |
| `preferred_language` | varchar(5) | NO | `fr` / `en` |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

Indexes: `email` (unique), `username` (unique), `role`, `is_suspended`

---

### 2.2 catalog

#### `catalog_category`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `name` | varchar(80) | NO | Canonical label |
| `slug` | varchar(90) | NO | UNIQUE, i18n key |
| `description` | text | NO | |
| `icon` | varchar(40) | NO | Lucide icon name |
| `accent_color` | varchar(7) | NO | Hex color |
| `display_order` | integer | NO | |
| `is_active` | boolean | NO | |

#### `catalog_tag`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `name` | varchar(50) | NO | UNIQUE, normalised lowercase |
| `slug` | varchar(60) | NO | UNIQUE |
| `usage_count` | integer | NO | Denormalised |

---

### 2.3 videos

#### `videos_video`

Primary key: `UUID`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `uploader_id` | integer | NO | FK → `accounts_user` |
| `title` | varchar(200) | NO | |
| `description` | text | NO | max 5000 |
| `status` | varchar(16) | NO | `processing` / `ready` / `failed` / `taken_down` |
| `visibility` | varchar(16) | NO | `public` / `unlisted` / `private` |
| `category_id` | integer | YES | FK → `catalog_category` |
| `duration_seconds` | integer | NO | |
| `source_width` | integer | NO | |
| `source_height` | integer | NO | |
| `source_resolution` | varchar(20) | NO | e.g. `1920x1080` |
| `source_video_codec` | varchar(40) | NO | |
| `source_audio_codec` | varchar(40) | NO | |
| `has_audio` | boolean | NO | |
| `original_key` | varchar(512) | NO | MinIO object key |
| `original_filename` | varchar(255) | NO | |
| `original_size_bytes` | bigint | NO | |
| `original_mime_type` | varchar(100) | NO | |
| `storage_bucket` | varchar(100) | NO | Current bucket for HLS assets |
| `hls_master_path` | varchar(512) | NO | |
| `poster_path` | varchar(512) | NO | |
| `sprite_path` | varchar(512) | NO | |
| `thumbnail_vtt_path` | varchar(512) | NO | |
| `sprite_meta` | jsonb | NO | `{cols, rows, tile_w, tile_h, interval}` |
| `processing_stage` | varchar(20) | NO | Fine-grained pipeline stage |
| `processing_progress` | smallint | NO | 0–100 |
| `failure_reason` | text | NO | |
| `transcode_attempts` | smallint | NO | |
| `view_count` | integer | NO | Denormalised |
| `like_count` | integer | NO | Denormalised |
| `dislike_count` | integer | NO | Denormalised |
| `comment_count` | integer | NO | Denormalised |
| `takedown_reason` | text | NO | |
| `taken_down_at` | timestamptz | YES | |
| `uploaded_at` | timestamptz | NO | |
| `published_at` | timestamptz | YES | |
| `is_short` | boolean | NO | Auto-classified at transcode time |
| `search_vector` | tsvector | YES | Weighted GIN-indexed FTS field |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

#### `videos_videorendition`

One row per ABR quality level.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `video_id` | uuid | NO | FK → `videos_video` |
| `label` | varchar(10) | NO | e.g. `720p` |
| `width` | integer | NO | |
| `height` | integer | NO | |
| `video_bitrate_kbps` | integer | NO | |
| `audio_bitrate_kbps` | integer | NO | default 128 |
| `hls_playlist_path` | varchar(512) | NO | |
| `file_size` | bigint | NO | |
| `segment_count` | integer | NO | |
| `codecs` | varchar(60) | NO | RFC 6381 string |
| `created_at` | timestamptz | NO | |

Unique constraint: `(video_id, label)`

#### `videos_videothumbnail`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `video_id` | uuid | NO | FK → `videos_video` |
| `timestamp_offset` | float | NO | Seconds from start |
| `image_path` | varchar(512) | NO | |
| `is_poster` | boolean | NO | |
| `sprite_x` | integer | YES | Pixel offset in sprite sheet |
| `sprite_y` | integer | YES | |
| `sprite_width` | integer | YES | |
| `sprite_height` | integer | YES | |

#### `videos_uploadsession`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `user_id` | integer | NO | FK → `accounts_user` |
| `filename` | varchar(255) | NO | |
| `upload_length` | bigint | NO | Declared size in bytes |
| `offset` | bigint | NO | Bytes received so far |
| `status` | varchar(16) | NO | `in_progress` / `completed` / `aborted` / `expired` |
| `metadata` | jsonb | NO | Client-supplied metadata |
| `scratch_path` | varchar(512) | NO | Path in upload_scratch volume |
| `video_id` | uuid | YES | FK → `videos_video` (set on completion) |
| `error` | text | NO | |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |
| `expires_at` | timestamptz | NO | |

#### `videos_video_tags` (M2M)

| Column | Type |
|---|---|
| `video_id` | uuid |
| `tag_id` | integer |

---

### 2.4 engagement

#### `engagement_view`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `video_id` | uuid | NO | FK → `videos_video` |
| `viewer_id` | integer | YES | FK → `accounts_user` (null = anonymous) |
| `session_key` | varchar(64) | NO | Browser session |
| `ip_hash` | varchar(64) | NO | SHA-256 salted hash, raw IP never stored |
| `watched_seconds` | integer | NO | |
| `counted` | boolean | NO | True once min watch time reached |
| `dedup_key` | varchar(64) | NO | Per (video, identity, 12-h bucket) |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

Unique constraint: `(video_id, dedup_key)`

#### `engagement_like`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `video_id` | uuid | NO | FK → `videos_video` |
| `user_id` | integer | NO | FK → `accounts_user` |
| `is_like` | boolean | NO | `true` = like, `false` = dislike |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

Unique constraint: `(video_id, user_id)` — switching vote is an UPDATE, not delete+insert.

#### `engagement_comment`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `video_id` | uuid | NO | FK → `videos_video` |
| `author_id` | integer | NO | FK → `accounts_user` |
| `content` | text | NO | max 2000 |
| `parent_comment_id` | integer | YES | FK → self (max one level of nesting) |
| `is_deleted` | boolean | NO | Soft-delete flag |
| `deleted_by_id` | integer | YES | FK → `accounts_user` |
| `deletion_reason` | text | NO | |
| `reply_count` | integer | NO | Denormalised |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

#### `engagement_report`

Uses Django **GenericForeignKey** (ContentType framework) to target any model.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `reporter_id` | integer | NO | FK → `accounts_user` |
| `content_type_id` | integer | NO | FK → `django_content_type` |
| `object_id` | varchar(64) | NO | Target PK (string-encoded) |
| `reason` | varchar(24) | NO | `spam` / `harassment` / `violence` / etc. |
| `details` | text | NO | max 1000 |
| `status` | varchar(12) | NO | `pending` / `actioned` / `dismissed` |
| `reviewed_by_id` | integer | YES | FK → `accounts_user` |
| `reviewed_at` | timestamptz | YES | |
| `resolution_note` | text | NO | |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

Partial unique constraint: one pending report per (reporter, content_type, object_id).

---

### 2.5 library

#### `library_watchhistoryentry`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `user_id` | integer | NO | FK → `accounts_user` |
| `video_id` | uuid | NO | FK → `videos_video` |
| `progress_seconds` | integer | NO | Furthest point reached |
| `completed` | boolean | NO | |
| `watch_count` | integer | NO | Number of times watched |
| `first_watched_at` | timestamptz | NO | |
| `last_watched_at` | timestamptz | NO | |

Unique constraint: `(user_id, video_id)` — updated in-place, not deleted when history is cleared (clearing deletes the row only from this table, never from `engagement_view`).

#### `library_bookmark`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `user_id` | integer | NO | FK → `accounts_user` |
| `video_id` | uuid | NO | FK → `videos_video` |
| `note` | varchar(200) | NO | Optional personal note |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

Unique constraint: `(user_id, video_id)`

#### `library_follow`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `follower_id` | integer | NO | FK → `accounts_user` |
| `channel_id` | integer | NO | FK → `accounts_user` (the followed user) |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

Unique constraint: `(follower_id, channel_id)`  
Check constraint: `follower_id ≠ channel_id` (no self-follow)

---

### 2.6 live

#### `live_livechannel`

One row per user (OneToOne).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `user_id` | integer | NO | FK → `accounts_user` (UNIQUE) |
| `slug` | varchar(40) | NO | UNIQUE, public RTMP path segment |
| `title` | varchar(200) | NO | |
| `description` | text | NO | max 2000 |
| `category_id` | integer | YES | FK → `catalog_category` |
| `stream_key` | varchar(64) | NO | UNIQUE, bearer secret |
| `stream_key_rotated_at` | timestamptz | NO | |
| `status` | varchar(10) | NO | `offline` / `live` / `ended` |
| `started_at` | timestamptz | YES | |
| `ended_at` | timestamptz | YES | |
| `current_viewer_count` | integer | NO | |
| `peak_viewer_count` | integer | NO | Current-session peak |
| `all_time_peak_viewers` | integer | NO | |
| `total_sessions` | integer | NO | |
| `is_enabled` | boolean | NO | Moderation kill-switch |
| `chat_enabled` | boolean | NO | |
| `record_sessions` | boolean | NO | Auto-VOD from recording |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

#### `live_liverecording`

One row per broadcast session.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `live_channel_id` | integer | NO | FK → `live_livechannel` |
| `started_at` | timestamptz | NO | |
| `ended_at` | timestamptz | YES | null = still live |
| `peak_viewer_count` | integer | NO | |
| `chat_message_count` | integer | NO | |
| `recorded_file` | varchar(512) | NO | Path in live_recordings volume |
| `recorded_size_bytes` | bigint | NO | |
| `converted_video_id` | uuid | YES | FK → `videos_video` (after VOD conversion) |
| `conversion_error` | text | NO | |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

#### `live_livechatmessage`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `live_channel_id` | integer | NO | FK → `live_livechannel` |
| `session_id` | integer | YES | FK → `live_liverecording` |
| `user_id` | integer | NO | FK → `accounts_user` |
| `content` | text | NO | max 500 |
| `is_deleted` | boolean | NO | Soft-delete |
| `deleted_by_id` | integer | YES | FK → `accounts_user` |
| `created_at` | timestamptz | NO | |

---

### 2.7 monetization

#### `monetization_subscriptionplan`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `name` | varchar(80) | NO | |
| `slug` | varchar(90) | NO | UNIQUE |
| `description` | text | NO | |
| `price` | integer | NO | **FCFA integer** |
| `billing_period` | varchar(12) | NO | `monthly` / `quarterly` / `yearly` |
| `ad_free` | boolean | NO | Grants ad-free experience |
| `benefits` | jsonb | NO | Array of display strings |
| `is_active` | boolean | NO | |
| `display_order` | integer | NO | |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

#### `monetization_usersubscription`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `user_id` | integer | NO | FK → `accounts_user` |
| `plan_id` | integer | NO | FK → `monetization_subscriptionplan` |
| `status` | varchar(12) | NO | `pending` / `active` / `cancelled` / `expired` |
| `started_at` | timestamptz | YES | |
| `current_period_end` | timestamptz | YES | |
| `cancelled_at` | timestamptz | YES | |
| `auto_renew` | boolean | NO | |
| `renewal_failures` | smallint | NO | |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

Partial unique constraint: one `pending` or `active` subscription per user.

#### `monetization_transaction`

Primary key: `UUID`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `user_id` | integer | NO | FK → `accounts_user` (PROTECT) |
| `subscription_id` | integer | YES | FK → `monetization_usersubscription` |
| `plan_id` | integer | YES | FK → `monetization_subscriptionplan` (PROTECT) |
| `provider` | varchar(20) | NO | `orange_money` / `moov_money` / `wave` / `card` / `mock` |
| `type` | varchar(16) | NO | `subscription` / `renewal` |
| `status` | varchar(12) | NO | `pending` / `completed` / `failed` / `cancelled` |
| `amount` | integer | NO | **FCFA integer**, min 1 |
| `currency` | varchar(3) | NO | `XOF` |
| `idempotency_key` | varchar(80) | NO | **UNIQUE** — the DB-level double-payment guard |
| `provider_reference` | varchar(120) | NO | Provider's payment ID |
| `payer_identifier` | varchar(64) | NO | Mobile number or last 4 of card, never a full PAN |
| `failure_reason` | text | NO | |
| `completed_at` | timestamptz | YES | |
| `provider_payload` | jsonb | NO | Raw provider response |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

#### `monetization_webhookevent`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `provider` | varchar(20) | NO | |
| `event_id` | varchar(120) | NO | Provider-assigned event ID |
| `event_type` | varchar(60) | NO | |
| `transaction_id` | uuid | YES | FK → `monetization_transaction` |
| `payload` | jsonb | NO | Raw callback body |
| `signature_valid` | boolean | NO | |
| `processed` | boolean | NO | |
| `processed_at` | timestamptz | YES | |
| `processing_error` | text | NO | |
| `received_at` | timestamptz | NO | |

Unique constraint: `(provider, event_id)` — replay guard.

#### `monetization_adcampaign`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `advertiser_name` | varchar(120) | NO | |
| `title` | varchar(200) | NO | |
| `creative` | varchar(100) | NO | Storage path in public bucket |
| `creative_is_video` | boolean | NO | |
| `click_url` | varchar(200) | NO | |
| `placement` | varchar(12) | NO | `pre_roll` / `mid_roll` |
| `duration_seconds` | integer | NO | |
| `skippable_after_seconds` | integer | NO | 0 = non-skippable |
| `mid_roll_position` | float | NO | 0.0–1.0 fraction of video duration |
| `start_date` | timestamptz | NO | |
| `end_date` | timestamptz | NO | |
| `impression_cap` | integer | NO | 0 = unlimited |
| `impression_count` | integer | NO | Denormalised |
| `completed_count` | integer | NO | Denormalised |
| `click_count` | integer | NO | Denormalised |
| `weight` | smallint | NO | Relative rotation weight |
| `status` | varchar(10) | NO | `draft` / `active` / `paused` / `ended` |
| `created_by_id` | integer | YES | FK → `accounts_user` |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

#### `monetization_adcampaign_categories` (M2M)

| `adcampaign_id` | `category_id` |

#### `monetization_adimpression`

Primary key: `UUID`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | uuid | NO | PK |
| `campaign_id` | integer | NO | FK → `monetization_adcampaign` |
| `video_id` | uuid | YES | FK → `videos_video` (content against which ad played) |
| `viewer_id` | integer | YES | FK → `accounts_user` (null = anonymous) |
| `session_key` | varchar(64) | NO | |
| `placement` | varchar(12) | NO | |
| `played_at` | timestamptz | NO | |
| `completed` | boolean | NO | |
| `skipped` | boolean | NO | |
| `watched_seconds` | integer | NO | |
| `clicked` | boolean | NO | |

---

### 2.8 moderation

#### `moderation_moderationaction`

Immutable once written.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `moderator_id` | integer | YES | FK → `accounts_user` (SET NULL if deleted) |
| `action` | varchar(24) | NO | Action type enum |
| `content_type_id` | integer | YES | FK → `django_content_type` |
| `object_id` | varchar(64) | NO | |
| `target_repr` | varchar(255) | NO | Human-readable snapshot |
| `affected_user_id` | integer | YES | FK → `accounts_user` |
| `reason` | text | NO | Mandatory justification |
| `report_id` | integer | YES | FK → `engagement_report` |
| `metadata` | jsonb | NO | |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

#### `moderation_usersanction`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `user_id` | integer | NO | FK → `accounts_user` |
| `moderator_id` | integer | YES | FK → `accounts_user` |
| `type` | varchar(12) | NO | `warning` / `suspension` / `ban` |
| `reason` | text | NO | |
| `starts_at` | timestamptz | NO | |
| `expires_at` | timestamptz | YES | null = permanent |
| `lifted_at` | timestamptz | YES | |
| `lifted_by_id` | integer | YES | FK → `accounts_user` |
| `report_id` | integer | YES | FK → `engagement_report` |
| `created_at` | timestamptz | NO | |
| `updated_at` | timestamptz | NO | |

---

### 2.9 audit

#### `audit_auditlog`

Append-only. Never updated.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | integer | NO | PK |
| `actor_id` | integer | YES | FK → `accounts_user` (null = system/Celery task) |
| `action` | varchar(64) | NO | e.g. `video.uploaded`, `user.suspended` |
| `content_type_id` | integer | YES | FK → `django_content_type` |
| `object_id` | varchar(64) | YES | |
| `object_repr` | varchar(255) | NO | Snapshot, survives target deletion |
| `reason` | text | NO | |
| `metadata` | jsonb | NO | |
| `ip_address` | inet | YES | |
| `created_at` | timestamptz | NO | |

---

### 2.10 Django Internals

| Table | Purpose |
|---|---|
| `django_content_type` | Content-type registry for GenericForeignKey |
| `django_session` | Session storage |
| `django_migrations` | Migration history |
| `auth_permission` | Permission objects |
| `auth_group` | Permission groups |
| `token_blacklist_blacklistedtoken` | Revoked JWT refresh tokens |
| `token_blacklist_outstandingtoken` | All issued refresh tokens |
| `django_celery_beat_*` | Celery Beat schedule store |
| `django_celery_results_taskresult` | Celery task result backend |

---

## 3. Indexes

| Table | Index | Type | Purpose |
|---|---|---|---|
| `videos_video` | `(status, visibility, -published_at)` | B-tree | Feed queries |
| `videos_video` | `(uploader, -uploaded_at)` | B-tree | Studio listing |
| `videos_video` | `(-view_count)` | B-tree | Trending sort |
| `videos_video` | `(is_short, status, visibility, -published_at)` | B-tree | Shorts feed |
| `videos_video` | `search_vector` | GIN | Full-text search |
| `engagement_view` | `(video, counted, -created_at)` | B-tree | Analytics rollup |
| `engagement_view` | `(viewer, -created_at)` | B-tree | User history |
| `engagement_comment` | `(video, parent_comment, -created_at)` | B-tree | Comment thread fetch |
| `live_livechannel` | `(status, -started_at)` | B-tree | Live directory |
| `live_livechatmessage` | `(live_channel, -created_at)` | B-tree | Chat backlog fetch |
| `live_livechatmessage` | `(session, created_at)` | B-tree | Session replay |
| `monetization_transaction` | `(user, -created_at)` | B-tree | Payment history |
| `monetization_adcampaign` | `(status, start_date, end_date)` | B-tree | Eligible campaign selection |
| `monetization_adimpression` | `(campaign, -played_at)` | B-tree | Campaign analytics |
| `audit_auditlog` | `(action, -created_at)` | B-tree | Action filtering |

---

## 4. Constraints

| Table | Constraint | Description |
|---|---|---|
| `videos_videorendition` | `UNIQUE (video_id, label)` | One rendition per quality per video |
| `engagement_view` | `UNIQUE (video_id, dedup_key)` | Deduplication window |
| `engagement_like` | `UNIQUE (video_id, user_id)` | One like/dislike per user per video |
| `engagement_report` | Partial UNIQUE pending | One pending report per reporter per target |
| `library_watchhistoryentry` | `UNIQUE (user_id, video_id)` | Single resumable row per viewer per video |
| `library_bookmark` | `UNIQUE (user_id, video_id)` | |
| `library_follow` | `UNIQUE (follower_id, channel_id)` | |
| `library_follow` | `CHECK follower ≠ channel` | No self-follow |
| `monetization_usersubscription` | Partial UNIQUE active/pending | One live subscription per user |
| `monetization_transaction` | `UNIQUE idempotency_key` | **Double-payment guard** |
| `monetization_webhookevent` | `UNIQUE (provider, event_id)` | Webhook replay guard |

---

## 5. Denormalised Counters

To avoid expensive COUNT queries on every page load, several counters are maintained on the parent row:

| Counter | Location | Maintained by |
|---|---|---|
| `User.follower_count` | `accounts_user` | `library.services.toggle_follow` (recomputed from rows) |
| `User.following_count` | `accounts_user` | Same service |
| `Video.view_count` | `videos_video` | `engagement` app, F() increments + beat reconciliation |
| `Video.like_count` | `videos_video` | `engagement` app, F() increments |
| `Video.dislike_count` | `videos_video` | `engagement` app, F() increments |
| `Video.comment_count` | `videos_video` | `engagement` app, F() increments |
| `Comment.reply_count` | `engagement_comment` | `engagement` app, F() increments |
| `Tag.usage_count` | `catalog_tag` | M2M signal |
| `AdCampaign.impression_count` | `monetization_adcampaign` | F() increment at impression creation |
| `AdCampaign.completed_count` | `monetization_adcampaign` | F() increment on completion event |
| `AdCampaign.click_count` | `monetization_adcampaign` | F() increment on click event |

Counters use Django's `F()` expressions for concurrent-safe updates. The beat task `reconcile_counters` periodically recomputes `view_count` from source rows to correct any drift.

---

## 6. Soft-Delete Pattern

Rather than hard-deleting rows that would orphan related records or erase audit evidence, several tables use a soft-delete approach:

| Table | Flag | Side-effect |
|---|---|---|
| `engagement_comment` | `is_deleted` | Content hidden in API responses, text preserved for moderation |
| `live_livechatmessage` | `is_deleted` | Message hidden from chat |
| `videos_video` | `status = taken_down` | Video removed from all feeds but row kept |

Permanent hard-deletes are performed by:
- `django-cleanup` — removes orphaned media files from storage
- `sweep_expired_uploads` beat task — prunes expired `UploadSession` rows

---

## 7. Full-Text Search Vector

`videos_video.search_vector` is a `tsvector` maintained by the application (not a trigger) and indexed with a GIN index for sub-millisecond search over the full catalogue.

```
Weight A: title          (highest relevance)
Weight B: tags           (tag names joined)
Weight C: description    (lowest relevance)

Language: SEARCH_LANGUAGE_CONFIG (default: 'french')
          — controls stemming; set to 'english' in .env for English content

Update: post_save on Video + M2M changed signal for tags
        Also called at the end of the transcode pipeline once metadata is final.
```

Query pattern:
```sql
SELECT * FROM videos_video
WHERE search_vector @@ plainto_tsquery('french', ?)
ORDER BY ts_rank(search_vector, plainto_tsquery('french', ?)) DESC
```
