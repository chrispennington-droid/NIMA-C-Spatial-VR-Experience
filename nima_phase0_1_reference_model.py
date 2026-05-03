"""
nima_phase0_1_reference_model.py

NIMA Phase II - Tyler Prove-Out Facility
Phase 0/1 Diagnostic Reference / Blockout Model

Purpose:
    Lightweight 1:1 scale interior reference/blockout model used for layout,
    scale, ceiling-height, circulation, material-flow, equipment-fit and
    F1<->F2 relationship verification inside Blender, then exported to FBX
    for Unity / Spatial walkthroughs.

This is NOT:
    - A digital twin
    - A BIM model
    - A photoreal render
    - A final architectural model

Hard rules enforced by this script:
    - Blender units = meters, 1 unit = 1 m
    - 1 grid square = 8 ft = 2.4384 m
    - +X = East, +Y = North, +Z = Up
    - No elevator (no elevator object, void, material, or label - anywhere)
    - No stair geometry (only an import zone)
    - No reception (no reception zone, marker, label, or geometry - anywhere)
    - No exterior shell, no forklift / crane sim
    - No final walls / final doors yet
    - F2 overlook is a 4-point verified POLYGON, never a bbox rectangle
    - GRND/RECYC + Pallet plate is flush at Z = 3.09 m (no 3-inch step)

Run inside Blender:
    Blender > Scripting workspace > Open > nima_phase0_1_reference_model.py > Run
    or from CLI:
        blender --background --python nima_phase0_1_reference_model.py

Outputs (written next to this script):
    NIMA_Phase0_1_Reference_Blockout.blend
    NIMA_Phase0_1_Reference_Blockout.fbx
"""

import os
import math
import bpy
import bmesh
from mathutils import Vector, Matrix


# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------

GRID_SIZE_M = 2.4384            # 8 ft = 2.4384 m
FT_TO_M = 0.3048

# Purple reference boundaries (in GRID units)
BOUND_OUTER = 22
BOUND_INNER = 16

# Heights (already in meters)
H_F1                = 3.09      # 10.13 ft
H_F2_SLAB_BASE      = 3.09
H_F2_SLAB_TOP       = 3.39
H_F2_SLAB_THICK     = 0.30
H_F2_TOP            = 5.99      # 19.64 ft, F2 occupied ceiling reference
H_HIGHBAY           = 10.31     # 33.81 ft
H_ROOF_REF          = 11.91     # 39.08 ft, REFERENCE ONLY, not occupied

# GRND/RECYC plate (3 in steel plate, top flush with F2 reference)
H_PLATE_BOTTOM      = 3.0138
H_PLATE_TOP         = 3.09
PLATE_THICK         = 0.0762    # 3 in

# Stair opening / import zone (in GRID units for X/Y; Z in meters)
# Excel master list ZONE_STAIRS: X [-9, -5.3592089], Y [-1, 0.25], Z [0, 3.39].
# (User-provided precise SVG points -0.0893314 / 0.12511772 are the opening
# hole inside this broader zone; the Excel zone is authoritative.)
STAIR_X_MIN = -9.0
STAIR_X_MAX = -5.3592089
STAIR_Y_MIN = -1.0
STAIR_Y_MAX =  0.25
STAIR_Z_BASE = 0.0
STAIR_Z_TOP  = 3.39

# Precise stair-opening hole inside the broader zone (kept as a debug overlay).
STAIR_HOLE_X_MIN = -9.0
STAIR_HOLE_X_MAX = -5.3592089
STAIR_HOLE_Y_MIN = -0.0893314
STAIR_HOLE_Y_MAX =  0.12511772

# Spawn (in GRID units for X/Y; spawn is at floor level Z = 0)
SPAWN_X = -10.6043320328266
SPAWN_Y = -1.5170187
SPAWN_FACING = "S"   # facing South => -Y

# F2 overlook 4 verified corners (GRID units). Order: NE, NW, SW, SE.
F2_OVERLOOK_POLYGON = [
    (-3.5425804,         2.32234629),     # NE
    (-5.9055563,         2.32248083),     # NW
    (-6.4485403,        -1.0574465),      # SW
    (-4.13278622359747, -2.06928561818916) # SE
]

# High-Bay angle break debug line (3 vertices in GRID units, at floor level)
HIGHBAY_ANGLE_LINE_PTS = [
    (-10.0,        -1.0),
    (-5.547289,    -1.0),
    (-5.0,          2.0),
]

# Overhead door placeholder width (VERIFY). 1.5 grid = 12 ft = 3.6576 m.
OVERHEAD_DOOR_W_M = 1.5 * GRID_SIZE_M

# Mezz loading gate (VERIFY before Phase 5)
MEZZ_GATE_HEIGHT_M = 3.0 * FT_TO_M       # 0.9144 m
MEZZ_GATE_WIDTH_M  = 37.21 * FT_TO_M     # ~ 11.34 m

# -----------------------------------------------------------------------------
# MASTER LIST DATA (sourced from
# NIMA_Phase2_Master_Coordinate_Geometry_Confidence_List_Clean.xlsx)
# -----------------------------------------------------------------------------
# All X/Y values are in GRID UNITS unless suffixed _M.
# Tuple format for bbox zones:
#     (id, min_xg, max_xg, min_yg, max_yg, base_z_m, top_z_m, mat_key)

MASTER_F1_ZONES = [
    ("ZONE_LOBBY_CTX",        -14.3, -5.5, -5.0,  0.9, 0.0,        H_F1,        "MAT_Floor_TanCeramicTile"),
    ("ZONE_CONNECTOR_PATH",   -14.2, -6.0, -2.4,  0.2, 0.0,        0.02,        "MAT_Debug_VERIFY_Transparent"),
    ("ZONE_OFFICELAB_TRANS",   -6.3, -4.9, -5.4, -0.6, 0.0,        H_F1,        "MAT_Floor_TanCeramicTile"),
    ("ZONE_HIGHBAY",           -4.7,  3.2, -6.6, 10.5, 0.0,        H_HIGHBAY,   "MAT_HighBay_ConcreteSlab"),
    ("ZONE_GRND_RECYC",        -1.0,  2.2, -7.3, -5.5, 0.0,        H_F1,        "MAT_HighBay_SolidIndustrialWall"),
]

MASTER_F2_ZONES = [
    ("ZONE_HIGHBAY_OVERLOOK",  -6.0, -4.2, -1.3,  1.1, H_F2_SLAB_BASE, H_F2_TOP,    "MAT_Floor_TanCeramicTile"),
    ("ZONE_HIGHBAY_VOID",      -4.7,  3.2, -0.5, 10.5, H_F2_SLAB_BASE, H_HIGHBAY,   "MAT_Debug_VERIFY_Transparent"),
    ("ZONE_MEZZ",              -7.1, -5.1, -5.6, -3.4, H_F2_SLAB_BASE, H_F2_TOP,    "MAT_Wall_WarmCreamPaint"),
    ("ZONE_PALLET",            -1.0,  2.2, -7.3, -5.5, H_F2_SLAB_BASE, H_F2_TOP,    "MAT_HighBay_SolidIndustrialWall"),
]

# Excel-authoritative HighBay footprint and rotation extents.
HIGHBAY_BBOX_GRID = (-4.7, 3.2, -6.6, 10.5)

