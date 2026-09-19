import json
import struct
from pathlib import Path

import pytest

from tools import repair_gltf

ASSET = Path(__file__).resolve().parent.parent / "assets" / "avatar" / "jonny.glb"


def _chunks(path):
    size = path.stat().st_size
    out = {}
    with open(path, "rb") as fh:
        fh.seek(12)
        while fh.tell() < size:
            chunk_len, chunk_type = struct.unpack("<II", fh.read(8))
            out[chunk_type] = fh.read(chunk_len)
    return out


def _read_gltf_json(path):
    return json.loads(_chunks(path)[0x4E4F534A])


def test_source_asset_has_the_aliased_uv_defect():
    """Guards the premise: if a future re-download lacks the defect, the
    repair is a no-op and this test says so loudly rather than silently
    passing."""
    gltf = _read_gltf_json(ASSET)
    aliased = [
        prim
        for mesh in gltf["meshes"]
        for prim in mesh["primitives"]
        if any(k.startswith("TEXCOORD_") and int(k.split("_")[1]) >= 1
               for k in prim["attributes"])
    ]
    assert aliased, "expected at least one primitive with TEXCOORD_1+"


def test_strip_aliased_uvs_removes_extra_texcoords(tmp_path):
    dst = tmp_path / "fixed.glb"
    removed = repair_gltf.strip_aliased_uvs(ASSET, dst)

    assert removed == 7
    gltf = _read_gltf_json(dst)
    for mesh in gltf["meshes"]:
        for prim in mesh["primitives"]:
            extra = [k for k in prim["attributes"]
                     if k.startswith("TEXCOORD_") and int(k.split("_")[1]) >= 1]
            assert extra == []


def test_strip_aliased_uvs_keeps_texcoord_0(tmp_path):
    dst = tmp_path / "fixed.glb"
    repair_gltf.strip_aliased_uvs(ASSET, dst)

    gltf = _read_gltf_json(dst)
    assert any("TEXCOORD_0" in prim["attributes"]
               for mesh in gltf["meshes"] for prim in mesh["primitives"])


def test_strip_aliased_uvs_preserves_morph_targets(tmp_path):
    """The whole point of repairing rather than using the GLB-converted
    download: the morphs must survive."""
    dst = tmp_path / "fixed.glb"
    repair_gltf.strip_aliased_uvs(ASSET, dst)

    gltf = _read_gltf_json(dst)
    named = [m.get("extras", {}).get("targetNames") for m in gltf["meshes"]]
    assert ["mouthOpen", "mouthSmile"] in named


def test_strip_aliased_uvs_preserves_binary_chunk_byte_for_byte(tmp_path):
    """No rstrip: trailing zero bytes are legitimate buffer content, and
    stripping them would mask a repair that silently dropped them."""
    dst = tmp_path / "fixed.glb"
    repair_gltf.strip_aliased_uvs(ASSET, dst)
    assert _chunks(dst)[0x004E4942] == _chunks(ASSET)[0x004E4942]


def test_only_texcoords_are_removed_from_any_primitive(tmp_path):
    """Guards against stripping the wrong attribute. Asserting per
    primitive matters: a test that only checks *some* primitive kept
    TEXCOORD_0 would pass even if another lost POSITION or JOINTS_0."""
    dst = tmp_path / "fixed.glb"
    repair_gltf.strip_aliased_uvs(ASSET, dst)

    before = _read_gltf_json(ASSET)
    after = _read_gltf_json(dst)

    for old_mesh, new_mesh in zip(before["meshes"], after["meshes"]):
        for old_prim, new_prim in zip(old_mesh["primitives"],
                                      new_mesh["primitives"]):
            expected = {
                k: v for k, v in old_prim["attributes"].items()
                if not (k.startswith("TEXCOORD_")
                        and int(k.split("_")[1]) >= 1)
            }
            assert new_prim["attributes"] == expected


def test_truncated_file_is_rejected_not_silently_repaired(tmp_path):
    """A short read would otherwise yield a self-consistent file whose
    buffer byteLength still claims the original size."""
    truncated = tmp_path / "cut.glb"
    truncated.write_bytes(ASSET.read_bytes()[: ASSET.stat().st_size // 2])
    with pytest.raises(ValueError):
        repair_gltf.strip_aliased_uvs(truncated, tmp_path / "out.glb")


def test_chunks_stay_four_byte_aligned(tmp_path):
    """A GLB whose JSON chunk length is not padded to 4 bytes pushes the
    BIN chunk header off alignment. The file still 'looks' fine until a
    real loader reads it."""
    dst = tmp_path / "fixed.glb"
    repair_gltf.strip_aliased_uvs(ASSET, dst)

    size = dst.stat().st_size
    with open(dst, "rb") as fh:
        total = struct.unpack("<III", fh.read(12))[2]
        while fh.tell() < size:
            assert fh.tell() % 4 == 0, "chunk header is not 4-byte aligned"
            chunk_len, _chunk_type = struct.unpack("<II", fh.read(8))
            assert chunk_len % 4 == 0, "chunk length is not padded to 4 bytes"
            fh.read(chunk_len)
    assert total == size, "header total length does not match the file"


def test_rejects_a_non_glb_file(tmp_path):
    bogus = tmp_path / "not.glb"
    bogus.write_bytes(b"\x00" * 64)
    with pytest.raises(ValueError):
        repair_gltf.strip_aliased_uvs(bogus, tmp_path / "out.glb")
