# Release Notes - 7.1.1

The headline change is **reader-owned integrations and BookFusion support**. BookBridge now gives every reader a self-service place to manage their own service accounts, adds BookFusion progress and highlight sync, and expands the list/collection bridge work introduced around 7.1.

Highlight and note sync still requires the **BridgeSync KOReader plugin from 7.1.0 or newer**. Standard KOReader/KOSync progress sync continues to work without it, but annotation exchange, sweep, close-capture, and managed collection features use the updated plugin.

## Added

- **BookFusion progress and highlight sync** - readers can link their own BookFusion account, sync reading progress by percentage, and relay BookFusion highlights through the annotation hub. BookFusion positions use a fresh UTF-16 offset/xpointer mapper, and uploading books to BookFusion is intentionally not part of this release.
- **Self-service reader integrations** - each signed-in reader now has Account -> My Integrations, where they can manage service usernames, passwords, tokens, API keys, and per-user sync toggles. Admins can still manage those same fields for any reader from Settings -> Users.
- **Readest and Hardcover annotation spokes** - Readest cloud highlights and Hardcover annotations can participate in the annotation hub using each reader's own account configuration.
- **BridgeSync collections from Grimmory or Hardcover** - KOReader collection manifests can use either Grimmory shelves or Hardcover lists as the source, configured per reader.
- **Grimmory shelves to Hardcover lists** - readers can optionally mirror Grimmory shelf membership into Hardcover lists, with modes for all shelves, magic shelves, or regular shelves.

## Changed

- **Integration settings follow the reader** - user-owned credentials live with the reader, either in Account -> My Integrations or in the admin-managed user integrations page. Global Settings keep shared engine behavior such as server URLs, poll intervals, and daemon-level options.
- **KOReader collection controls are per-reader** - the collection source selector now lives under each reader's KOReader Collections integration group, making Hardcover-list collections discoverable even when Grimmory is disabled.
- **Readest uses per-user email/password authentication** - Readest highlight sync logs in with each reader's own account and caches tokens for that reader.
- **Settings and account pages explain the split** - admin integration pages point readers to Account -> My Integrations, and BookFusion forms link to BookFusion's Calibre integration page for manual API-key setup.

## Operational Notes

Database migrations apply automatically on startup. BookFusion support syncs progress and highlights only; uploading books to BookFusion is not included. Web-reader annotation sync depends on the matching source credentials being configured for each reader.