# Doors. (id, x_grid, y_grid, function, floor)
# function in {WORKING, CLOSED_NONWORKING, OVERHEAD_CLOSED}.
MASTER_DOORS = [
    # F1
    ("D_F1_A",       -11.0,  -0.2, "CLOSED_NONWORKING", "F1"),
    ("D_F1_B",       -10.9,  -1.1, "CLOSED_NONWORKING", "F1"),
    ("D_F1_WORK_A",   -5.5,  -1.0, "WORKING",           "F1"),
    ("D_F1_C",        -5.9,  -3.5, "CLOSED_NONWORKING", "F1"),
    ("D_F1_D",        -6.1,  -4.6, "CLOSED_NONWORKING", "F1"),
    ("D_F1_OH_A",     -6.2,  -6.8, "OVERHEAD_CLOSED",   "F1"),
    ("D_F1_OH_B",     -4.7,  -7.1, "OVERHEAD_CLOSED",   "F1"),
    ("D_F1_OH_C",     -2.9,  -7.4, "OVERHEAD_CLOSED",   "F1"),
    ("D_F1_E",        -1.4,  -7.4, "CLOSED_NONWORKING", "F1"),
    ("D_F1_F",        -0.5,  -5.6, "CLOSED_NONWORKING", "F1"),
    ("D_F1_G",        -3.4,  10.1, "CLOSED_NONWORKING", "F1"),
    # F2
    ("D_F2_A",       -13.1,  -3.7, "CLOSED_NONWORKING", "F2"),
    ("D_F2_B",       -12.5,  -3.8, "CLOSED_NONWORKING", "F2"),
    ("D_F2_C",        -8.8,  -4.6, "CLOSED_NONWORKING", "F2"),
    ("D_F2_D",        -7.6,  -3.3, "CLOSED_NONWORKING", "F2"),
    ("D_F2_E",        -5.5,  -2.1, "CLOSED_NONWORKING", "F2"),
    ("D_F2_F",       -12.0,  -0.1, "CLOSED_NONWORKING", "F2"),
    ("D_F2_G",       -11.5,   0.0, "CLOSED_NONWORKING", "F2"),
    ("D_F2_H",        -5.2,   0.9, "CLOSED_NONWORKING", "F2"),
]

# F1 door height = 2.13 m (84 in), starts at Z 0.
# F2 door height = 2.13 m, starts at Z 3.09.
# Overhead door height = 3.05 m, width = 1.5 grid placeholder, VERIFY.
DOOR_HEIGHT_MAN_M       = 2.13
DOOR_HEIGHT_OVERHEAD_M  = 3.05
DOOR_WIDTH_MAN_M        = 0.91   # 36 in, single-leaf placeholder

# Output paths (next to script)
SCRIPT_DIR = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.getcwd()
OUT_BLEND = os.path.join(SCRIPT_DIR, "NIMA_Phase0_1_Reference_Blockout.blend")
OUT_FBX   = os.path.join(SCRIPT_DIR, "NIMA_Phase0_1_Reference_Blockout.fbx")


# -----------------------------------------------------------------------------
# SCENE RESET / UNITS
# -----------------------------------------------------------------------------

def reset_scene():
    # Wipe everything for a clean diagnostic build.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = 'METERS'
    # Make selection / world a known good state.
    scene.world = bpy.data.worlds.new("NIMA_World") if scene.world is None else scene.world


# -----------------------------------------------------------------------------
# COLLECTION HELPERS
# -----------------------------------------------------------------------------

COLLECTIONS = [
    "00_REFERENCE_GRID",
    "01_DEBUG_BOUNDARIES",
    "02_HEIGHT_POSTS",
    "03_SPAWN",
    "04_F1_ZONE_OVERLAYS",
    "05_HIGHBAY_ROTATION_OVERLAYS",
    "06_F2_SLAB_AND_POLYGON_OVERLAYS",
    "07_CUTOUT_AND_VOID_MARKERS",
    "08_DOOR_WINDOW_GLASS_MARKERS",
    "09_STACKING_AND_CAGE_MARKERS",
    "10_IMPORT_ZONES",
    "11_REVIEW_CAMERAS",
]


def add_collection(name):
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    return coll


def link_to(coll, obj):
    # Move obj to coll, removing from any other collections (incl. scene root).
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll.objects.link(obj)


# -----------------------------------------------------------------------------
# UNIT HELPERS
# -----------------------------------------------------------------------------

def grid_to_m(x_grid, y_grid):
    """Convert grid-unit (X, Y) to meters."""
    return (x_grid * GRID_SIZE_M, y_grid * GRID_SIZE_M)


# -----------------------------------------------------------------------------
# MATERIALS
# -----------------------------------------------------------------------------

def _mk_mat(name, rgba, alpha=1.0, emit_strength=0.0):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = rgba
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = alpha
        if emit_strength > 0 and "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = emit_strength
    if alpha < 1.0:
        # Property names differ across Blender versions (4.2+ removed shadow_method).
        if hasattr(mat, "blend_method"):
            mat.blend_method = 'BLEND'
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = 'NONE'
    return mat


def build_materials():
    return {
        "MAT_Debug_Grid":               _mk_mat("MAT_Debug_Grid",               (0.55, 0.55, 0.55, 1.0)),
        "MAT_Debug_PurpleBoundary":     _mk_mat("MAT_Debug_PurpleBoundary",     (0.55, 0.20, 0.85, 1.0)),
        "MAT_Debug_SpawnRed":           _mk_mat("MAT_Debug_SpawnRed",           (1.00, 0.05, 0.05, 1.0)),
        "MAT_Debug_SpawnArrow":         _mk_mat("MAT_Debug_SpawnArrow",         (1.00, 0.55, 0.00, 1.0)),
        "MAT_Debug_Height_F1":          _mk_mat("MAT_Debug_Height_F1",          (0.20, 0.70, 1.00, 1.0)),
        "MAT_Debug_Height_F2":          _mk_mat("MAT_Debug_Height_F2",          (0.20, 1.00, 0.50, 1.0)),
        "MAT_Debug_Height_HighBay":     _mk_mat("MAT_Debug_Height_HighBay",     (1.00, 0.85, 0.10, 1.0)),
        "MAT_Debug_Height_RoofReference":_mk_mat("MAT_Debug_Height_RoofReference",(0.85, 0.85, 0.85, 1.0)),
        "MAT_Debug_VERIFY_Transparent": _mk_mat("MAT_Debug_VERIFY_Transparent", (1.00, 0.10, 0.65, 0.18), alpha=0.18),
        "MAT_Debug_HighBay_Unrotated":  _mk_mat("MAT_Debug_HighBay_Unrotated",  (0.10, 0.55, 1.00, 0.30), alpha=0.30),
        "MAT_Debug_HighBay_Rotated10":  _mk_mat("MAT_Debug_HighBay_Rotated10",  (1.00, 0.30, 0.30, 0.30), alpha=0.30),
        "MAT_Floor_TanCeramicTile":     _mk_mat("MAT_Floor_TanCeramicTile",     (0.82, 0.72, 0.55, 1.0)),
        "MAT_Floor_DarkPolishedStoneInlay":_mk_mat("MAT_Floor_DarkPolishedStoneInlay",(0.18, 0.16, 0.16, 1.0)),
        "MAT_Wall_WarmCreamPaint":      _mk_mat("MAT_Wall_WarmCreamPaint",      (0.95, 0.90, 0.78, 1.0)),
        "MAT_Glass_ClearArchitectural": _mk_mat("MAT_Glass_ClearArchitectural", (0.55, 0.85, 1.00, 0.25), alpha=0.25),
        "MAT_Guard_BlackPaintedMetal":  _mk_mat("MAT_Guard_BlackPaintedMetal",  (0.06, 0.06, 0.06, 1.0)),
        "MAT_HighBay_ConcreteSlab":     _mk_mat("MAT_HighBay_ConcreteSlab",     (0.55, 0.55, 0.55, 1.0)),
        "MAT_HighBay_SolidIndustrialWall":_mk_mat("MAT_HighBay_SolidIndustrialWall",(0.40, 0.42, 0.45, 1.0)),
        "MAT_Door_ClosedNonWorking":    _mk_mat("MAT_Door_ClosedNonWorking",    (1.00, 0.00, 0.85, 1.0)),    # magenta
        "MAT_Door_Working":             _mk_mat("MAT_Door_Working",             (1.00, 0.95, 0.10, 1.0)),    # yellow
        "MAT_Window_Trumatch34b":       _mk_mat("MAT_Window_Trumatch34b",       (0.96, 0.85, 0.45, 1.0)),    # Trumatch 34-b approx
        "MAT_GlassWall_Trumatch31d":    _mk_mat("MAT_GlassWall_Trumatch31d",    (0.55, 0.78, 0.95, 1.0)),    # Trumatch 31-d approx
        "MAT_Cage_WireMetal":           _mk_mat("MAT_Cage_WireMetal",           (0.30, 0.30, 0.32, 0.55), alpha=0.55),
        "MAT_Plate_Steel":              _mk_mat("MAT_Plate_Steel",              (0.50, 0.50, 0.55, 1.0)),
        "MAT_Gate_MetalSafety":         _mk_mat("MAT_Gate_MetalSafety",         (1.00, 0.55, 0.00, 1.0)),
        "MAT_DoorMarker_Cyan":          _mk_mat("MAT_DoorMarker_Cyan",          (0.10, 0.95, 0.95, 1.0)),    # cyan glass curtain
    }


