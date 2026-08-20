def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = imported.val().Solids()
    if not solids:
        raise ValueError("The input STEP file contains no solids")
    solid = max(solids, key=lambda s: s.Volume())

    # Identify a broad planar annular face. Its plane defines the frame plane
    # and its straight boundary edges define the in-plane width direction.
    annular_faces = [
        face for face in solid.Faces()
        if face.geomType() == "PLANE" and len(face.Wires()) >= 2
    ]
    if not annular_faces:
        raise ValueError("Could not identify a planar annular frame face")
    reference_face = max(annular_faces, key=lambda f: f.Area())

    normal = reference_face.normalAt().normalized()
    straight_edges = [
        edge for edge in reference_face.Edges()
        if edge.geomType() == "LINE"
    ]
    if not straight_edges:
        raise ValueError("Could not determine the frame width direction")

    # The longest straight boundary segment belongs to the long horizontal
    # portions of this rounded rectangular frame.
    width_dir = max(straight_edges, key=lambda e: e.Length()).tangentAt().normalized()
    width_dir = (
        width_dir - normal.multiply(width_dir.dot(normal))
    ).normalized()
    height_dir = normal.cross(width_dir).normalized()

    reference_center = reference_face.Center()
    bb = solid.BoundingBox()
    diagonal = math.sqrt(bb.xlen ** 2 + bb.ylen ** 2 + bb.zlen ** 2)
    span = 2.0 * diagonal + 30.0

    # Construct a large prism in the intrinsic frame coordinate system without
    # transforming the imported solid. This avoids generalized-transform
    # numerical errors and preserves the original model orientation exactly.
    def make_intrinsic_slab(y_min, y_max):
        if y_max <= y_min:
            raise ValueError("Invalid intrinsic slab interval")
        y_mid = 0.5 * (y_min + y_max)
        origin = (
            reference_center
            + height_dir.multiply(y_mid)
            - normal.multiply(span)
        )
        plane = cq.Plane(origin=origin, xDir=width_dir, normal=normal)
        return (
            cq.Workplane(plane)
            .rect(2.0 * span, y_max - y_min)
            .extrude(2.0 * span)
            .val()
        )

    increase = 5.0
    half_increase = 0.5 * increase

    # Split through the middle of the two straight side members. The rounded
    # corners and horizontal members remain untouched and are translated
    # symmetrically by 2.5 mm.
    lower_cutter = make_intrinsic_slab(-span, 0.0)
    upper_cutter = make_intrinsic_slab(0.0, span)

    lower = solid.intersect(lower_cutter).translate(
        height_dir.multiply(-half_increase)
    )
    upper = solid.intersect(upper_cutter).translate(
        height_dir.multiply(half_increase)
    )

    # Reuse the original invariant side-member geometry across the new 5 mm
    # central interval. The slight overlap ensures a robust Boolean union while
    # retaining the exact original cross-sectional profile.
    overlap = 0.02
    bridge_cutter = make_intrinsic_slab(
        -half_increase - overlap,
        half_increase + overlap
    )
    bridge = solid.intersect(bridge_cutter)

    result = lower.fuse(bridge).fuse(upper).clean()
    result_solids = result.Solids()
    if len(result_solids) != 1:
        raise ValueError(
            f"Expected one continuous solid after height extension, got {len(result_solids)}"
        )
    result = result_solids[0].clean()

    if not result.isValid():
        raise ValueError("The height-extended frame is not a valid solid")

    # Measure extents in the intrinsic frame directions from tessellated points.
    def directional_extents(shape, direction):
        points, _ = shape.tessellate(0.25)
        values = [p.dot(direction) for p in points]
        return min(values), max(values)

    old_y0, old_y1 = directional_extents(solid, height_dir)
    new_y0, new_y1 = directional_extents(result, height_dir)
    old_x0, old_x1 = directional_extents(solid, width_dir)
    new_x0, new_x1 = directional_extents(result, width_dir)
    old_z0, old_z1 = directional_extents(solid, normal)
    new_z0, new_z1 = directional_extents(result, normal)

    print(f"Original intrinsic height: {old_y1 - old_y0:.6f} mm")
    print(f"Modified intrinsic height: {new_y1 - new_y0:.6f} mm")
    print(f"Height increase: {(new_y1 - new_y0) - (old_y1 - old_y0):.6f} mm")
    print(f"Width change: {(new_x1 - new_x0) - (old_x1 - old_x0):.6f} mm")
    print(f"Depth change: {(new_z1 - new_z0) - (old_z1 - old_z0):.6f} mm")
    print(f"Result valid: {result.isValid()}")

    return cq.Workplane("XY").newObject([result])