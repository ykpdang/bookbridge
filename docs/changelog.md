# Changelog

For the full history of changes, please refer to the **[GitHub Releases](https://github.com/cporcellijr/abs-kosync-bridge/releases)** page.

---

## [6.5.0] 2026-4-12

### What's New

= **Add CWA reading progress sync via Kobo sync protocol**
Enables bidirectional reading progress sync between the bridge and
Calibre-Web Automated using CWA's Kobo sync endpoints. This allows
stock Kobo e-readers (and KOReader via CWA) to participate in the
sync loop alongside Audiobookshelf, Storyteller, and other clients.
(Thank @dfendr)

- **KOReader plugin can now update itself.** A new "Check for Plugin Update" option appears in the Bridge Sync plugin menu (after Test Connection). It checks whether a newer version of the plugin is available on your bridge server, and if so, offers to download and install it directly from KOReader — no more downloading a ZIP from GitHub and copying it manually.

- **KOReader stats now shows all your reading activity, not just linked books.** The stats page previously only listed books that were linked in BookBridge. It now shows every book KOReader has recorded, whether linked or not. Books that are not linked appear with an "Unlinked" marker so they are easy to tell apart.

### What Changed

- **Storyteller sync no longer rejects books when the transcript file count doesn't match.** If the number of Storyteller transcript files differs from the number of ABS chapters, the bridge previously rejected the book entirely. It now uses whatever transcript files are available and derives timing from them instead. This unblocks sync for books with partial Storyteller transcripts or different chunking than ABS expected.

### Fixed

- **Progress was being silently reset to the cover in Scrivener-style EPUBs.** EPUBs produced by Scrivener — and other tools that wrap every paragraph's text in a `<span>` element — caused the bridge to generate a position reference KOReader could not resolve. KOReader would fall back to position 0 (the cover page) and write that back, erasing saved progress on every sync. The bridge now generates the correct reference for these EPUBs.

- **Storyteller sync placed you at the wrong position in some books.** Fixed a case where Storyteller could not find the right location in books that use fragment IDs for navigation. Sync positions are now accurate for these books. (Thanks @Sirozha1337)

- **Storyteller auth could fail mid-session when tokens expired.** Improved token lifetime management so the bridge no longer hits authentication errors during long Storyteller sync sessions. (Thanks @Sirozha1337)

---

## [6.4.0] - 2026-04-04

### Added

- Added an optional **Bridge Sync** KOReader plugin for pulling bridge-managed books into a device folder.
- Added **Find IDs** helpers for Audiobookshelf and Grimmory library ID settings, with dropdown pickers after lookup.
- Added an intentional **ABS disabled** mode for ebook-only or maintenance-focused deployments.
- Added Grimmory shelf and magic shelf support for **Bridge Sync** plugin collection syncing.
- Added a Grimmory shelf picker in Settings to make Bridge Sync collection setup easier.

### Changed

- The **Whisper Model** setting now accepts custom values instead of only a fixed preset list.
- Forge now uploads EPUB and audio inputs directly to Storyteller through the REST/TUS API instead of depending on a watched library hand-off.
- Added documentation for `STORYTELLER_UPLOAD_CHUNK_SIZE` so direct-upload chunk size can be tuned when needed.
- Grimmory compatibility and session handling were expanded so newer Grimmory installs behave more reliably as both ebook and audiobook sources.
- Settings now test the values currently in the form and show a restart page after saving.
- Dashboard cards now show reading session details.
- Match, Batch Match, Suggestions, and Forge now show clearer working feedback when you start an action.
- Built-in KOSync testing in Settings now works with the values currently in the form.

### Fixed

- Fixed Grimmory session writes so reading and listening sessions stay in the format Grimmory expects.
- Fixed Storyteller direct-upload metadata formatting so Forge no longer fails with `400 Invalid upload-metadata` on Storyteller `web-v2.9.3`.
- Fixed Storyteller direct-upload metadata and readiness issues that could break Forge imports.
- Fixed deadband rollback behavior so tiny audiobook-vs-ebook gaps still avoid leader flapping without pushing older ABS progress back onto newer high-confidence ebook locators.
- Fixed Grimmory progress, cache, and download edge cases that could break matching or syncing.
- Fixed several sync stability issues around finished-book suggestions, KOReader locators, and replayed instant-sync events.
- Fixed Grimmory session reporting so reading and listening sessions are recorded more reliably.
- Fixed dashboard sync warnings so old inactive states do not create misleading out-of-sync messages.
- Fixed the built-in KOSync Test button so it no longer requires saving first.

---

## [6.3.3] - 2026-03-08

### Added

- Added a dedicated **Library Suggestions** workspace with background scans, cached repeat scans, and a **Full Refresh** option.
- Added **Grimmory audiobook** support across Match, Batch Match, Suggestions, Forge, and the dashboard.
- Added more flexible linking flows, including ebook-only links, Storyteller-only links, and a **Refresh Grimmory Cache** action in Settings.

### Changed

- Match and dashboard views now show clearer source badges and audio-source details.
- Storyteller transcript ingest now accepts more real-world layouts while staying the preferred timing source when available.

### Fixed

- Fixed cross-format drift cases that could cause bounce-backs or bad resets.
- Fixed ebook-only links getting stuck in processing.
- Fixed edge cases where Storyteller-only links or stale Grimmory data could break matching or syncing.

---

## [6.3.0] - 2026-02-18

### 🚀 Features

- **Tri-Link Architecture**: Maintain a three-way link between ABS audiobook, KOReader ebook, and Storyteller entries.
- **Auto-Forge Pipeline**: Automated downloading, staging, and upload to Storyteller for processing. Triggered from the Matcher — automatically creates the sync mapping after Storyteller finishes.
- **Hardcover.app Audiobook Support**: Link specific editions and sync listening progress (in seconds).
- **Grimmory & CWA (OPDS) Integration**: Fetch ebooks from Grimmory and OPDS sources.
- **Split-Port Security Mode**: Run sync and admin UI on separate ports.
- **New Transcription Providers**: Support for Whisper.cpp Server, Deepgram API, and CUDA GPU acceleration.
- **Progress Suggestions**: Smart auto-discovery and suggestions for potential matches.
- **Telegram Notifications**: Send log alerts to a Telegram chat at a configurable severity level.
- **UI Redesign**: Horizontal dashboard cards, overhauled match pages, and responsive settings UI.

### 🐛 Fixes

- Fixed KOReader sync crashes (XPath double `body` tag issue).
- Fixed KOSync hash overwrites by Storyteller artifacts.
- Fixed race conditions in Storyteller ingestion.
- Fixed special characters in filenames breaking glob searches.
- Fixed KOSync client headers, legacy exception types, and sync position payloads.

### 🧹 Maintenance

- **Logging Standardization**: Consistent emoji prefixes and log levels across the entire codebase.
- **Unified DB Architecture**: Transitioned to SQLAlchemy for alignments, transcripts, and settings.
- **Alembic Migrations**: Improved migration tracking and safety checks.
- **Storyteller API**: Removed direct DB access in favor of strictly API-based communication.