# -----------------------------------------------------------------------------
# PRIMITIVE / GEOMETRY HELPERS
# -----------------------------------------------------------------------------

def _new_mesh_obj(name, verts, edges=(), faces=(), coll=None, mat=None):
    me = bpy.data.meshes.new(name + "_MESH")
    me.from_pydata(verts, edges, faces)
    me.update()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    if coll is not None:
        link_to(coll, obj)
    if mat is not None:
        obj.data.materials.append(mat)
    return obj


def add_label(name, text, location, size=0.4, coll=None, mat=None):
    txt = bpy.data.curves.new(name + "_TXT", type='FONT')
    txt.body = text
    txt.size = size
    obj = bpy.data.objects.new(name, txt)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    if coll is not None:
        link_to(coll, obj)
    if mat is not None:
        obj.data.materials.append(mat)
    return obj


def add_debug_line(name, start, end, mat=None, coll=None):
    # start/end already in meters, 3D.
    return _new_mesh_obj(name, [start, end], edges=[(0, 1)], coll=coll, mat=mat)


def add_rect_outline(name, min_x, max_x, min_y, max_y, z, mat=None, coll=None):
    # min/max in METERS already.
    v = [(min_x, min_y, z), (max_x, min_y, z), (max_x, max_y, z), (min_x, max_y, z)]
    e = [(0, 1), (1, 2), (2, 3), (3, 0)]
    return _new_mesh_obj(name, v, edges=e, coll=coll, mat=mat)


def add_transparent_box_from_bbox(name, min_x, max_x, min_y, max_y, base_z, top_z, mat=None, coll=None):
    # min/max in METERS already.
    v = [
        (min_x, min_y, base_z), (max_x, min_y, base_z),
        (max_x, max_y, base_z), (min_x, max_y, base_z),
        (min_x, min_y, top_z),  (max_x, min_y, top_z),
        (max_x, max_y, top_z),  (min_x, max_y, top_z),
    ]
    f = [
        (0, 1, 2, 3),    # bottom
        (4, 5, 6, 7),    # top
        (0, 1, 5, 4),    # south
        (1, 2, 6, 5),    # east
        (2, 3, 7, 6),    # north
        (3, 0, 4, 7),    # west
    ]
    return _new_mesh_obj(name, v, faces=f, coll=coll, mat=mat)


def add_polygon_plane_or_outline(name, points_grid, z, mat=None, coll=None, outline_too=True):
    """
    Build a true polygon (flat plane) from a list of (x_grid, y_grid) corners.
    Adds both a filled plane and a closed outline (so the verified shape is
    obvious from above, not a derived bbox).
    """
    pts_m = []
    for (xg, yg) in points_grid:
        x, y = grid_to_m(xg, yg)
        pts_m.append((x, y, z))

    n = len(pts_m)
    face = [tuple(range(n))]
    poly = _new_mesh_obj(name, pts_m, faces=face, coll=coll, mat=mat)

    if outline_too:
        edges = [(i, (i + 1) % n) for i in range(n)]
        outline = _new_mesh_obj(name + "_OUTLINE", pts_m, edges=edges, coll=coll, mat=mat)
        outline.location.z += 0.005  # nudge outline above the plane to avoid z-fight
    return poly


