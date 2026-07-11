-- Pure helpers for reading-session collapsing, shared by the SQLite and
-- LuaSettings persistence backends and by the Lua regression tests.
--
-- Adjacent sessions for the same book that start within a merge threshold of
-- the previous session's end are collapsed into one session. Reading duration
-- accumulates across merged parts so the idle gap between them never counts
-- as reading time.

local BridgeSessions = {}

-- True when `session` may be collapsed into the earlier session `prev`.
-- Merging is keyed on abs_id only: hash-only (unmatched) sessions always
-- stay separate because their book identity is not yet authoritative.
function BridgeSessions.canMerge(prev, session, threshold_seconds)
    return prev ~= nil and session ~= nil
        and session.abs_id ~= nil
        and prev.abs_id == session.abs_id
        and not prev.uploaded
        and type(prev.end_time) == "number"
        and type(session.start_time) == "number"
        and session.start_time >= prev.end_time
        and (session.start_time - prev.end_time) <= (threshold_seconds or 300)
end

-- Extend `prev` in place with the end state of `session`, accumulating the
-- actual reading duration.
function BridgeSessions.applyMerge(prev, session)
    prev.end_time = session.end_time
    prev.end_progress = session.end_progress
    if session.end_page ~= nil then
        prev.end_page = session.end_page
    end
    prev.duration_seconds = (prev.duration_seconds or 0) + (session.duration_seconds or 0)
end

-- Scan `pending` newest-first for a mergeable session and merge in place.
-- Returns true when merged, false when the caller should append `session`.
function BridgeSessions.mergeIntoPending(pending, session, threshold_seconds)
    if not session.abs_id then
        return false
    end
    for i = #pending, 1, -1 do
        local prev = pending[i]
        if BridgeSessions.canMerge(prev, session, threshold_seconds) then
            BridgeSessions.applyMerge(prev, session)
            return true
        end
    end
    return false
end

return BridgeSessions
