"""Small props built from geometry in code rather than loaded from a file.

A cigarette is a cylinder; buying or downloading one would mean another asset
with its own licence to track, on a model that is already gitignored for
exactly that reason. This one is ours, weighs nothing, and ships in the repo.

The scene parents it to a hand joint -- see `AvatarScene._attach_prop`.
"""
import math

from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData,
                          GeomVertexFormat, GeomVertexWriter, Material,
                          NodePath, Vec4)

# A real cigarette is 84mm long and 8mm across. The model stands 1.8 units
# tall, so one unit is one metre and these are simply the real dimensions.
LENGTH = 0.084
RADIUS = 0.004

FILTER_END = 0.27       # fraction of the length that is the tan filter
EMBER_START = 0.93      # the lit tip

PAPER = Vec4(0.93, 0.92, 0.88, 1.0)
FILTER = Vec4(0.78, 0.60, 0.36, 1.0)
EMBER = Vec4(1.0, 0.32, 0.05, 1.0)


def _cylinder(name: str, y0: float, y1: float, radius: float, segments: int) -> GeomNode:
    """A capped cylinder along +Y, with outward normals."""
    vdata = GeomVertexData(name, GeomVertexFormat.get_v3n3(), Geom.UHStatic)
    vertex = GeomVertexWriter(vdata, "vertex")
    normal = GeomVertexWriter(vdata, "normal")
    tris = GeomTriangles(Geom.UHStatic)

    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        x, z = math.cos(angle), math.sin(angle)
        vertex.add_data3(x * radius, y0, z * radius)
        normal.add_data3(x, 0.0, z)
        vertex.add_data3(x * radius, y1, z * radius)
        normal.add_data3(x, 0.0, z)

    for i in range(segments):
        low, high = 2 * i, 2 * i + 1
        next_low, next_high = (2 * i + 2) % (2 * segments), (2 * i + 3) % (2 * segments)
        tris.add_vertices(low, next_low, high)
        tris.add_vertices(high, next_low, next_high)

    # Caps: a fan around a centre vertex at each end.
    for y, facing in ((y0, -1.0), (y1, 1.0)):
        centre = vdata.get_num_rows()
        vertex.add_data3(0.0, y, 0.0)
        normal.add_data3(0.0, facing, 0.0)
        first = vdata.get_num_rows()
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            vertex.add_data3(math.cos(angle) * radius, y, math.sin(angle) * radius)
            normal.add_data3(0.0, facing, 0.0)
        for i in range(segments):
            rim, next_rim = first + i, first + (i + 1) % segments
            if facing < 0:
                tris.add_vertices(centre, next_rim, rim)
            else:
                tris.add_vertices(centre, rim, next_rim)

    geom = Geom(vdata)
    geom.add_primitive(tris)
    node = GeomNode(name)
    node.add_geom(geom)
    return node


def _material(name: str, colour: Vec4, emissive: bool = False) -> Material:
    material = Material(name)
    material.set_base_color(colour)
    material.set_diffuse(colour)
    material.set_roughness(0.85)
    material.set_metallic(0.0)
    if emissive:
        material.set_emission(colour)
    return material


def make_cigarette(length: float = LENGTH, radius: float = RADIUS,
                   segments: int = 10) -> NodePath:
    """A cigarette lying along +Y from the filter end at the origin."""
    cigarette = NodePath("cigarette")
    sections = (
        ("filter", 0.0, FILTER_END * length, FILTER, False),
        ("paper", FILTER_END * length, EMBER_START * length, PAPER, False),
        ("ember", EMBER_START * length, length, EMBER, True),
    )
    for name, y0, y1, colour, emissive in sections:
        part = cigarette.attach_new_node(_cylinder(name, y0, y1, radius, segments))
        part.set_material(_material(name, colour, emissive), 1)
        if emissive:
            # The lit end should not go dark when he turns away from the light.
            part.set_light_off(1)
    return cigarette