def add_height_post(name, x_grid, y_grid, height_m, mat=None, coll=None, label_text=None):
    x, y = grid_to_m(x_grid, y_grid)
    # Thin vertical post (square cross section, ~6 cm).
    s = 0.03
    v = [
        (x - s, y - s, 0.0), (x + s, y - s, 0.0),
        (x + s, y + s, 0.0), (x - s, y + s, 0.0),
        (x - s, y - s, height_m), (x + s, y - s, height_m),
        (x + s, y + s, height_m), (x - s, y + s, height_m),
    ]
    f = [
        (0, 1, 2, 3), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5),
        (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    obj = _new_mesh_obj(name, v, faces=f, coll=coll, mat=mat)
    if label_text:
        add_label(
            name + "_LBL",
            f"{label_text} ({height_m:.2f} m / {height_m / FT_TO_M:.2f} ft)",
            (x + 0.1, y, height_m + 0.15),
            size=0.25, coll=coll
        )
    return obj


def add_door_marker(name, x_grid, y_grid, marker_type, mat=None, coll=None,
                    width_m=0.9, depth_m=0.08, height_m=2.1, rotation_z_deg=0.0):
    """
    marker_type one of:
      'WORKING'           - yellow box
      'CLOSED_NONWORKING' - magenta box
      'CYAN_GLASS'        - cyan thin panel
      'OVERHEAD_CLOSED'   - VERIFY-pink wide flat marker
      'GLASS_DOOR'        - clear glass thin panel
      'PAIR_NOTE'         - identical to its base type but suffixed for double-door pair
    """
    x, y = grid_to_m(x_grid, y_grid)
    hx = width_m * 0.5
    hy = depth_m * 0.5
    v = [
        (-hx, -hy, 0.0), (hx, -hy, 0.0), (hx, hy, 0.0), (-hx, hy, 0.0),
        (-hx, -hy, height_m), (hx, -hy, height_m), (hx, hy, height_m), (-hx, hy, height_m),
    ]
    f = [
        (0, 1, 2, 3), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5),
        (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    obj = _new_mesh_obj(name, v, faces=f, coll=coll, mat=mat)
    obj.rotation_euler[2] = math.radians(rotation_z_deg)
    obj.location = (x, y, 0.0)
    return obj


def add_arrow_marker(name, x_grid, y_grid, facing_direction, mat=None, coll=None,
                     length_m=1.2, head_m=0.4, z=0.02):
    """
    facing_direction: 'N' / 'S' / 'E' / 'W'
    Draws a flat arrow on the floor pointing the given direction.
    """
    x, y = grid_to_m(x_grid, y_grid)

    # Build arrow in local +X then rotate.
    half_w = 0.10
    v = [
        (0.0,        -half_w, 0.0),
        (length_m,   -half_w, 0.0),
        (length_m,    half_w, 0.0),
        (0.0,         half_w, 0.0),
        # Arrow head
        (length_m,           -head_m, 0.0),
        (length_m + head_m,    0.0,   0.0),
        (length_m,            head_m, 0.0),
    ]
    f = [(0, 1, 2, 3), (4, 5, 6)]
    obj = _new_mesh_obj(name, v, faces=f, coll=coll, mat=mat)

    rot_map = {"E": 0.0, "N": 90.0, "W": 180.0, "S": 270.0}
    obj.rotation_euler[2] = math.radians(rot_map.get(facing_direction.upper(), 0.0))
    obj.location = (x, y, z)
    return obj


# -----------------------------------------------------------------------------
# BUILD STEPS
# -----------------------------------------------------------------------------

def build_reference_grid(coll, materials):
    mat = materials["MAT_Debug_Grid"]
    span = BOUND_OUTER  # grid units
    # Grid lines every 1 grid square within +/- span
    for g in range(-span, span + 1):
        x = g * GRID_SIZE_M
        y_min = -span * GRID_SIZE_M
        y_max =  span * GRID_SIZE_M
        add_debug_line(f"GRID_X_{g:+d}", (x, y_min, 0.0), (x, y_max, 0.0), mat=mat, coll=coll)
    for g in range(-span, span + 1):
        y = g * GRID_SIZE_M
        x_min = -span * GRID_SIZE_M
        x_max =  span * GRID_SIZE_M
        add_debug_line(f"GRID_Y_{g:+d}", (x_min, y, 0.0), (x_max, y, 0.0), mat=mat, coll=coll)

    # Coordinate labels every 2 grid squares along the +X and +Y axes.
    label_step = 2
    for g in range(-span, span + 1, label_step):
        x = g * GRID_SIZE_M
        add_label(
            f"GRID_LBL_X_{g:+d}",
            f"{g:+d}g  ({x:+.2f}m)",
            (x, -span * GRID_SIZE_M - 0.6, 0.0),
            size=0.30, coll=coll,
        )
    for g in range(-span, span + 1, label_step):
        y = g * GRID_SIZE_M
        add_label(
            f"GRID_LBL_Y_{g:+d}",
            f"{g:+d}g  ({y:+.2f}m)",
            (-span * GRID_SIZE_M - 1.4, y, 0.0),
            size=0.30, coll=coll,
        )

    # Scale bar at SE corner.
    sb_x0, sb_y = (-span + 1) * GRID_SIZE_M, (-span - 1.6) * GRID_SIZE_M
    sb_x1 = sb_x0 + 10 * GRID_SIZE_M  # 10 grids = 24.384 m
    add_debug_line("SCALEBAR_10GRID", (sb_x0, sb_y, 0.0), (sb_x1, sb_y, 0.0), mat=mat, coll=coll)
    add_label("SCALEBAR_LBL_1G", "1 grid = 8 ft = 2.4384 m", (sb_x0, sb_y + 0.4, 0.0), size=0.30, coll=coll)
    add_label("SCALEBAR_LBL_10G", "10 grids = 80 ft = 24.384 m", (sb_x0, sb_y - 0.6, 0.0), size=0.30, coll=coll)

    # Origin marker (0,0)
    add_label("ORIGIN_LBL", "ORIGIN (0,0)", (0.2, 0.2, 0.0), size=0.35, coll=coll)


def build_purple_boundaries(coll, materials):
    mat = materials["MAT_Debug_PurpleBoundary"]
    for b in (BOUND_OUTER, BOUND_INNER):
        m = b * GRID_SIZE_M
        # Outer/inner boundaries are square reference lines.
        add_rect_outline(
            f"PURPLE_BOUNDARY_{'OUTER_22' if b == BOUND_OUTER else 'INNER_16'}",
            -m, m, -m, m, 0.0, mat=mat, coll=coll
        )
        add_label(
            f"PURPLE_BOUNDARY_{b}_LBL",
            f"PURPLE +/-{b}g  ({m:.2f} m)",
            (-m + 0.2, m + 0.3, 0.0),
            size=0.35, coll=coll, mat=mat,
        )


def build_height_posts(coll, materials):
    # Place posts in a clear column near the +X / -Y corner of the inner boundary,
    # out of the way of building geometry.
    base_xg = BOUND_INNER + 1   # +17 grid
    base_yg = -(BOUND_INNER + 1)  # -17 grid
    spacing = 1.0  # grid
    posts = [
        ("HPOST_F1_3p09",         H_F1,         "MAT_Debug_Height_F1",            "F1 lobby/ref"),
        ("HPOST_F2SLAB_3p39",     H_F2_SLAB_TOP,"MAT_Debug_Height_F2",            "F2 slab top"),
        ("HPOST_F2TOP_5p99",      H_F2_TOP,     "MAT_Debug_Height_F2",            "F2 ceiling ref"),
        ("HPOST_HIGHBAY_10p31",   H_HIGHBAY,    "MAT_Debug_Height_HighBay",       "HighBay"),
        ("HPOST_ROOFREF_11p91",   H_ROOF_REF,   "MAT_Debug_Height_RoofReference", "Roof REF only"),
    ]
    for i, (name, h, mat_key, lbl) in enumerate(posts):
        add_height_post(name, base_xg + i * spacing, base_yg, h,
                        mat=materials[mat_key], coll=coll, label_text=lbl)


def build_spawn(coll, materials):
    x, y = grid_to_m(SPAWN_X, SPAWN_Y)

    # Red cross floor marker.
    arm = 0.6
    v = [
        (-arm, -0.05, 0.0), (arm, -0.05, 0.0), (arm, 0.05, 0.0), (-arm, 0.05, 0.0),
        (-0.05, -arm, 0.0), (0.05, -arm, 0.0), (0.05, arm, 0.0), (-0.05, arm, 0.0),
    ]
    f = [(0, 1, 2, 3), (4, 5, 6, 7)]
    cross = _new_mesh_obj("Spawn_RedCross_DebugMarker", v, faces=f,
                          coll=coll, mat=materials["MAT_Debug_SpawnRed"])
    cross.location = (x, y, 0.01)

    # Empty as the actual export anchor (zero-rotation, exact spawn).
    anchor = bpy.data.objects.new("Spawn_RedCross_ExportAnchor", None)
    anchor.empty_display_type = 'ARROWS'
    anchor.empty_display_size = 0.6
    anchor.location = (x, y, 0.0)
    # Facing south = -Y; default empty -Y axis points down, so rotate around Z by 180 so its +Y becomes -Y... we just leave rotation 0 and rely on the arrow + text for clarity.
    bpy.context.scene.collection.objects.link(anchor)
    link_to(coll, anchor)

    add_arrow_marker(
        "Spawn_FacingSouth_Arrow", SPAWN_X, SPAWN_Y, "S",
        mat=materials["MAT_Debug_SpawnArrow"], coll=coll,
    )

    add_label(
        "Spawn_LBL",
        f"SPAWN  X={SPAWN_X:.4f}g  Y={SPAWN_Y:.4f}g  facing S",
        (x + 0.2, y + 0.2, 0.05),
        size=0.30, coll=coll,
    )


def _build_zone_list(zone_rows, coll, materials, skip_names=()):
    for (name, x0, x1, y0, y1, z0, z1, mk) in zone_rows:
        if name in skip_names:
            continue
        mn_x, _ = grid_to_m(x0, 0); mx_x, _ = grid_to_m(x1, 0)
        _, mn_y = grid_to_m(0, y0); _, mx_y = grid_to_m(0, y1)
        add_transparent_box_from_bbox(name, mn_x, mx_x, mn_y, mx_y, z0, z1,
                                      mat=materials[mk], coll=coll)
        add_label(name + "_LBL", name,
                  ((mn_x + mx_x) * 0.5, (mn_y + mx_y) * 0.5, z1 + 0.1),
                  size=0.25, coll=coll)


def build_f1_zone_overlays(coll, materials):
    """
    F1 zone overlays driven by the Excel master list (MASTER_F1_ZONES).
    The HighBay zone is also rendered here as the authoritative footprint;
    rotation overlays are produced separately by build_highbay_overlays.
    """
    # ZONE_GRND_RECYC is rendered as a cage in build_grnd_recyc_pallet_stack.
    _build_zone_list(MASTER_F1_ZONES, coll, materials,
                     skip_names={"ZONE_GRND_RECYC"})


def build_highbay_overlays(coll, materials):
    """
    The High-Bay floor footprint and rotation are still VERIFY. Build:
      - VERIFY_HighBay_Unrotated_Overlay: axis-aligned bbox at HighBay height
      - VERIFY_HighBay_Rotated_10deg_Overlay: same bbox, rotated 10deg about its center
      - HighBay angle break debug polyline from the 100/260 deg call-out
    """
    # Bounding bbox from Excel master list ZONE_HIGHBAY.
    hb_xg0, hb_xg1, hb_yg0, hb_yg1 = HIGHBAY_BBOX_GRID
    hb_x0, _ = grid_to_m(hb_xg0, 0); hb_x1, _ = grid_to_m(hb_xg1, 0)
    _, hb_y0 = grid_to_m(0, hb_yg0); _, hb_y1 = grid_to_m(0, hb_yg1)

    unrot = add_transparent_box_from_bbox(
        "VERIFY_HighBay_Unrotated_Overlay",
        hb_x0, hb_x1, hb_y0, hb_y1, 0.0, H_HIGHBAY,
        mat=materials["MAT_Debug_HighBay_Unrotated"], coll=coll
    )
    rot = add_transparent_box_from_bbox(
        "VERIFY_HighBay_Rotated_10deg_Overlay",
        hb_x0, hb_x1, hb_y0, hb_y1, 0.0, H_HIGHBAY,
        mat=materials["MAT_Debug_HighBay_Rotated10"], coll=coll
    )
    # Rotate 10deg about bbox center
    cx = (hb_x0 + hb_x1) * 0.5
    cy = (hb_y0 + hb_y1) * 0.5
    rot.location = (cx, cy, 0.0)
    rot.data.transform(Matrix.Translation((-cx, -cy, 0.0)))
    rot.rotation_euler[2] = math.radians(10.0)

    add_label("HighBay_HEIGHT_LBL", f"HighBay {H_HIGHBAY:.2f} m / 33.81 ft",
              (hb_x1 + 0.4, hb_y0, H_HIGHBAY), size=0.35, coll=coll)

    # Angle-break debug polyline (100/260 deg note).
    pts_m = [(grid_to_m(xg, yg)[0], grid_to_m(xg, yg)[1], 0.02)
             for (xg, yg) in HIGHBAY_ANGLE_LINE_PTS]
    edges = [(i, i + 1) for i in range(len(pts_m) - 1)]
    _new_mesh_obj(
        "VERIFY_HighBay_AngleBreak_DebugLine",
        pts_m, edges=edges, coll=coll,
        mat=materials["MAT_Debug_HighBay_Rotated10"],
    )
    mid = pts_m[1]
    add_label(
        "VERIFY_HighBay_AngleBreak_LBL",
        "HB angle: ~100 deg N / ~260 deg S  (VERIFY)",
        (mid[0] + 0.2, mid[1] - 0.4, 0.05),
        size=0.30, coll=coll,
    )


def build_f2_slab_and_polygon(coll_slab, coll_door, materials):
    """
    F2 slab as a thin transparent bbox plate (verified extents are deferred to
    the Excel list; here we use a generous bbox covering the second-floor band).
    F2 overlook is built strictly from the 4 verified corner points - never as
    a bbox rectangle.
    """
    # F2 slab bbox: union of F2 zones from the master list (excluding the void).
    f2_xg0, f2_xg1, f2_yg0, f2_yg1 = -14.3, 3.2, -7.3, 10.5
    fx0, _ = grid_to_m(f2_xg0, 0); fx1, _ = grid_to_m(f2_xg1, 0)
    _, fy0 = grid_to_m(0, f2_yg0); _, fy1 = grid_to_m(0, f2_yg1)
    add_transparent_box_from_bbox(
        "F2_SLAB_REFERENCE_ONLY_NOT_FINAL_GEOMETRY",
        fx0, fx1, fy0, fy1, H_F2_SLAB_BASE, H_F2_SLAB_TOP,
        mat=materials["MAT_Debug_VERIFY_Transparent"], coll=coll_slab,
    )
    add_label(
        "F2_SLAB_REFERENCE_ONLY_NOT_FINAL_GEOMETRY_LBL",
        f"F2_SLAB_REFERENCE_ONLY_NOT_FINAL_GEOMETRY  "
        f"base {H_F2_SLAB_BASE:.2f} m / top {H_F2_SLAB_TOP:.2f} m  (thk {H_F2_SLAB_THICK:.2f} m)",
        (fx0 + 0.2, fy0 - 0.6, H_F2_SLAB_TOP + 0.05),
        size=0.30, coll=coll_slab,
    )

    # F2 overlook polygon - verified 4 points.
    add_polygon_plane_or_outline(
        "ZONE_F2_OVERLOOK_POLYGON_VERIFIED",
        F2_OVERLOOK_POLYGON,
        H_F2_SLAB_TOP,
        mat=materials["MAT_Debug_HighBay_Unrotated"],
        coll=coll_slab,
        outline_too=True,
    )
    # F2 zones from master list. ZONE_PALLET is rendered as a stacked cage in
    # build_grnd_recyc_pallet_stack. ZONE_HIGHBAY_VOID is also rendered in cutouts.
    _build_zone_list(MASTER_F2_ZONES, coll_slab, materials,
                     skip_names={"ZONE_PALLET", "ZONE_HIGHBAY_VOID"})

    # Glass perimeter wall along the same 4-corner polygon.
    # Excel ELEM_F2_GLASS_PERIMETER_WALL: Z 3.09 -> 4.19 (height 1.10 m, guard).
    glass_h = 4.19 - H_F2_SLAB_BASE   # 1.10 m
    pts_m = [grid_to_m(xg, yg) for (xg, yg) in F2_OVERLOOK_POLYGON]
    n = len(pts_m)
    glass_verts = []
    glass_faces = []
    for i, (x, y) in enumerate(pts_m):
        glass_verts.append((x, y, H_F2_SLAB_TOP))
        glass_verts.append((x, y, H_F2_SLAB_TOP + glass_h))
    for i in range(n):
        a = i * 2
        b = (i * 2 + 2) % (n * 2)
        glass_faces.append((a, b, b + 1, a + 1))
    glass_obj = _new_mesh_obj(
        "ELEM_F2_GLASS_PERIMETER_WALL",
        glass_verts, faces=glass_faces,
        coll=coll_slab, mat=materials["MAT_Glass_ClearArchitectural"],
    )

    # SW corner short non-working door marker.
    sw_xg, sw_yg = F2_OVERLOOK_POLYGON[2]   # SW
    add_door_marker(
        "ELEM_SHORT_DOOR_F2_SW",
        sw_xg, sw_yg, "CLOSED_NONWORKING",
        mat=materials["MAT_Door_ClosedNonWorking"],
        coll=coll_door,
        width_m=0.9, depth_m=0.10, height_m=1.6,
    )
    swx, swy = grid_to_m(sw_xg, sw_yg)
    add_label(
        "ELEM_SHORT_DOOR_F2_SW_LBL",
        "F2 SW short non-working door",
        (swx, swy, H_F2_SLAB_TOP + 1.7),
        size=0.25, coll=coll_door,
    )


def build_cutouts_and_voids(coll, materials):
    """
    Phase 0/1 cutouts are MARKER zones; we do not boolean them out of the slab.
    Naming reflects the eventual cut, but they are visually transparent for now.
    """
    # CUTOUT_F2_HIGHBAY_VOID - extents from Excel ZONE_HIGHBAY_VOID.
    hb_x0, _ = grid_to_m(-4.7, 0); hb_x1, _ = grid_to_m(3.2, 0)
    _, hb_y0 = grid_to_m(0, -0.5); _, hb_y1 = grid_to_m(0, 10.5)
    add_transparent_box_from_bbox(
        "CUTOUT_F2_HIGHBAY_VOID",
        hb_x0, hb_x1, hb_y0, hb_y1,
        H_F2_SLAB_BASE, H_F2_SLAB_TOP,
        mat=materials["MAT_Debug_VERIFY_Transparent"], coll=coll,
    )

    # CUTOUT_F2_STAIR_OPENING - SLAB CUTOUT MARKER at the stair opening footprint.
    # Z spans only the F2 slab thickness (3.09 -> 3.39 m). The full-height
    # ZONE_STAIR_OPENING_IMPORT_ONLY (0 -> 3.39 m) lives in 10_IMPORT_ZONES.
    sx0, _ = grid_to_m(STAIR_X_MIN, 0); sx1, _ = grid_to_m(STAIR_X_MAX, 0)
    _, sy0 = grid_to_m(0, STAIR_Y_MIN); _, sy1 = grid_to_m(0, STAIR_Y_MAX)
    add_transparent_box_from_bbox(
        "CUTOUT_F2_STAIR_OPENING",
        sx0, sx1, sy0, sy1, H_F2_SLAB_BASE, H_F2_SLAB_TOP,
        mat=materials["MAT_Debug_VERIFY_Transparent"], coll=coll,
    )
    add_label(
        "CUTOUT_F2_STAIR_OPENING_LBL",
        f"Stair slab cutout {H_F2_SLAB_BASE:.2f} -> {H_F2_SLAB_TOP:.2f} m",
        ((sx0 + sx1) * 0.5, (sy0 + sy1) * 0.5, H_F2_SLAB_TOP + 0.1),
        size=0.25, coll=coll,
    )
    # Precise stair-opening hole (smaller, inside the broader zone).
    hx0, _ = grid_to_m(STAIR_HOLE_X_MIN, 0); hx1, _ = grid_to_m(STAIR_HOLE_X_MAX, 0)
    _, hy0 = grid_to_m(0, STAIR_HOLE_Y_MIN); _, hy1 = grid_to_m(0, STAIR_HOLE_Y_MAX)
    add_rect_outline(
        "CUTOUT_F2_STAIR_OPENING_PRECISE_HOLE",
        hx0, hx1, hy0, hy1, H_F2_SLAB_TOP + 0.005,
        mat=materials["MAT_Debug_HighBay_Rotated10"], coll=coll,
    )

    # CUTOUT_F2_LOBBY_OPEN_TO_BELOW_VERIFY (to-be-confirmed open-to-below over lobby)
    lx0, _ = grid_to_m(-12, 0); lx1, _ = grid_to_m(-7, 0)
    _, ly0 = grid_to_m(0, -3); _, ly1 = grid_to_m(0, 1)
    add_transparent_box_from_bbox(
        "CUTOUT_F2_LOBBY_OPEN_TO_BELOW_VERIFY",
        lx0, lx1, ly0, ly1, H_F2_SLAB_BASE, H_F2_SLAB_TOP,
        mat=materials["MAT_Debug_VERIFY_Transparent"], coll=coll,
    )


def build_stair_import_zone(coll, materials):
    sx0, _ = grid_to_m(STAIR_X_MIN, 0); sx1, _ = grid_to_m(STAIR_X_MAX, 0)
    _, sy0 = grid_to_m(0, STAIR_Y_MIN); _, sy1 = grid_to_m(0, STAIR_Y_MAX)
    add_transparent_box_from_bbox(
        "ZONE_STAIR_OPENING_IMPORT_ONLY",
        sx0, sx1, sy0, sy1, STAIR_Z_BASE, STAIR_Z_TOP,
        mat=materials["MAT_Debug_VERIFY_Transparent"], coll=coll,
    )
    add_label(
        "ZONE_STAIR_OPENING_IMPORT_ONLY_LBL",
        "STAIR OPENING - IMPORT ONLY (no stair geometry)",
        ((sx0 + sx1) * 0.5, (sy0 + sy1) * 0.5, STAIR_Z_TOP + 0.4),
        size=0.30, coll=coll,
    )



def build_grnd_recyc_pallet_stack(coll, materials):
    """
    GRND/RECYC at floor up to F1, capped by 3-inch steel plate, then Pallet
    Storage stacked above the plate up to F2 ceiling reference.
    Plate top is FLUSH with F2 reference plane (Z = 3.09 m). Do NOT introduce
    a 3-inch step.
    XY footprint locked to Excel master list (X -1.0..+2.2, Y -7.3..-5.5).
    """
    # bbox from Excel master list ZONE_GRND_RECYC / ZONE_PALLET / ELEM_GRND_RECYC_CAGE.
    gx0, gx1 = -1.0, 2.2
    gy0, gy1 = -7.3, -5.5
    mx0, _ = grid_to_m(gx0, 0); mx1, _ = grid_to_m(gx1, 0)
    _, my0 = grid_to_m(0, gy0); _, my1 = grid_to_m(0, gy1)

    # GRND/RECYC zone (open cage volume)
    add_transparent_box_from_bbox(
        "ZONE_GRND_RECYC", mx0, mx1, my0, my1, 0.0, H_F1,
        mat=materials["MAT_Cage_WireMetal"], coll=coll,
    )
    # Outline cage (just the silhouette)
    add_rect_outline(
        "ELEM_GRND_RECYC_CAGE", mx0, mx1, my0, my1, 0.0,
        mat=materials["MAT_Guard_BlackPaintedMetal"], coll=coll,
    )

    # Steel plate: 3.0138 -> 3.09 m, top FLUSH at 3.09 m
    add_transparent_box_from_bbox(
        "ELEM_PALLET_FLOOR_PLATE",
        mx0, mx1, my0, my1, H_PLATE_BOTTOM, H_PLATE_TOP,
        mat=materials["MAT_Plate_Steel"], coll=coll,
    )

    # Pallet Storage above plate up to F2 top ref
    add_transparent_box_from_bbox(
        "ZONE_PALLET_STORAGE",
        mx0, mx1, my0, my1, H_PLATE_TOP, H_F2_TOP,
        mat=materials["MAT_Cage_WireMetal"], coll=coll,
    )

    add_label(
        "STACK_GRND_RECYC_LBL",
        "GRND/RECYC -> 3in plate (flush 3.09 m) -> Pallet Storage",
        ((mx0 + mx1) * 0.5, my1 + 0.6, H_F1 + 0.1),
        size=0.28, coll=coll,
    )


def build_mezz_gate(coll, materials):
    """
    Mezz Storage open loading side - hinged metal safety gate marker.

    *** VERIFY ***
    Exact coordinates are NOT confirmed and must be verified before Phase 5.
    Width and height are taken from the user spec (W = 11.34 m / 37.21 ft,
    H = 0.9144 m / 3 ft). The Mezz bbox here is the Excel ZONE_MEZZ extents,
    but the gate width exceeds those extents - do NOT shrink the gate to
    force it into the older bbox. The placement on the east edge is a
    diagnostic anchor, not a confirmed location.
    """
    # Mezz bbox from Excel ZONE_MEZZ.
    mzx0, mzx1 = -7.1, -5.1
    mzy0, mzy1 = -5.6, -3.4
    mx0, _ = grid_to_m(mzx0, 0); mx1, _ = grid_to_m(mzx1, 0)
    _, my0 = grid_to_m(0, mzy0); _, my1 = grid_to_m(0, mzy1)

    # Gate runs along the open NE-SE side (east edge of Mezz, +X face).
    # User-specified gate W = 11.34 m exceeds the bbox; do NOT shrink to fit.
    # Anchor the gate centered on the east edge midpoint.
    cy_mid = (my0 + my1) * 0.5
    gx = mx1 + 0.05
    half_w = MEZZ_GATE_WIDTH_M * 0.5
    gy_a = cy_mid - half_w
    gy_b = cy_mid + half_w
    h = MEZZ_GATE_HEIGHT_M

    # Build gate aligned along Y (east face, perpendicular to X).
    v = [
        (gx - 0.04, gy_a, H_F2_SLAB_BASE), (gx + 0.04, gy_a, H_F2_SLAB_BASE),
        (gx + 0.04, gy_b, H_F2_SLAB_BASE), (gx - 0.04, gy_b, H_F2_SLAB_BASE),
        (gx - 0.04, gy_a, H_F2_SLAB_BASE + h), (gx + 0.04, gy_a, H_F2_SLAB_BASE + h),
        (gx + 0.04, gy_b, H_F2_SLAB_BASE + h), (gx - 0.04, gy_b, H_F2_SLAB_BASE + h),
    ]
    f = [
        (0, 1, 2, 3), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5),
        (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    _new_mesh_obj(
        "ELEM_MEZZ_LOADING_GATE_VERIFY",
        v, faces=f, coll=coll, mat=materials["MAT_Gate_MetalSafety"],
    )
    add_label(
        "ELEM_MEZZ_LOADING_GATE_VERIFY_LBL",
        f"MEZZ GATE  W={MEZZ_GATE_WIDTH_M:.2f} m (37.21 ft)  "
        f"H={MEZZ_GATE_HEIGHT_M:.4f} m (3 ft)  VERIFY (W exceeds Mezz bbox)",
        (gx + 0.2, cy_mid, H_F2_SLAB_BASE + h + 0.15),
        size=0.28, coll=coll,
    )


def _detect_pair_partners(doors, threshold_grid=1.2):
    """
    Tag potential double-door pairs: any two same-floor doors of compatible
    function within `threshold_grid` of each other.
    Returns dict[id] -> partner_id (only for doors that have a partner).
    """
    partners = {}
    for i, (id_a, xa, ya, fn_a, fl_a) in enumerate(doors):
        if id_a in partners:
            continue
        for (id_b, xb, yb, fn_b, fl_b) in doors[i + 1:]:
            if id_b in partners or fl_a != fl_b or fn_a != fn_b:
                continue
            if math.hypot(xa - xb, ya - yb) <= threshold_grid:
                partners[id_a] = id_b
                partners[id_b] = id_a
                break
    return partners


def build_door_window_glass_markers(coll, materials):
    """
    Door / overhead-door / window / glass markers driven by the Excel master list.

    SVG color map:
      magenta = closed/non-working door
      yellow  = working door
      cyan    = glass curtain wall
      Trumatch 34-b = window
      Trumatch 31-d = glass wall

    All doors treated as glass doors unless revised later (per user spec).
    Adjacent same-floor doors of compatible function are flagged as likely
    double-door pairs in their object name suffix (_PAIRA/_PAIRB).
    """
    pair_map = _detect_pair_partners(MASTER_DOORS, threshold_grid=1.2)
    pair_label_assigned = {}

    for (door_id, xg, yg, fn, fl) in MASTER_DOORS:
        if fn == "WORKING":
            mat_key = "MAT_Door_Working"
            h = DOOR_HEIGHT_MAN_M
            w = DOOR_WIDTH_MAN_M
        elif fn == "OVERHEAD_CLOSED":
            mat_key = "MAT_Door_ClosedNonWorking"
            h = DOOR_HEIGHT_OVERHEAD_M
            w = OVERHEAD_DOOR_W_M
        else:  # CLOSED_NONWORKING
            mat_key = "MAT_Door_ClosedNonWorking"
            h = DOOR_HEIGHT_MAN_M
            w = DOOR_WIDTH_MAN_M

        suffix = ""
        if door_id in pair_map:
            partner = pair_map[door_id]
            if door_id < partner:
                suffix = "_PAIRA"; pair_label_assigned[door_id] = "A"
            else:
                suffix = "_PAIRB"; pair_label_assigned[door_id] = "B"

        name = door_id + suffix
        obj = add_door_marker(
            name, xg, yg, fn,
            mat=materials[mat_key], coll=coll,
            width_m=w, depth_m=0.10, height_m=h, rotation_z_deg=0.0,
        )
        # Lift F2 doors onto the slab.
        if fl == "F2":
            obj.location.z = H_F2_SLAB_BASE

        x, y = grid_to_m(xg, yg)
        z_lbl = (H_F2_SLAB_BASE if fl == "F2" else 0.0) + h + 0.1
        tag = "  [DOUBLE-DOOR PAIR]" if door_id in pair_map else ""
        add_label(
            name + "_LBL", f"{door_id}{suffix}{tag}",
            (x, y + 0.2, z_lbl), size=0.22, coll=coll,
        )


def build_additional_elements(coll, materials):
    """
    Additional elements from the Excel master list section
    '05 New Standard Blockout Elements':
      - ELEM_RAIL_HB_OVERLOOK
      - ELEM_STAIR_OPENING_GUARD_VERIFY
      - ELEM_OPEN_TO_BELOW_EDGE
      - ELEM_ENTRY_GLASS_PROXY
      - ELEM_OVERHEAD_VERIFY  (wide overhead-verify panel band)
    """
    # ELEM_RAIL_HB_OVERLOOK: -4.7..-4.2, -1.3..1.1, Z 3.09 -> 4.19 (h 1.10)
    rx0, _ = grid_to_m(-4.7, 0); rx1, _ = grid_to_m(-4.2, 0)
    _, ry0 = grid_to_m(0, -1.3); _, ry1 = grid_to_m(0, 1.1)
    add_transparent_box_from_bbox(
        "ELEM_RAIL_HB_OVERLOOK",
        rx0, rx1, ry0, ry1, H_F2_SLAB_BASE, 4.19,
        mat=materials["MAT_Glass_ClearArchitectural"], coll=coll,
    )

    # ELEM_STAIR_OPENING_GUARD_VERIFY: -9..-7, -0.5..1, Z 3.09 -> 4.19 VERIFY
    sx0, _ = grid_to_m(-9, 0); sx1, _ = grid_to_m(-7, 0)
    _, sy0 = grid_to_m(0, -0.5); _, sy1 = grid_to_m(0, 1)
    add_transparent_box_from_bbox(
        "ELEM_STAIR_OPENING_GUARD_VERIFY",
        sx0, sx1, sy0, sy1, H_F2_SLAB_BASE, 4.19,
        mat=materials["MAT_Guard_BlackPaintedMetal"], coll=coll,
    )

    # ELEM_OPEN_TO_BELOW_EDGE: -4.7..3.2, -0.5..10.5, Z 3.09 -> 3.14 (5 cm strip)
    ex0, _ = grid_to_m(-4.7, 0); ex1, _ = grid_to_m(3.2, 0)
    _, ey0 = grid_to_m(0, -0.5); _, ey1 = grid_to_m(0, 10.5)
    add_rect_outline(
        "ELEM_OPEN_TO_BELOW_EDGE",
        ex0, ex1, ey0, ey1, 3.14,
        mat=materials["MAT_Debug_VERIFY_Transparent"], coll=coll,
    )

    # ELEM_ENTRY_GLASS_PROXY: center -11, -2.5, height 2.4 m (working entry).
    add_door_marker(
        "ELEM_ENTRY_GLASS_PROXY",
        -11.0, -2.5, "WORKING",
        mat=materials["MAT_Glass_ClearArchitectural"], coll=coll,
        width_m=2.0, depth_m=0.05, height_m=2.4, rotation_z_deg=0.0,
    )
    ex, ey = grid_to_m(-11.0, -2.5)
    add_label(
        "ELEM_ENTRY_GLASS_PROXY_LBL", "ENTRY GLASS PROXY (working)",
        (ex, ey + 0.3, 2.5), size=0.25, coll=coll,
    )

    # ELEM_OVERHEAD_VERIFY: wide overhead band -6.5..-2.5, -7.8..-6.3, Z 0..3.05
    ox0, _ = grid_to_m(-6.5, 0); ox1, _ = grid_to_m(-2.5, 0)
    _, oy0 = grid_to_m(0, -7.8); _, oy1 = grid_to_m(0, -6.3)
    add_transparent_box_from_bbox(
        "ELEM_OVERHEAD_VERIFY",
        ox0, ox1, oy0, oy1, 0.0, DOOR_HEIGHT_OVERHEAD_M,
        mat=materials["MAT_Door_ClosedNonWorking"], coll=coll,
    )
    add_label(
        "ELEM_OVERHEAD_VERIFY_LBL",
        f"OVERHEAD VERIFY band  H={DOOR_HEIGHT_OVERHEAD_M:.2f} m  (closed)",
        ((ox0 + ox1) * 0.5, oy0 - 0.4, DOOR_HEIGHT_OVERHEAD_M + 0.15),
        size=0.28, coll=coll,
    )


# -----------------------------------------------------------------------------
# CAMERAS
# -----------------------------------------------------------------------------

def add_camera(name, location, rotation_euler, lens=35, ortho=False, ortho_scale=60, coll=None):
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = lens
    if ortho:
        cam_data.type = 'ORTHO'
        cam_data.ortho_scale = ortho_scale
    cam = bpy.data.objects.new(name, cam_data)
    cam.location = location
    cam.rotation_euler = rotation_euler
    bpy.context.scene.collection.objects.link(cam)
    if coll is not None:
        link_to(coll, cam)
    return cam


def build_review_cameras(coll):
    # Top-down ortho
    add_camera(
        "CAM_TopDown_Ortho",
        location=(0.0, 0.0, 80.0),
        rotation_euler=(0.0, 0.0, 0.0),
        ortho=True, ortho_scale=BOUND_OUTER * GRID_SIZE_M * 2.2,
        coll=coll,
    )
    # Spawn perspective
    sx, sy = grid_to_m(SPAWN_X, SPAWN_Y)
    add_camera(
        "CAM_SpawnPerspective",
        location=(sx, sy + 0.2, 1.7),
        rotation_euler=(math.radians(82), 0.0, math.radians(180)),  # facing south
        lens=28, coll=coll,
    )
    # High-bay
    add_camera(
        "CAM_HighBay_Perspective",
        location=(grid_to_m(-2, -14)[0], grid_to_m(-2, -14)[1], 5.0),
        rotation_euler=(math.radians(70), 0.0, 0.0),
        lens=24, coll=coll,
    )
    # F2 overlook
    f2_cx = sum(grid_to_m(xg, yg)[0] for (xg, yg) in F2_OVERLOOK_POLYGON) / 4.0
    f2_cy = sum(grid_to_m(xg, yg)[1] for (xg, yg) in F2_OVERLOOK_POLYGON) / 4.0
    add_camera(
        "CAM_F2_Overlook",
        location=(f2_cx + 6.0, f2_cy - 6.0, H_F2_SLAB_TOP + 1.7),
        rotation_euler=(math.radians(78), 0.0, math.radians(45)),
        lens=28, coll=coll,
    )


# -----------------------------------------------------------------------------
# EXPORT / VALIDATION
# -----------------------------------------------------------------------------

def save_outputs():
    bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)
    bpy.ops.export_scene.fbx(
        filepath=OUT_FBX,
        use_selection=False,
        global_scale=1.0,
        apply_unit_scale=True,
        apply_scale_options='FBX_SCALE_NONE',
        bake_space_transform=False,
        object_types={'MESH', 'EMPTY', 'CAMERA', 'OTHER'},
        mesh_smooth_type='OFF',
        use_mesh_modifiers=True,
        path_mode='AUTO',
        axis_forward='-Z',
        axis_up='Y',
    )


def print_validation_report():
    f1_doors = sum(1 for d in MASTER_DOORS if d[4] == "F1" and d[3] != "OVERHEAD_CLOSED")
    f2_doors = sum(1 for d in MASTER_DOORS if d[4] == "F2")
    oh_doors = sum(1 for d in MASTER_DOORS if d[3] == "OVERHEAD_CLOSED")
    working_doors = sum(1 for d in MASTER_DOORS if d[3] == "WORKING")
    lines = [
        "=" * 72,
        "NIMA Phase 0/1 Reference Blockout - VALIDATION REPORT",
        "Source: NIMA_Phase2_Master_Coordinate_Geometry_Confidence_List_Clean.xlsx",
        "=" * 72,
        f"Grid scale:                1 grid = {GRID_SIZE_M:.4f} m (8 ft)",
        f"Spawn coordinate:          X = {SPAWN_X:.13f} g  Y = {SPAWN_Y:.7f} g  facing S",
        f"Spawn coordinate (m):      X = {SPAWN_X * GRID_SIZE_M:+.4f} m  "
        f"Y = {SPAWN_Y * GRID_SIZE_M:+.4f} m",
        "Elevator:                  NONE (no elevator object, void, material, or label)",
        "Stair mesh:                NONE (no treads, risers, rails, or landings)",
        "Reception:                 NONE (no reception zone, marker, label, or geometry)",
        "Final walls / doors / stairs / reception / elevator / exterior /",
        "  forklift / crane:        NONE (intentionally not generated in Phase 0/1)",
        "-" * 72,
        f"ZONE_HIGHBAY:              X [-4.7, +3.2] g  Y [-6.6, +10.5] g  Z [0, {H_HIGHBAY:.2f}] m",
        f"CUTOUT_F2_HIGHBAY_VOID:    X [-4.7, +3.2] g  Y [-0.5, +10.5] g  "
        f"Z [{H_F2_SLAB_BASE:.2f}, {H_F2_SLAB_TOP:.2f}] m  (slab cutout marker, not full-height solid)",
        f"ZONE_GRND_RECYC:           X [-1.0, +2.2] g  Y [-7.3, -5.5] g  Z [0, {H_F1:.2f}] m",
        f"ZONE_PALLET_STORAGE:       X [-1.0, +2.2] g  Y [-7.3, -5.5] g  "
        f"Z [{H_PLATE_TOP:.2f}, {H_F2_TOP:.2f}] m",
        f"ELEM_PALLET_FLOOR_PLATE:   X [-1.0, +2.2] g  Y [-7.3, -5.5] g  "
        f"Z [{H_PLATE_BOTTOM:.4f}, {H_PLATE_TOP:.2f}] m  (plate top flush at F2 ref, no 3-inch step)",
        "F2 overlook shape:         polygon from 4 verified corners only "
        "(NOT bbox rectangle)",
        "ELEM_F2_GLASS_PERIMETER_WALL: follows the same 4 verified corners",
        f"F2 slab reference:         base Z = {H_F2_SLAB_BASE:.2f} m, top Z = {H_F2_SLAB_TOP:.2f} m, "
        f"thk {H_F2_SLAB_THICK:.2f} m  (label: F2_SLAB_REFERENCE_ONLY_NOT_FINAL_GEOMETRY)",
        f"ZONE_STAIR_OPENING_IMPORT_ONLY: X [{STAIR_X_MIN}, {STAIR_X_MAX}] g  "
        f"Y [{STAIR_Y_MIN}, {STAIR_Y_MAX}] g  Z [{STAIR_Z_BASE:.2f}, {STAIR_Z_TOP:.2f}] m",
        f"CUTOUT_F2_STAIR_OPENING:   X [{STAIR_X_MIN}, {STAIR_X_MAX}] g  "
        f"Y [{STAIR_Y_MIN}, {STAIR_Y_MAX}] g  Z [{H_F2_SLAB_BASE:.2f}, {H_F2_SLAB_TOP:.2f}] m",
        f"High-bay height:           {H_HIGHBAY:.2f} m (33.81 ft)",
        f"Roof reference:            {H_ROOF_REF:.2f} m (39.08 ft) REFERENCE ONLY, not occupied",
        f"Overhead doors:            placeholder/VERIFY width 1.5 grid = "
        f"{OVERHEAD_DOOR_W_M:.4f} m (12 ft)",
        f"ELEM_MEZZ_LOADING_GATE_VERIFY: W={MEZZ_GATE_WIDTH_M:.2f} m  "
        f"H={MEZZ_GATE_HEIGHT_M:.4f} m  VERIFY (exact coordinates NOT confirmed)",
        "High-bay rotation:         VERIFY (unrotated + 10 deg overlays present)",
        f"Doors generated:           F1 man-doors={f1_doors}  F2 doors={f2_doors}  "
        f"overhead={oh_doors}  working={working_doors}  total={len(MASTER_DOORS)}",
        "Door positions:            sourced from Excel master list (Section 04)",
        "Pair detection:            adjacent same-floor same-function doors "
        "flagged _PAIRA/_PAIRB",
        "ELEM_STAIR_OPENING_GUARD_VERIFY: present (renamed from ELEM_RAIL_STAIR_VOID_VERIFY)",
        "Guard material:            MAT_Guard_BlackPaintedMetal "
        "(no MAT_Handrail_BlackPaintedMetal references)",
        "=" * 72,
        "F2 OVERLOOK POLYGON (verified, grid units):",
    ]
    labels = ["NE", "NW", "SW", "SE"]
    for lbl, (xg, yg) in zip(labels, F2_OVERLOOK_POLYGON):
        x, y = grid_to_m(xg, yg)
        lines.append(f"  {lbl}: X = {xg:+.7f} g ({x:+.4f} m)   Y = {yg:+.7f} g ({y:+.4f} m)")
    lines.append("=" * 72)
    print("\n" + "\n".join(lines) + "\n")


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():
    reset_scene()

    colls = {name: add_collection(name) for name in COLLECTIONS}
    materials = build_materials()

    build_reference_grid(           colls["00_REFERENCE_GRID"],        materials)
    build_purple_boundaries(        colls["01_DEBUG_BOUNDARIES"],      materials)
    build_height_posts(             colls["02_HEIGHT_POSTS"],          materials)
    build_spawn(                    colls["03_SPAWN"],                 materials)
    build_f1_zone_overlays(         colls["04_F1_ZONE_OVERLAYS"],      materials)
    build_highbay_overlays(         colls["05_HIGHBAY_ROTATION_OVERLAYS"], materials)
    build_f2_slab_and_polygon(
        colls["06_F2_SLAB_AND_POLYGON_OVERLAYS"],
        colls["08_DOOR_WINDOW_GLASS_MARKERS"],
        materials,
    )
    build_cutouts_and_voids(        colls["07_CUTOUT_AND_VOID_MARKERS"], materials)
    build_door_window_glass_markers(colls["08_DOOR_WINDOW_GLASS_MARKERS"], materials)
    build_grnd_recyc_pallet_stack(  colls["09_STACKING_AND_CAGE_MARKERS"], materials)
    build_mezz_gate(                colls["09_STACKING_AND_CAGE_MARKERS"], materials)
    build_stair_import_zone(        colls["10_IMPORT_ZONES"],          materials)
    build_additional_elements(      colls["08_DOOR_WINDOW_GLASS_MARKERS"], materials)
    build_review_cameras(           colls["11_REVIEW_CAMERAS"])

    save_outputs()
    print_validation_report()


if __name__ == "__main__":
    main()
