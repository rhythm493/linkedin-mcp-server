# Merge Plan: stickerdaniel/linkedin-mcp-server + iushv/linkedin-agent-mcp

## Context

- **Original** (base): `stickerdaniel-orig/` — v4.13.0, 941 commits, mature infrastructure
- **Fork** (additions): `iushv-fork/` — v4.0.0, 496 commits, `job-search-manager-mcp` branch
- **Merge target**: `merged-codebase/` (copy of stickerdaniel-orig)

## Architecture Overview

### stickerdaniel-orig (base)
```
linkedin_mcp_server/
├── __main__.py           # Entry: calls cli_main.main()
├── cli_main.py           # CLI parsing, browser setup, server startup
├── server.py             # FastMCP server + tool registration
├── authentication.py     # Auth state management
├── bootstrap.py          # Background browser setup, runtime policy
├── callbacks.py          # MCP progress reporting
├── common_utils.py       # Shared utilities
├── config/               # Config management (schema, loaders)
├── core/                 # 5 files: auth.py, browser.py, exceptions.py, utils.py
├── debug_trace.py        # Page tracing
├── debug_utils.py        # Navigation stabilization
├── dependencies.py       # DI: get_ready_extractor, handle_auth_error
├── drivers/
│   └── browser.py        # Singleton browser + cookie bridge + runtime profiles
├── error_diagnostics.py  # Issue diagnostic builder
├── error_handler.py      # raise_tool_error() raises ToolError
├── exceptions.py         # App-level exceptions
├── logging_config.py
├── scraping/             # 5 files: extractor (3455 lines), fields, connection, etc.
├── sequential_tool_middleware.py
├── session_state.py      # Docker/source/derived runtime state
├── setup.py              # Profile creation
├── tools/                # 6 files: company, feed, job, messaging, person
└── utils/
```

### iushv-fork (additions)
```
linkedin_mcp_server/
├── (same entry, cli, config, logging structure — simplified)
├── core/ (14 files — the big addition)
│   ├── interactions.py   # click_element, type_text, wait_for_modal, upload_file
│   ├── pagination.py     # PaginatedResponse, cursor encode/decode
│   ├── resolver.py       # resolve_company, resolve_geo
│   ├── responses.py      # WriteResult/ReadResult structured envelopes
│   ├── safety.py         # Write quotas, browser/write locks, audit, CAPTCHA handling
│   ├── schemas.py        # PersonCard, JobCard dataclasses
│   ├── selectors.py      # LocatorChain selector registry
│   ├── throttle.py       # AdaptiveThrottle
│   └── timing.py         # Humanized delays, viewport randomization
├── tools/ (14 files — 8 new)
│   ├── _common.py        # goto_and_check, run_read_tool, run_write_tool
│   ├── saved_jobs.py     # save_job, get_saved_jobs       ← USER'S ASK
│   ├── profile.py        # update_profile_headline, set_open_to_work, +skills
│   ├── recommendations.py# get_job_recommendations
│   ├── people.py         # search_people (+match_mode), get_company_people
│   ├── post.py           # create_post, create_poll, delete_post, repost
│   ├── engagement.py     # react_to_post, comment_on_post, reply/like
│   └── network.py        # send_connection_request, invitations, follow
```

## Decisions Made

1. **Response format**: New tools use fork's structured envelopes (ReadResult/WriteResult). Original tools stay unchanged.
2. **search_people**: Fork's enhanced version replaces original's. Adds match_mode, company/geo resolution, structured PersonCard results.
3. **Reliability features**: Add all fork's core modules (throttle, timing, safety, selectors) — they complement without conflicting.

## Execution Plan

### Phase 0: Setup
- [x] Copy stickerdaniel-orig to merged-codebase/
- [ ] Initialize git in merged-codebase/
- [ ] Update pyproject.toml version

### Phase 1: Add fork's core/ modules (10 files)
Copy from `iushv-fork/linkedin_mcp_server/core/`:
1. `interactions.py` — click_element, type_text, wait_for_modal, upload_file, click_and_confirm, dismiss_modal
2. `pagination.py` — PaginatedResponse[T], encode_cursor, decode_cursor, build_paginated_response
3. `resolver.py` — resolve_company, resolve_geo (async batch resolution)
4. `responses.py` — WriteResult, ReadResult, write_success/error/dry_run/quota, read_success/error
5. `safety.py` — Write quotas (daily/session), browser/write locks, audit logs, CAPTCHA handling, confirmation
6. `schemas.py` — PersonCard, JobCard dataclasses with validators
7. `selectors.py` — LocatorChain, LocatorStrategy (AriaLabel, Role, Text, CSS), SELECTORS registry
8. `throttle.py` — AdaptiveThrottle singleton with sliding window
9. `timing.py` — navigation_delay, scroll_pause, scroll_distance, viewport_dimensions
10. `core/__init__.py` — update exports

