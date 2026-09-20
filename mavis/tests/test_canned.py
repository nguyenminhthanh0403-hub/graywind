import json

from avatar import canned, lines


def _write(root, entries, version=1):
    root.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        (root / entry["file"]).write_bytes(b"RIFF fake wav")
    (root / canned.MANIFEST_NAME).write_text(json.dumps({
        "version": version, "sample_rate": 24000, "entries": entries,
    }))


def _entry(moment, text):
    return {"moment": moment, "text": text, "hash": lines.slug(text),
            "file": f"{moment}-{lines.slug(text)}.wav", "seconds": 1.5}


def _full(root):
    _write(root, [_entry(m, t) for m, t in lines.all_lines()])


def test_missing_manifest_is_unavailable_not_an_error(tmp_path):
    voice = canned.CannedVoice(tmp_path)
    assert voice.available is False
    assert voice.path_for("greeting") is None


def test_full_catalogue_is_available(tmp_path):
    _full(tmp_path)
    voice = canned.CannedVoice(tmp_path)
    assert voice.available is True
    assert voice.missing == []


def test_path_for_returns_text_and_an_existing_file(tmp_path):
    _full(tmp_path)
    voice = canned.CannedVoice(tmp_path)
    text, path = voice.path_for("filler")
    assert text in lines.LINES["filler"]
    assert path.endswith(".wav")


def test_entry_without_its_wav_is_reported_missing(tmp_path):
    """A half-finished generation run must degrade, not crash."""
    entries = [_entry(m, t) for m, t in lines.all_lines()]
    _write(tmp_path, entries)
    (tmp_path / entries[0]["file"]).unlink()

    voice = canned.CannedVoice(tmp_path)
    assert entries[0]["text"] in voice.missing
    assert voice.available is True


def test_a_moment_with_no_audio_returns_none(tmp_path):
    entries = [_entry(m, t) for m, t in lines.all_lines()
               if m != "dismissal"]
    _write(tmp_path, entries)

    voice = canned.CannedVoice(tmp_path)
    assert voice.path_for("dismissal") is None
    assert voice.path_for("greeting") is not None


def test_entry_whose_text_is_not_in_the_catalogue_is_ignored(tmp_path):
    """An entry whose text no longer appears in lines.all_lines() -- because
    the line was edited or removed -- is rejected by the `wanted` lookup
    before any hash is even considered, so its audio is never played."""
    stale = _entry("greeting", "a line that is no longer in the catalogue")
    _write(tmp_path, [stale])

    voice = canned.CannedVoice(tmp_path)
    assert voice.path_for("greeting") is None


def test_path_for_honours_exclude(tmp_path):
    _full(tmp_path)
    voice = canned.CannedVoice(tmp_path)
    first = lines.LINES["idle"][0]
    for _ in range(40):
        text, _path = voice.path_for("idle", exclude=first)
        assert text != first


def test_unreadable_manifest_degrades_rather_than_raising(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / canned.MANIFEST_NAME).write_text("{ not json")
    voice = canned.CannedVoice(tmp_path)
    assert voice.available is False
    assert voice.path_for("idle") is None


def test_unknown_moment_returns_none(tmp_path):
    _full(tmp_path)
    voice = canned.CannedVoice(tmp_path)
    assert voice.path_for("nonsense") is None
