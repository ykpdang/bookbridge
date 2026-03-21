import pytest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from src.services.alignment_service import (
    AlignmentService,
    _resolve_storyteller_title_dir,
    probe_storyteller_transcripts,
)
from src.utils.polisher import Polisher
from src.db.models import BookAlignment

@pytest.fixture
def mock_db():
    db = MagicMock()
    session = MagicMock()
    db.get_session.return_value = session
    return db

@pytest.fixture
def service(mock_db):
    return AlignmentService(mock_db, Polisher())

def test_align_and_store_success(service, mock_db):
    ebook_text = "Alice in Wonderland"
    segments = [{'start': 0.0, 'end': 1.0, 'text': "Alice"}]
    
    # Setup Session Context
    session = mock_db.get_session()
    session.__enter__.return_value = session
    
    # Mock lower-level alignment logic (tested separately in test_generate_alignment_map)
    # We only want to verify the storage flow here
    service._generate_alignment_map = MagicMock(return_value=[{'char': 0, 'ts': 0.0}, {'char': 5, 'ts': 1.0}])
    
    # Ensure DB query returns None (Simulate no existing record)
    session.query.return_value.filter_by.return_value.first.return_value = None
    
    result = service.align_and_store("test_id", segments, ebook_text)
    
    assert result == True
    session.add.assert_called()

def test_generate_alignment_map(service):
    ebook_text = "One two three four five."
    segments = [
        {'start': 0.0, 'end': 1.0, 'text': "One two"},
        {'start': 1.0, 'end': 2.0, 'text': "three four"},
        {'start': 2.0, 'end': 3.0, 'text': "five"}
    ]
    
    # N=12 in implementation is large, so with short text it might fail finding anchors?
    # Actually, N=12 refers to N-grams of WORDS? 
    # Code: keys = [x['word'] for x in items[i:i+N]] -> Yes, 12 words.
    # So short text won't align with N=12.
    # We need longer text for this test or need to mock the constant.
    
    # Let's mock the N constant or provide long text?
    # Providing long text is safer.
    
    tokens = ["word" + str(i) for i in range(20)]
    ebook_text = " ".join(tokens)
    
    # Create segments roughly matching
    segments = []
    for i in range(20):
        segments.append({'start': float(i), 'end': float(i+1), 'text': tokens[i]})
        
    alignment_map = service._generate_alignment_map(segments, ebook_text)
    
    assert len(alignment_map) > 0
    # Should contain start (0,0) and likely some anchors
    assert alignment_map[0]['char'] == 0
    assert alignment_map[0]['ts'] == 0.0

def test_get_time_for_text(service, mock_db):
    # Mock _get_alignment return
    mock_map = [
        {'char': 0, 'ts': 0.0},
        {'char': 100, 'ts': 10.0}
    ]
    
    session = mock_db.get_session()
    session.__enter__.return_value = session
    mock_entry = MagicMock()
    mock_entry.alignment_map_json = json.dumps(mock_map)
    session.query.return_value.filter_by.return_value.first.return_value = mock_entry
    
    # Test Exact
    ts = service.get_time_for_text("test_id", "query", char_offset_hint=0)
    assert ts == 0.0
    
    # Test Interpolation (50 chars -> 5.0s)
    ts = service.get_time_for_text("test_id", "query", char_offset_hint=50)
    assert ts == 5.0


def test_probe_storyteller_transcripts_returns_ready_when_assets_not_configured():
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("STORYTELLER_ASSETS_DIR", raising=False)
        result = probe_storyteller_transcripts("Auto Book", [])

    assert result["ready"] is True
    assert result["reason"] == "assets_not_configured"


def test_probe_storyteller_transcripts_returns_not_ready_when_transcriptions_dir_missing():
    with tempfile.TemporaryDirectory() as tmp:
        assets_root = Path(tmp)
        (assets_root / "assets" / "Auto Book").mkdir(parents=True, exist_ok=True)

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("STORYTELLER_ASSETS_DIR", str(assets_root))
            result = probe_storyteller_transcripts("Auto Book", [{"start": 0.0, "end": 1.0}])

    assert result["ready"] is False
    assert result["reason"] == "transcriptions_dir_missing"


