# StreamVerse — API Reference

**Base URL:** `/api/`  
**Protocol:** HTTP/1.1 + WebSocket  
**Auth:** JWT Bearer tokens (SimpleJWT)  
**Schema:** OpenAPI 3 available at `/api/schema/` · Swagger UI at `/api/docs/` · ReDoc at `/api/redoc/`

All responses use JSON. Paginated list responses follow the DRF default:
```json
{ "count": 100, "next": "...", "previous": "...", "results": [...] }
```

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Accounts](#2-accounts)
3. [Catalog](#3-catalog)
4. [Videos](#4-videos)
5. [Upload (tus)](#5-upload-tus)
6. [Engagement](#6-engagement)
7. [Library](#7-library)
8. [Search](#8-search)
9. [Live Streaming](#9-live-streaming)
10. [Monetization](#10-monetization)
11. [Moderation](#11-moderation)
12. [Admin](#12-admin)
13. [WebSocket Consumers](#13-websocket-consumers)
14. [Health](#14-health)

---

## 1. Authentication

All auth endpoints are provided by **Djoser** + **SimpleJWT**.

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/users/` | Register a new account |
| POST | `/api/auth/users/activation/` | Activate account (uid + token from email) |
| POST | `/api/auth/jwt/create/` | Login → returns `access` + `refresh` tokens |
| POST | `/api/auth/jwt/refresh/` | Exchange refresh token for new access token |
| POST | `/api/auth/jwt/verify/` | Check if an access token is valid |
| POST | `/api/auth/users/reset_password/` | Request password reset email |
| POST | `/api/auth/users/reset_password_confirm/` | Confirm password reset |
| POST | `/api/auth/users/set_password/` | Change password (authenticated) |
| GET  | `/api/auth/users/me/` | Get current user profile |

**Token format:** `Authorization: Bearer <access_token>`

Access tokens are short-lived. Refresh tokens rotate on each use and are blacklisted on logout.

---

## 2. Accounts

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/accounts/me/` | Auth | Current user profile with channel info |
| PATCH | `/api/accounts/me/` | Auth | Update the text profile (see below) |
| POST | `/api/accounts/me/password/` | Auth | Change password (`current_password`, `new_password`) |
| PUT | `/api/accounts/me/avatar/` | Auth | Replace the profile picture (multipart) |
| DELETE | `/api/accounts/me/avatar/` | Auth | Remove the profile picture |
| PUT | `/api/accounts/me/banner/` | Auth | Replace the channel banner (multipart) |
| DELETE | `/api/accounts/me/banner/` | Auth | Remove the channel banner |
| GET | `/api/accounts/channels/<username>/` | Public | Public channel profile + aggregates |
| GET | `/api/accounts/channels/<username>/videos/` | Public | Channel's published videos (`?sort=recent\|popular\|oldest`) |

### The profile

`PATCH /api/accounts/me/` accepts the text fields only:

```json
{
  "display_name": "Fatou Diallo",
  "bio": "Realisatrice a Ouagadougou.",
  "location": "Ouagadougou, Burkina Faso",
  "website_url": "https://fatou.example.com",
  "preferred_language": "fr"
}
```

`email`, `username`, `role`, `is_active` and `is_suspended` are read-only — signup and moderation own them. `website_url` must be `http`/`https`: it is rendered as an anchor on a public page.

Every write here answers with the **full** user record, not the patch, so a client can replace its cached copy instead of merging.

### Profile images

Avatar and banner have their own endpoints rather than riding along in the PATCH: an image needs decode-level validation, and replacing one has to delete the object it supersedes.

```
PUT /api/accounts/me/avatar/
Content-Type: multipart/form-data

file=<binary>
```

| Image | Max size | Max side | Field in responses |
|---|---|---|---|
| avatar | 5 MiB | 2048 px | `avatar_url` |
| banner | 10 MiB | 6000 px | `banner_url` |

Accepted formats are JPEG, PNG, WebP and GIF — decided by **decoding** the file, not by its `Content-Type` header or filename. The stored object name is generated server-side. Both endpoints return the full user record; `DELETE` on an image that is not set answers `404`.

Both `*_url` values are absolute, unsigned URLs into the public bucket, safe to render for anonymous visitors and to cache. They are `null` when no image is set — clients are expected to fall back to an initials tile.

**Public channel response:**
```json
{
  "id": 3,
  "username": "fatou",
  "display_name": "Fatou Diallo",
  "bio": "Realisatrice a Ouagadougou.",
  "location": "Ouagadougou, Burkina Faso",
  "website_url": "https://fatou.example.com",
  "avatar_url": "http://localhost:9010/streamverse-public/avatars/2026/08/3-5eb475ce7bd3.png",
  "banner_url": "http://localhost:9010/streamverse-public/banners/2026/08/3-0c1f2e58d7e7.png",
  "created_at": "2026-08-11T23:38:51Z",
  "stats": {
    "video_count": 5, "total_views": 512, "total_likes": 14,
    "total_duration_seconds": 55, "follower_count": 2
  },
  "is_following": false,
  "is_self": false
}
```

`stats` covers **public, ready** videos only, so a private upload never leaks its existence through a count. `is_following` is whether *the caller* follows this channel — never whether anyone does.

The uploader nested in a video card carries the lean shape instead (`id`, `username`, `display_name`, `bio`, `avatar_url`, `created_at`): `banner_url` and the rest would be paid for once per card on every listing.

---

## 3. Catalog

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/catalog/categories/` | Public | List all active categories |
| GET | `/api/catalog/tags/` | Public | List tags (ordered by usage) |

---

## 4. Videos

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/videos/` | Public | Paginated public video feed |
| GET | `/api/videos/?category=<slug>` | Public | Filter by category |
| GET | `/api/videos/?ordering=-view_count` | Public | Trending |
| GET | `/api/videos/<uuid>/` | Public* | Video detail + streaming URLs |
| PATCH | `/api/videos/<uuid>/` | Owner/Staff | Update title, description, visibility, category, tags |
| DELETE | `/api/videos/<uuid>/` | Owner/Staff | Delete video + all assets |
| POST | `/api/videos/<uuid>/retry/` | Owner | Re-queue failed transcode |
| POST | `/api/videos/<uuid>/visibility/` | Owner | Change visibility (public/unlisted/private) |
| GET | `/api/shorts/` | Public | Paginated Shorts feed. `?sort=shuffle\|recent\|popular\|liked\|oldest` (default `shuffle`), `?seed=` to reproduce a shuffle, `?start=<uuid>` to pin one Short first |
| GET | `/api/shorts/<uuid>/` | Public | Single Short detail |

*Unlisted videos are accessible with a direct UUID link. Private videos require auth as owner or staff.

**Video object response includes:**
- HLS master URL (signed if private, public if public/unlisted)
- Poster URL
- Sprite sheet meta (for seek-bar preview)
- Renditions list (label, width, height, bandwidth)
- Processing stage + progress (when `status=processing`)

---

## 5. Upload (tus)

Resumable upload follows the [tus protocol v1.0](https://tus.io/protocols/resumable-upload).

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/videos/upload/` | Auth | Create upload session → returns `Location` header |
| HEAD | `/api/videos/upload/<uuid>/` | Auth | Query upload offset |
| PATCH | `/api/videos/upload/<uuid>/` | Auth | Upload chunk |
| DELETE | `/api/videos/upload/<uuid>/` | Auth | Abort upload |

**Request headers for POST:**
```
Upload-Length: <total bytes>
Upload-Metadata: filename <b64>, title <b64>, description <b64>, category_id <b64>, visibility <b64>
Content-Type: application/offset+octet-stream
Tus-Resumable: 1.0.0
```

A `Video` row is created only after the final chunk lands and validation passes. The upload session then triggers the transcode Celery task. Monitor progress via WebSocket (see §13).

---

## 6. Engagement

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/videos/<uuid>/view/` | Public | Record/update a viewing session |
| GET | `/api/videos/<uuid>/like/` | Auth | Get current user's like status |
| POST | `/api/videos/<uuid>/like/` | Auth | Like or dislike (body: `{"is_like": true}`) |
| DELETE | `/api/videos/<uuid>/like/` | Auth | Remove like/dislike |
| GET | `/api/videos/<uuid>/comments/` | Public | Paginated top-level comments |
| POST | `/api/videos/<uuid>/comments/` | Auth | Post a comment |
| GET | `/api/videos/<uuid>/comments/<id>/replies/` | Public | Replies to a comment |
| POST | `/api/videos/<uuid>/comments/<id>/replies/` | Auth | Reply to a comment |
| DELETE | `/api/videos/<uuid>/comments/<id>/` | Owner/Staff | Soft-delete a comment |
| POST | `/api/reports/` | Auth | File a report against a video or comment |

**View body:**
```json
{ "watched_seconds": 45, "session_key": "abc123" }
```
The view is counted once `watched_seconds` crosses the minimum threshold (30 s or 30% of duration, whichever is shorter). Deduplication is per (video, viewer, 12-hour bucket).

---

## 7. Library

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/library/history/` | Auth | Paginated watch history |
| DELETE | `/api/library/history/` | Auth | Clear entire history |
| DELETE | `/api/library/history/<id>/` | Auth | Remove one entry |
| GET | `/api/library/bookmarks/` | Auth | Saved videos |
| POST | `/api/library/bookmarks/` | Auth | Bookmark a video (`{"video": "<uuid>"}`) |
| DELETE | `/api/library/bookmarks/<id>/` | Auth | Remove bookmark |
| GET | `/api/library/following/` | Auth | Channels the user follows |
| POST | `/api/library/follow/<username>/` | Auth | Follow a channel |
| DELETE | `/api/library/follow/<username>/` | Auth | Unfollow a channel |
| GET | `/api/library/feed/` | Auth | Videos from followed channels |

---

## 8. Search

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/search/?q=<query>` | Public | Full-text search over videos |
| GET | `/api/search/?q=<query>&category=<slug>` | Public | Search within category |
| GET | `/api/search/?q=<query>&type=shorts` | Public | Search only Shorts |

Results are ranked by `ts_rank` on the weighted tsvector field (title > tags > description). Pagination supported.

---

## 9. Live Streaming

#### Public endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/live/` | Public | List of currently live channels |
| GET | `/api/live/<slug>/` | Public | Channel detail + HLS URL |
| GET | `/api/live/<slug>/chat/` | Public | Recent chat messages (backlog) |

#### Creator endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/live/me/` | Auth | Own channel details + stream key |
| PATCH | `/api/live/me/` | Auth | Update title, description, category, chat and recording switches |
| POST | `/api/live/me/rotate-key/` | Auth | Rotate stream key (refused while live) |
| POST | `/api/live/me/webrtc-ticket/` | Auth | Mint a browser publish ticket |
| GET | `/api/live/me/sessions/` | Auth | Past broadcasts and their recordings |

#### Going live from the browser

`POST /api/live/me/webrtc-ticket/` returns where to publish and for how long:

```json
{ "publish_url": "/live-webrtc/webrtc/fatou/whip?key=<ticket>", "expires_in": 300 }
```

The client then speaks [WHIP](https://www.rfc-editor.org/rfc/rfc9725.html) to
that URL: `POST` an SDP offer, `DELETE` the returned `Location` to hang up. Two
requirements the server will not negotiate around:

* **H264 video.** The bridge copies the video track through without re-encoding
  it, so a VP8 offer would turn a cheap audio-only bridge into a full transcode.
  The client filters its codec preferences to H264 and fails loudly if the
  browser has none.
* **A ticket, not the stream key.** It is bound to one channel, expires in
  `LIVE_WHIP_TICKET_TTL_SECONDS`, and is refused while the channel is already
  live. The permanent key stays out of the browser entirely.

`can_broadcast_from_browser` on the owner's channel says whether to offer the
panel at all; no publish URL is exposed until the user actually goes live.

#### MediaMTX internal hooks (not browser-facing)

The hooks are protected by an `X-Live-Hook-Secret` header; the auth endpoint
cannot carry one and relies on network isolation. nginx returns 404 for all of
these paths at the edge.

| Method | Path | Description |
|---|---|---|
| POST | `/api/live/auth/` | Publish authorisation — stream key, browser ticket, or the bridge |
| GET | `/api/live/authz/` | Playlist authorisation, called by nginx `auth_request` |
| POST | `/api/live/hooks/ready/` | Stream went live |
| POST | `/api/live/hooks/not-ready/` | Stream ended |

A publish is accepted on three credentials: the channel's **stream key** (OBS),
a **browser ticket**, or the **hook secret** — the last only for the in-container
ffmpeg bridge, and only from loopback, so reading the secret out of a config
file does not let anyone publish as any channel.

---

## 10. Monetization

#### Subscriptions

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/monetization/plans/` | Public | Available subscription plans |
| GET | `/api/monetization/my-subscription/` | Auth | Current user's subscription status |
| POST | `/api/monetization/checkout/` | Auth | Initiate payment (`{"plan_id": 1, "provider": "orange_money"}`) |
| POST | `/api/monetization/cancel/` | Auth | Cancel auto-renewal |

#### Advertising

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/monetization/ad/select/` | Public | Select an ad to play for a video (`?video_id=<uuid>`) |
| POST | `/api/monetization/ad/<uuid>/event/` | Public | Record ad event (impression/complete/skip/click) |

#### Webhooks (provider callbacks)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/monetization/webhooks/mock/` | HMAC | Mock provider webhook |
| POST | `/api/monetization/webhooks/<provider>/` | HMAC | Real provider webhook |

---

## 11. Moderation

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/moderation/reports/` | Moderator | Pending report queue |
| POST | `/api/moderation/reports/<id>/action/` | Moderator | Action a report (dismiss, take down, warn user) |
| POST | `/api/moderation/videos/<uuid>/takedown/` | Moderator | Take down a video |
| POST | `/api/moderation/videos/<uuid>/restore/` | Moderator | Restore a taken-down video |
| POST | `/api/moderation/users/<username>/warn/` | Moderator | Issue a warning |
| POST | `/api/moderation/users/<username>/suspend/` | Moderator | Suspend account |
| POST | `/api/moderation/users/<username>/reinstate/` | Moderator | Lift suspension |
| POST | `/api/moderation/live/<slug>/disable/` | Moderator | Disable live channel |
| POST | `/api/moderation/live/<slug>/enable/` | Moderator | Re-enable live channel |
| GET | `/api/moderation/history/<username>/` | Moderator | Moderation history for a user |

---

## 12. Admin

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/monetization/campaigns/` | Admin | List ad campaigns |
| POST | `/api/monetization/campaigns/` | Admin | Create campaign |
| GET | `/api/monetization/campaigns/<id>/` | Admin | Campaign detail + stats |
| PATCH | `/api/monetization/campaigns/<id>/` | Admin | Update campaign |
| DELETE | `/api/monetization/campaigns/<id>/` | Admin | Delete draft campaign |
| POST | `/api/monetization/campaigns/<id>/activate/` | Admin | Activate campaign |
| POST | `/api/monetization/campaigns/<id>/pause/` | Admin | Pause campaign |
| GET | `/api/accounts/users/` | Admin | User list with suspension status |
| POST | `/api/accounts/users/<id>/role/` | Admin | Change user role |
| GET | `/api/audit/` | Admin | Audit log (filterable by action, actor, date) |

Django Admin (`/admin/`) provides full CRUD on all models with the Jazzmin UI skin.

---

## 13. WebSocket Consumers

Connect with a JWT token in the `Authorization` header or as a query param (`?token=<access>`).

### Transcode Progress

```
WS /ws/videos/<video-uuid>/progress/
```

Receives JSON messages while the transcode pipeline runs:
```json
{ "type": "progress", "stage": "transcoding", "progress": 42 }
{ "type": "done",     "video_id": "<uuid>" }
{ "type": "error",    "reason": "ffprobe failed: ..." }
```

### Live Chat

```
WS /ws/live/<slug>/chat/
```

**Receive** (broadcast to all connected clients):
```json
{ "type": "chat.message", "id": 123, "user": "alice", "content": "hello!", "created_at": "..." }
{ "type": "chat.delete",  "id": 123 }
```

**Send** (to post a message):
```json
{ "type": "chat.send", "content": "hello!" }
```

### Live Viewer Count

```
WS /ws/live/<slug>/viewers/
```

Receives periodic count broadcasts:
```json
{ "type": "viewer.count", "count": 142 }
```

---

## 14. Health

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/health/` | Public | Returns `{"status": "ok"}` when the service is up |

Used by the Docker Compose health check: `curl -sf http://localhost:8000/api/health/`
