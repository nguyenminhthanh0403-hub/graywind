"""Make the Sketchfab Johnny model convertible by panda3d-gltf.

The model is a Ready Player Me export whose `Wolf3D_Outfit_Bottom`
primitive declares TEXCOORD_1..TEXCOORD_7 all pointing at a single
accessor. panda3d-gltf miscounts vertex rows from those aliased UV sets
and then fails on the *following* mesh with "GeomTriangles references
vertices up to 1003, but GeomVertexData has only 557 rows".

Nothing in the file is malformed -- every accessor count is a consistent
1004 -- so the repair only deletes redundant attribute *references*. The
binary chunk is copied through untouched, which is why the morph targets
(mouthOpen/mouthSmile) survive; the GLB-converted download from Sketchfab
loses them.

TEXCOORD_1 is deliberately KEPT, and that is the whole subtlety here.
The primitive's data is interleaved at `byteStride` 60: POSITION 12 +
NORMAL 12 + TEXCOORD_0 8 + JOINTS_0 4 + WEIGHTS_0 16 = 52, plus the 8
bytes of the one physical extra UV set that all seven aliases point at.
panda3d-gltf derives its row count from the declared attribute sizes
rather than from byteStride, so the sum must equal the stride:

    all 7 aliases kept  -> 52 + 7*8 = 108 -> 60240/108 =  557 rows (crash)
    all 7 removed       -> 52           -> 60240/52  = 1158 rows (silent
                                                       corruption: the
                                                       trousers explode to
                                                       +/-18 units and
                                                       swallow the camera)
    exactly one kept    -> 52 + 8   = 60 -> 60240/60  = 1004 rows (correct)

Removing all of them is the dangerous case precisely because it does not
crash -- gltf2bam exits 0 and writes a model whose geometry is garbage.
`test_declared_attributes_fill_the_byte_stride` is the permanent guard.

Chunk padding is load-bearing: glTF requires every chunk to start on a
4-byte boundary and `chunkLength` to count the padding. The repaired JSON
is a different size than the original, so writing an unpadded length here
would push the BIN chunk header off alignment and corrupt the file.

Truncated input is rejected rather than repaired. A short read would
otherwise produce a structurally self-consistent output file whose
`buffers[0].byteLength` still claims the original size -- corruption that
surfaces much later, inside gltf2bam or at render time.
"""
import json
import struct
from pathlib import Path

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def _pad(data: bytes, filler: bytes) -> bytes:
    return data + filler * ((4 - len(data) % 4) % 4)


def strip_aliased_uvs(src, dst) -> int:
    """Rewrite `src` to `dst` without the *redundant* aliased UV sets.

    TEXCOORD_2 and above are dropped; TEXCOORD_1 stays so the declared
    attribute sizes still add up to the interleaved byteStride. See the
    module docstring -- removing it too converts a loud crash into silently
    corrupt geometry.

    Returns the number of attribute references removed.
    """
    src, dst = Path(src), Path(dst)
    size = src.stat().st_size
    gltf, binary = None, b""

    with open(src, "rb") as fh:
        header = fh.read(12)
        if len(header) < 12:
            raise ValueError(f"{src} is too short to be a .glb file")
        magic, _version, total = struct.unpack("<III", header)
        if magic != GLB_MAGIC:
            raise ValueError(f"{src} is not a .glb file")
        if total > size:
            raise ValueError(
                f"{src} is truncated: header declares {total} bytes, "
                f"file holds {size}"
            )
        # Bound by the header's declared length, not the file size: bytes
        # appended past the declared end would otherwise be read as a chunk
        # header and yield a garbage length.
        while fh.tell() < total:
            head = fh.read(8)
            if len(head) < 8:
                raise ValueError(f"{src} ends inside a chunk header")
            chunk_len, chunk_type = struct.unpack("<II", head)
            data = fh.read(chunk_len)
            if len(data) < chunk_len:
                raise ValueError(
                    f"{src} ends inside a chunk: expected {chunk_len} bytes, "
                    f"found {len(data)}"
                )
            if chunk_type == CHUNK_JSON:
                gltf = json.loads(data)
            elif chunk_type == CHUNK_BIN:
                binary = data

    if gltf is None:
        raise ValueError(f"{src} has no JSON chunk")

    removed = 0
    for mesh in gltf.get("meshes", []):
        for prim in mesh["primitives"]:
            extra = [
                k for k in prim["attributes"]
                if k.startswith("TEXCOORD_") and int(k.split("_")[1]) >= 2
            ]
            for key in extra:
                del prim["attributes"][key]
                removed += 1

    json_chunk = _pad(json.dumps(gltf, separators=(",", ":")).encode(), b" ")
    bin_chunk = _pad(binary, b"\x00")
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)

    with open(dst, "wb") as fh:
        fh.write(struct.pack("<III", GLB_MAGIC, 2, total))
        fh.write(struct.pack("<II", len(json_chunk), CHUNK_JSON))
        fh.write(json_chunk)
        fh.write(struct.pack("<II", len(bin_chunk), CHUNK_BIN))
        fh.write(bin_chunk)

    return removed


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "assets" / "avatar"
    removed = strip_aliased_uvs(root / "jonny.glb", root / "jonny_fixed.glb")
    print(f"removed {removed} aliased texcoord attributes")


if __name__ == "__main__":
    main()
