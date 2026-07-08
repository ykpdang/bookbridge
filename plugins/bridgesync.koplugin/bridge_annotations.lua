--[[--
Two-way highlight/note sync with the bridge's annotation hub.

Each sync round, for recently-read books: upload this device's highlight
changes (new/edited since the per-book watermark) together with the complete
key list (the bridge detects deletions from keys that disappear), apply the
bridge's pending changes from other devices / BookOrbit's web reader into the
book's sidecar, and acknowledge what landed.

Positions are KOReader xpointers; only string positions sync (EPUB/rolling
documents — PDF position tables are skipped). Books currently open in the
reader are upload-only: server-side changes for them are deferred to the next
sync after the book is closed, where the sidecar merge path (annotations +
annotations_externally_modified, the same contract KOHighlights uses) lets
KOReader re-validate and re-sort on next open.
]]

local DocSettings = require("docsettings")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")
local md5 = require("ffi/sha2").md5

local MAX_BOOKS_PER_EXCHANGE = 20
local MAX_CHANGES_PER_BOOK = 50
local MAX_HISTORY_BOOKS = 30

local BridgeAnnotations = {}

local function deviceNow()
    return os.date("%Y-%m-%d %H:%M:%S")
end

-- Canonicalize an xpointer so the identity key survives crengine's
-- re-serialization (a trailing `.0` text offset and `[1]` sibling indexes come
-- and go between the authoring device and a receiving device for the SAME
-- highlight). MUST match the bridge's _normalize_xpointer_for_key. The raw
-- pos0 is still sent separately for positioning — this only feeds the key.
function BridgeAnnotations.normalizeXPointer(pos0)
    if type(pos0) ~= "string" then return "" end
    pos0 = pos0:gsub("%[1%]", "")
    pos0 = pos0:gsub("%.0$", "")
    return pos0
end

function BridgeAnnotations.buildKey(datetime, pos0)
    return md5(tostring(datetime) .. "|" .. BridgeAnnotations.normalizeXPointer(pos0))
end

-- Normalize a sidecar annotation entry into the wire format. Returns nil for
-- entries that can't sync (bookmarks without a range, PDF table positions).
function BridgeAnnotations.normalizeEntry(a)
    if type(a) ~= "table" then return nil end
    if type(a.datetime) ~= "string" or a.datetime == "" then return nil end
    if type(a.pos0) ~= "string" or a.pos0 == "" then return nil end
    if type(a.pos1) ~= "string" or a.pos1 == "" then return nil end
    local entry = {
        datetime = a.datetime,
        drawer = type(a.drawer) == "string" and a.drawer or "lighten",
        posFormat = "xpointer",
        pos0 = a.pos0,
        pos1 = a.pos1,
    }
    if type(a.datetime_updated) == "string" and a.datetime_updated ~= "" then
        entry.datetimeUpdated = a.datetime_updated
    end
    if type(a.color) == "string" and a.color ~= "" then entry.color = a.color end
    if type(a.text) == "string" and a.text ~= "" then entry.text = a.text end
    if type(a.note) == "string" and a.note ~= "" then entry.note = a.note end
    if type(a.chapter) == "string" and a.chapter ~= "" then entry.chapter = a.chapter end
    if type(a.pageno) == "number" then entry.pageno = a.pageno end
    return entry
end