### Phase 2: Add tools/_common.py
Port from `iushv-fork/tools/_common.py` with adaptations:
- `goto_and_check()` — navigate + rate-limit detection + retry + adaptive throttle
- `normalize_profile_url()` — canonicalize /in/<slug>/
- `extract_profile_slug()` — slug from URL/path
- `parse_count()` — "1,234" / "2.1k" → int
- `run_read_tool()` — browser lock → auth → check session → fetch → structured envelope
- `run_write_tool()` — browser lock → auth → confirm → write lock → quota → execute → audit → envelope
- `ensure_page_healthy()` — CAPTCHA pre-check

### Phase 3: Add 7 new tool files
Port each from `iushv-fork/tools/` with these adaptations:
- Replace `from mcp.types import ToolAnnotations` with original's `annotations={...}` dict
- Add `timeout` parameter to `@mcp.tool()` decorators
- Replace `handle_tool_error()` with original's `raise_tool_error()` pattern
- Update import paths to match merged structure

Files:
1. `tools/saved_jobs.py` — save_job, get_saved_jobs
2. `tools/profile.py` — update_profile_headline, set_open_to_work, add_profile_skills, set_featured_skills
3. `tools/recommendations.py` — get_job_recommendations
4. `tools/post.py` — create_post, create_poll, delete_post, repost
5. `tools/engagement.py` — react_to_post, comment_on_post, reply_to_comment, like_comment
6. `tools/network.py` — send_connection_request, get_pending_invitations, respond_to_invitation, follow_person
7. `tools/people.py` — search_people, get_company_people

### Phase 4: Update server.py
Add imports and registrations for all 7 new tool modules.
Keep all original tool registrations.
Original's `close_session` tool stays.

### Phase 5: Reconcile shared files
1. `tools/person.py` — remove original's `search_people` (replaced by people.py)
2. `tools/job.py` — merge: keep original's filter params, add fork's structured `jobs` field + DOM extraction
3. All other shared files: keep original unchanged

### Phase 6: Update metadata
- `pyproject.toml`: bump version to 4.14.0
- `README.md`: document new tools
- `AGENTS.md`: update
- `git init && git add . && git commit -m "Initial merge base"`

## Import Map (new tools)

Each new tool imports from these merged paths:

| Import | Source | Notes |
|--------|--------|-------|
| `from linkedin_mcp_server.core.pagination import ...` | fork | Added in Phase 1 |
| `from linkedin_mcp_server.core.schemas import ...` | fork | Added in Phase 1 |
| `from linkedin_mcp_server.core.selectors import SELECTORS` | fork | Added in Phase 1 |
| `from linkedin_mcp_server.core.interactions import ...` | fork | Added in Phase 1 |
| `from linkedin_mcp_server.core.responses import ...` | fork | Added in Phase 1 |
| `from linkedin_mcp_server.core.safety import ...` | fork | Added in Phase 1 |
| `from linkedin_mcp_server.core.exceptions import ...` | both | Already exists in original — fork adds InteractionError, SelectorError, QuotaExceededError, ConcurrencyError |
| `from linkedin_mcp_server.drivers.browser import ...` | both | Same API (`get_or_create_browser`, `ensure_authenticated`) |
| `from linkedin_mcp_server.error_handler import raise_tool_error` | original | Keep original pattern |
| `from linkedin_mcp_server.tools._common import ...` | fork | Added in Phase 2 |
| `from linkedin_mcp_server.tools.job import _build_job_result, ...` | original | Shared helpers needed by recommendations.py |

## Exception hierarchy additions

Fork adds these exception types under `core/exceptions.py`:
- `InteractionError` — UI interaction failures
- `SelectorError` — selector resolution failures
- `QuotaExceededError` — daily/session quota exceeded
- `ConcurrencyError` — lock contention

These need to be added to `core/exceptions.py` alongside the original's existing hierarchy.

## Tool completeness after merge

### All tools available:

**Person** → `get_person_profile`, `get_my_profile`, `search_people` (enhanced), `connect_with_person`, `get_sidebar_profiles`
**Company** → `get_company_profile`, `get_company_posts`, `search_companies`, `get_company_employees`
**Jobs** → `get_job_details`, `search_jobs`, `save_job`, `get_saved_jobs`, `get_job_recommendations`
**Profile** → `update_profile_headline`, `set_open_to_work`, `add_profile_skills`, `set_featured_skills`
**Post** → `create_post`, `create_poll`, `delete_post`, `repost`
**Engagement** → `react_to_post`, `comment_on_post`, `reply_to_comment`, `like_comment`
**Network** → `send_connection_request`, `get_pending_invitations`, `respond_to_invitation`, `follow_person`
**Messaging** → `get_inbox`, `get_conversation`, `search_conversations`, `send_message`
**Feed** → `get_feed`
**Session** → `close_session`
**Total**: ~30 tools (17 original + 13 new)