def test_probe_storyteller_transcripts_returns_not_ready_when_chapter_files_incomplete():
    with tempfile.TemporaryDirectory() as tmp:
        assets_root = Path(tmp)
        transcriptions_dir = assets_root / "assets" / "Auto Book" / "transcriptions"
        transcriptions_dir.mkdir(parents=True, exist_ok=True)
        (transcriptions_dir / "00000-00001.json").write_text(
            json.dumps({"transcript": "hello", "wordTimeline": []}),
            encoding="utf-8",
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("STORYTELLER_ASSETS_DIR", str(assets_root))
            result = probe_storyteller_transcripts(
                "Auto Book",
                [{"start": 0.0, "end": 1.0}, {"start": 1.0, "end": 2.0}],
            )

    assert result["ready"] is False
    assert result["reason"] == "chapter_set_incomplete"


def test_probe_storyteller_transcripts_returns_ready_when_validated():
    with tempfile.TemporaryDirectory() as tmp:
        assets_root = Path(tmp)
        transcriptions_dir = assets_root / "assets" / "Auto Book" / "transcriptions"
        transcriptions_dir.mkdir(parents=True, exist_ok=True)
        for idx in range(2):
            (transcriptions_dir / f"00000-{idx + 1:05d}.json").write_text(
                json.dumps({"transcript": "hello", "wordTimeline": [{"endTime": 1.0}]}),
                encoding="utf-8",
            )

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("STORYTELLER_ASSETS_DIR", str(assets_root))
            result = probe_storyteller_transcripts(
                "Auto Book",
                [{"start": 0.0, "end": 1.0}, {"start": 1.0, "end": 2.0}],
            )

    assert result["ready"] is True
    assert result["reason"] == "validated"


def test_resolve_storyteller_title_dir_prefers_suffixed_dir_with_transcriptions_over_bare_dir_without_transcriptions():
    with tempfile.TemporaryDirectory() as tmp:
        assets_root = Path(tmp)
        bare_dir = assets_root / "assets" / "Trad Wife"
        suffixed_dir = assets_root / "assets" / "Trad Wife [5j7RKcRZ]"
        bare_dir.mkdir(parents=True, exist_ok=True)
        transcriptions_dir = suffixed_dir / "transcriptions"
        transcriptions_dir.mkdir(parents=True, exist_ok=True)
        (transcriptions_dir / "00001-00001.json").write_text(
            json.dumps({"transcript": "hello", "wordTimeline": []}),
            encoding="utf-8",
        )

        result = _resolve_storyteller_title_dir(assets_root, "Trad Wife")

    assert result == suffixed_dir


def test_probe_storyteller_transcripts_uses_suffixed_storyteller_assets_dir():
    with tempfile.TemporaryDirectory() as tmp:
        assets_root = Path(tmp)
        (assets_root / "assets" / "Trad Wife").mkdir(parents=True, exist_ok=True)
        transcriptions_dir = assets_root / "assets" / "Trad Wife [5j7RKcRZ]" / "transcriptions"
        transcriptions_dir.mkdir(parents=True, exist_ok=True)
        for idx in range(2):
            (transcriptions_dir / f"00001-{idx + 1:05d}.json").write_text(
                json.dumps({"transcript": "hello", "wordTimeline": [{"endTime": 1.0}]}),
                encoding="utf-8",
            )

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("STORYTELLER_ASSETS_DIR", str(assets_root))
            result = probe_storyteller_transcripts(
                "Trad Wife",
                [{"start": 0.0, "end": 1.0}, {"start": 1.0, "end": 2.0}],
            )

    assert result["ready"] is True
    assert result["transcriptions_dir"] == transcriptions_dir


def test_resolve_storyteller_title_dir_matches_title_with_bracket_suffix_when_only_suffixed_dir_exists():
    with tempfile.TemporaryDirectory() as tmp:
        assets_root = Path(tmp)
        suffixed_dir = assets_root / "assets" / "Trad Wife [5j7RKcRZ]"
        suffixed_dir.mkdir(parents=True, exist_ok=True)

        result = _resolve_storyteller_title_dir(assets_root, "Trad Wife")

    assert result == suffixed_dir


def test_resolve_storyteller_title_dir_returns_none_when_multiple_transcript_ready_suffix_variants_exist():
    with tempfile.TemporaryDirectory() as tmp:
        assets_root = Path(tmp)
        first_dir = assets_root / "assets" / "Trad Wife [5j7RKcRZ]"
        second_dir = assets_root / "assets" / "Trad Wife [ABCD1234]"
        for folder in (first_dir, second_dir):
            transcriptions_dir = folder / "transcriptions"
            transcriptions_dir.mkdir(parents=True, exist_ok=True)
            (transcriptions_dir / "00001-00001.json").write_text(
                json.dumps({"transcript": "hello", "wordTimeline": []}),
                encoding="utf-8",
            )

        result = _resolve_storyteller_title_dir(assets_root, "Trad Wife")

    assert result is None