-- Server entries arrive as decoded JSON, where an absent optional field is a
-- null sentinel (a function/userdata in KOReader's json lib), NOT nil. Passing
-- that straight into a KOReader annotation crashes the bookmark list ("attempt
-- to concatenate field 'note' (a function value)"). Coerce every field to its
-- expected type or nil.
local function _s(v) return type(v) == "string" and v or nil end
local function _n(v) return type(v) == "number" and v or nil end

-- A server entry mapped back into KOReader's sidecar annotation shape.
local function toSidecarEntry(entry)
    return {
        datetime = _s(entry.datetime),
        datetime_updated = _s(entry.datetimeUpdated),
        drawer = _s(entry.drawer) or "lighten",
        color = _s(entry.color),
        text = _s(entry.text),
        note = _s(entry.note),
        chapter = _s(entry.chapter),
        pageno = _n(entry.pageno),
        page = _s(entry.pos0),
        pos0 = _s(entry.pos0),
        pos1 = _s(entry.pos1),
    }
end

local function entryTimestamp(entry)
    local updated = entry.datetimeUpdated or entry.datetime_updated
    if type(updated) == "string" and updated ~= "" then
        return updated
    end
    return entry.datetime or ""
end

-- ------------------------------------------------------------------
-- Book / annotation collection
-- ------------------------------------------------------------------

local function currentReaderFile()
    local ok, ReaderUI = pcall(require, "apps/reader/readerui")
    if not ok or not ReaderUI or not ReaderUI.instance then return nil, nil end
    local instance = ReaderUI.instance
    local file = instance.document and instance.document.file or nil
    local annotations = nil
    if instance.annotation and type(instance.annotation.annotations) == "table" then
        annotations = instance.annotation.annotations
    end
    return file, annotations
end

local function bookHash(file, doc_settings)
    local stored = doc_settings and doc_settings:readSetting("partial_md5_checksum")
    if type(stored) == "string" and #stored == 32 then
        return stored:lower()
    end
    local ok, util = pcall(require, "util")
    if ok and util and type(util.partialMD5) == "function" then
        local ok2, computed = pcall(util.partialMD5, file)
        if ok2 and type(computed) == "string" and #computed == 32 then
            return computed:lower()
        end
    end
    return nil
end

-- Resolve a book's KOSync hash (sidecar-stored or computed).
function BridgeAnnotations.resolveBookHash(file, doc_settings)
    if not doc_settings and DocSettings:hasSidecarFile(file) then
        doc_settings = DocSettings:open(file)
    end
    return bookHash(file, doc_settings)
end

-- Snapshot the live annotation list into plain tables while the ReaderUI is
-- still alive, so an upload after the document closes never touches reader
-- objects and never races the sidecar flush. Mirrors the capture/run split
-- convention: capture is synchronous, the upload runs later.
function BridgeAnnotations.captureLiveBook(ui)
    if not ui or not ui.document or type(ui.document.file) ~= "string" then
        return nil
    end
    local raw = ui.annotation and ui.annotation.annotations
    if type(raw) ~= "table" then
        return nil
    end

    local hash = nil
    if ui.doc_settings and ui.doc_settings.readSetting then
        local stored = ui.doc_settings:readSetting("partial_md5_checksum")
        if type(stored) == "string" and #stored == 32 then
            hash = stored:lower()
        end
    end

    local copies = {}
    for _, a in ipairs(raw) do
        if type(a) == "table" then
            table.insert(copies, {
                datetime = a.datetime,
                datetime_updated = a.datetime_updated,
                drawer = a.drawer,
                color = a.color,
                text = a.text,
                note = a.note,
                chapter = a.chapter,
                pageno = a.pageno,
                pos0 = a.pos0,
                pos1 = a.pos1,
            })
        end
    end

    -- live=false: by the time the deferred upload runs the book is closed, so
    -- server-side changes may be merged straight into the sidecar.
    return { file = ui.document.file, hash = hash, annotations = copies, live = false }
end

-- Read one closed book's sidecar after KOReader has had a chance to flush it.
-- Used by the close hook; unlike captureLiveBook this does not depend on the
-- reader UI still being alive.
function BridgeAnnotations.collectBookByFile(file, known_hash)
    if type(file) ~= "string" or file == "" or lfs.attributes(file, "mode") ~= "file" then
        return nil
    end
    if not DocSettings:hasSidecarFile(file) then
        return nil
    end
    local doc_settings = DocSettings:open(file)
    local hash = known_hash
    if type(hash) ~= "string" or #hash ~= 32 then
        hash = bookHash(file, doc_settings)
    end
    if type(hash) ~= "string" or #hash ~= 32 then
        return nil
    end
    return {
        file = file,
        hash = hash:lower(),
        annotations = doc_settings:readSetting("annotations") or {},
        live = false,
    }
end

-- Collect candidate books: recently-read files with sidecar annotations, plus
-- books we have watermarks for (so deleting a book's last highlight still
-- propagates). Returns a list of
-- {file, hash, annotations (raw sidecar list), live (bool)}.
function BridgeAnnotations.collectBooks(watermarks)
    local books, seen = {}, {}
    local live_file, live_annotations = currentReaderFile()

    local ok_hist, ReadHistory = pcall(require, "readhistory")
    local history = (ok_hist and ReadHistory and ReadHistory.hist) or {}

    local candidates = {}
    if live_file then
        table.insert(candidates, live_file)
    end
    for index, item in ipairs(history) do
        if index > MAX_HISTORY_BOOKS then break end
        if type(item) == "table" and type(item.file) == "string" then
            table.insert(candidates, item.file)
        end
    end

    for _, file in ipairs(candidates) do
        if not seen[file] and lfs.attributes(file, "mode") == "file" then
            seen[file] = true
            local has_sidecar = DocSettings:hasSidecarFile(file)
            local is_live = (file == live_file)
            if has_sidecar or is_live then
                local doc_settings = DocSettings:open(file)
                local hash = bookHash(file, doc_settings)
                if hash then
                    local annotations
                    if is_live and live_annotations then
                        annotations = live_annotations
                    else
                        annotations = doc_settings:readSetting("annotations") or {}
                    end
                    local has_any = type(annotations) == "table" and #annotations > 0
                    local tracked = watermarks[hash] ~= nil
                    if has_any or tracked then
                        table.insert(books, {
                            file = file,
                            hash = hash,
                            annotations = annotations,
                            live = is_live,
                        })
                    end
                end
            end
        end
        if #books >= MAX_BOOKS_PER_EXCHANGE then break end
    end
    return books
end

-- Build one book's exchange payload: full key list + changes since watermark.
-- keys_complete=false marks the key list as non-authoritative for deletion
-- detection (the sweep uses this — a backfill must never delete server data
-- just because a sidecar was momentarily empty/partial).
function BridgeAnnotations.buildBookPayload(book, watermark, keys_complete, ignore_watermark)
    local keys, changes = {}, {}
    local max_seen = ""
    for _, raw in ipairs(book.annotations or {}) do
        local entry = BridgeAnnotations.normalizeEntry(raw)
        if entry then
            table.insert(keys, { k = BridgeAnnotations.buildKey(entry.datetime, entry.pos0), dt = entry.datetime })
            local stamp = entryTimestamp(entry)
            if stamp > max_seen then max_seen = stamp end
            -- ignore_watermark: the sweep re-uploads EVERYTHING so a device whose
            -- watermark drifted ahead of the server (e.g. server data was reset)
            -- can resync its whole back-catalogue.
            if (ignore_watermark or stamp > (watermark or "")) and #changes < MAX_CHANGES_PER_BOOK then
                table.insert(changes, entry)
            end
        end
    end
    return {
        hash = book.hash,
        keys = keys,
        keysComplete = keys_complete ~= false,
        changes = changes,
    }, max_seen
end

-- ------------------------------------------------------------------
-- Applying server-side changes
-- ------------------------------------------------------------------

local function findByDatetime(annotations, datetime)
    for index, a in ipairs(annotations or {}) do
        if a.datetime == datetime then
            return index
        end
    end
    return nil
end

-- Merge toApply into the closed book's sidecar. Returns ack lists.
function BridgeAnnotations.applyToSidecar(book, to_apply)
    local applied, deleted = {}, {}
    local doc_settings = DocSettings:open(book.file)
    local annotations = doc_settings:readSetting("annotations") or {}
    local changed = false

    for _, entry in ipairs(to_apply.add or {}) do
        if type(entry.pos0) == "string" and type(entry.datetime) == "string" then
            local existing = findByDatetime(annotations, entry.datetime)
            if existing then
                annotations[existing] = toSidecarEntry(entry)
            else
                table.insert(annotations, toSidecarEntry(entry))
            end
            changed = true
            table.insert(applied, { serverId = entry.serverId, version = entry.version, status = "applied" })
        end
    end

    for _, entry in ipairs(to_apply.edit or {}) do
        if type(entry.datetime) == "string" then
            local existing = findByDatetime(annotations, entry.datetime)
            if existing then
                local target = annotations[existing]
                target.drawer = _s(entry.drawer) or target.drawer
                target.color = _s(entry.color) or target.color
                if _s(entry.text) then target.text = entry.text end
                target.note = _s(entry.note)
                if _s(entry.chapter) then target.chapter = entry.chapter end
                if _s(entry.datetimeUpdated) then target.datetime_updated = entry.datetimeUpdated end
            else
                table.insert(annotations, toSidecarEntry(entry))
            end
            changed = true
            table.insert(applied, { serverId = entry.serverId, version = entry.version, status = "applied" })
        end
    end

    for _, entry in ipairs(to_apply.delete or {}) do
        if type(entry.datetime) == "string" then
            local existing = findByDatetime(annotations, entry.datetime)
            if existing then
                table.remove(annotations, existing)
                changed = true
            end
            -- Ack even when already absent locally — the tombstone is satisfied.
            table.insert(deleted, { serverId = entry.serverId, status = "applied" })
        end
    end

    if changed then
        doc_settings:saveSetting("annotations", annotations)
        -- The KOHighlights-compatible flag: KOReader re-validates, re-sorts and
        -- re-pages external annotation edits on the next open. makeTrue mirrors
        -- the reference plugins (a plain saveSetting(...,true) also works, but
        -- makeTrue is the documented idiom for boolean flags).
        if type(doc_settings.makeTrue) == "function" then
            doc_settings:makeTrue("annotations_externally_modified")
        else
            doc_settings:saveSetting("annotations_externally_modified", true)
        end
        doc_settings:flush()
    end
    return applied, deleted
end

-- Apply server changes into the CURRENTLY-OPEN book's live annotation list via
-- KOReader's own annotation module, so they render immediately AND persist
-- through KOReader's own close-flush (writing the sidecar directly races that
-- flush and loses — the bug this replaces). The book must be the open one.
function BridgeAnnotations.applyLive(to_apply)
    local ok_rui, ReaderUI = pcall(require, "apps/reader/readerui")
    if not ok_rui or not ReaderUI or not ReaderUI.instance then
        return nil  -- no open book; caller falls back to sidecar/defer
    end
    local ui = ReaderUI.instance
    if not ui.annotation or type(ui.annotation.annotations) ~= "table"
        or not ui.document or not ui.rolling then
        return nil
    end
    local Event = require("ui/event")
    local UIManager = require("ui/uimanager")
    local annotations = ui.annotation.annotations

    local applied, deleted = {}, {}
    local touched = 0

    local function resolves(pos)
        if type(pos) ~= "string" or pos == "" then return false end
        local ok, inside = pcall(function() return ui.document:isXPointerInDocument(pos) end)
        -- Treat "unknown" (call failed) as resolvable — don't drop on a probe error.
        return (not ok) or inside ~= false
    end

    for _, entry in ipairs(to_apply.add or {}) do
        if findByDatetime(annotations, entry.datetime) then
            table.insert(applied, { serverId = entry.serverId, version = entry.version, status = "applied" })
        elseif entry.posFormat == "xpointer" and resolves(entry.pos0) then
            local item = toSidecarEntry(entry)  -- type-guarded (no JSON-null sentinels)
            local ok_add = pcall(function() ui.annotation:addItem(item) end)
            if ok_add then
                pcall(function()
                    ui:handleEvent(Event:new("AnnotationsModified", { item, nb_highlights_added = 1 }))
                end)
                touched = touched + 1
                table.insert(applied, { serverId = entry.serverId, version = entry.version, status = "applied" })
            end
            -- unresolvable / failed add: do NOT ack, so it retries later
        end
    end

    for _, entry in ipairs(to_apply.edit or {}) do
        local idx = findByDatetime(annotations, entry.datetime)
        if idx then
            local a = annotations[idx]
            a.drawer = _s(entry.drawer) or a.drawer
            a.color = _s(entry.color) or a.color
            if _s(entry.text) then a.text = entry.text end
            a.note = _s(entry.note)
            if _s(entry.chapter) then a.chapter = entry.chapter end
            if _s(entry.datetimeUpdated) then a.datetime_updated = entry.datetimeUpdated end
            pcall(function()
                ui:handleEvent(Event:new("AnnotationsModified", { a, index_modified = idx }))
            end)
            touched = touched + 1
        end
        -- Ack edits either way so a missing target doesn't loop forever.
        table.insert(applied, { serverId = entry.serverId, version = entry.version, status = "applied" })
    end

    for _, entry in ipairs(to_apply.delete or {}) do
        local idx = findByDatetime(annotations, entry.datetime)
        if idx and ui.bookmark and type(ui.bookmark.removeItemByIndex) == "function" then
            pcall(function() ui.bookmark:removeItemByIndex(idx) end)
            touched = touched + 1
        end
        table.insert(deleted, { serverId = entry.serverId, status = "applied" })
    end

    if touched > 0 then
        pcall(function() UIManager:setDirty("all", "ui") end)
    end
    return applied, deleted
end

-- ------------------------------------------------------------------
-- Sync driver
-- ------------------------------------------------------------------

-- Runs one exchange round against the bridge for the given books.
-- `bridge` supplies: api (bridge_api_client), state (LuaSettings),
-- logInfo/logWarn/logErr, and _currentDeviceIdentity().
-- `books` is a list of {file, hash, annotations (sidecar-shaped list), live}.
-- Shared by the periodic sync, the on-close snapshot, and the full sweep.
-- opts.keys_complete=false makes the key lists non-authoritative for deletion
-- (the sweep passes this so a backfill never deletes server data).
function BridgeAnnotations.exchangeBooks(bridge, books, opts)
    opts = opts or {}
    local keys_complete = opts.keys_complete
    if keys_complete == nil then keys_complete = true end
    local ignore_watermark = opts.ignore_watermark
    local device, device_id = bridge:_currentDeviceIdentity()
    local watermarks = bridge.state:readSetting("annotation_watermarks") or {}

    if #books == 0 then
        return { books = 0, uploaded = 0, applied = 0, deleted = 0 }
    end

    local payload_books = {}
    local max_seen_by_hash = {}
    local uploaded = 0
    for _, book in ipairs(books) do
        -- Guard the watermark against a device clock that ran ahead: a stored
        -- future watermark would swallow every new highlight forever.
        local watermark = watermarks[book.hash] or ""
        if watermark > deviceNow() then watermark = "" end
        local book_payload, max_seen = BridgeAnnotations.buildBookPayload(book, watermark, keys_complete, ignore_watermark)
        max_seen_by_hash[book.hash] = max_seen
        uploaded = uploaded + #book_payload.changes
        table.insert(payload_books, book_payload)
    end

    local ok, response = bridge.api:exchangeAnnotations({
        device = device,
        device_id = device_id,
        books = payload_books,
    })
    if not ok then
        return nil, tostring(response or "Annotation exchange failed")
    end
    if response.enabled == false then
        return { books = 0, uploaded = 0, applied = 0, deleted = 0, disabled = true }
    end

    -- Upload landed: advance watermarks (capped at the device clock so a
    -- future-dated entry re-uploads harmlessly instead of freezing the book).
    local now = deviceNow()
    for hash, max_seen in pairs(max_seen_by_hash) do
        local advance = max_seen
        if advance > now then advance = now end
        if advance ~= "" and advance > (watermarks[hash] or "") then
            watermarks[hash] = advance
        elseif watermarks[hash] == nil then
            watermarks[hash] = ""
        end
    end
    bridge.state:saveSetting("annotation_watermarks", watermarks)
    bridge.state:flush()

    -- Apply the bridge's pending changes (closed books only) and ack.
    local books_by_hash = {}
    for _, book in ipairs(books) do books_by_hash[book.hash] = book end

    local ack_books = {}
    local applied_total, deleted_total = 0, 0
    for _, result in ipairs(response.books or {}) do
        local book = books_by_hash[result.hash]
        local to_apply = result.toApply or {}
        local pending = #(to_apply.add or {}) + #(to_apply.edit or {}) + #(to_apply.delete or {})
        if book and pending > 0 then
            local applied, deleted
            if opts.upload_only then
                -- Close snapshot: only push this session's highlights. Received
                -- changes for the just-closed book are applied by the next
                -- periodic sync (its live/closed path), never a sidecar write
                -- that races KOReader's own close-flush.
                bridge:logInfo("Annotation sync: close snapshot, deferring", tostring(pending), "server change(s)")
            elseif book.live then
                -- Open book: apply into KOReader's live list (instant + survives
                -- the close-flush). If the reader vanished mid-cycle, leave it
                -- for the next round rather than racing the sidecar.
                applied, deleted = BridgeAnnotations.applyLive(to_apply)
                if applied == nil then
                    bridge:logInfo("Annotation sync: open book but no live reader, deferring", tostring(pending))
                end
            else
                local ok_apply, a, d = pcall(BridgeAnnotations.applyToSidecar, book, to_apply)
                if ok_apply then
                    applied, deleted = a, d
                else
                    bridge:logWarn("Annotation sync: sidecar apply failed:", tostring(a))
                end
            end
            if applied or deleted then
                applied_total = applied_total + #(applied or {})
                deleted_total = deleted_total + #(deleted or {})
                if (applied and #applied > 0) or (deleted and #deleted > 0) then
                    table.insert(ack_books, { hash = result.hash, applied = applied or {}, deleted = deleted or {} })
                end
            end
        end
    end

    if #ack_books > 0 then
        local ok_ack, ack_err = bridge.api:ackAnnotations({
            device = device,
            device_id = device_id,
            books = ack_books,
        })
        if not ok_ack then
            bridge:logWarn("Annotation sync: ack failed:", tostring(ack_err))
        end
    end

    return {
        books = #books,
        uploaded = uploaded,
        applied = applied_total,
        deleted = deleted_total,
    }
end

-- Periodic sync entry point: recent books + watermark-tracked books.
function BridgeAnnotations.run(bridge)
    local watermarks = bridge.state:readSetting("annotation_watermarks") or {}
    local books = BridgeAnnotations.collectBooks(watermarks)
    if #books == 0 then
        return { books = 0, uploaded = 0, applied = 0, deleted = 0 }
    end
    return BridgeAnnotations.exchangeBooks(bridge, books)
end

return BridgeAnnotations
