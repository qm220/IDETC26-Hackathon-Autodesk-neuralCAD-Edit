def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    imported_shape = imported.val()
    solids = imported_shape.Solids()
    if not solids:
        raise ValueError("The input STEP file contains no solids")
    solid = solids[0]

    # Find one of the broad annular planar faces. Such a face has an outer
    # boundary and an aperture boundary, and therefore at least two wires.
    annular_faces = [
        face for face in solid.Faces()
        if face.geomType() == "PLANE" and len(face.Wires()) >= 2
    ]
    if not annular_faces:
        raise ValueError("Could not identify a planar annular frame face")
    reference_face = max(annular_faces, key=lambda face: face.Area())

    normal = reference_face.normalAt().normalized()

    # The longest straight edge on the annular face defines the frame width.
    straight_edges = [
        edge for edge in reference_face.Edges()
        if edge.geomType() == "LINE"
    ]
    if not straight_edges:
        raise ValueError("Could not identify the frame's straight width direction")
    width_edge = max(straight_edges, key=lambda edge: edge.Length())
    width_dir = width_edge.tangentAt().normalized()

    # Remove any negligible component along the face normal.
    width_dir = (width_dir - normal.multiply(width_dir.dot(normal))).normalized()
    height_dir = normal.cross(width_dir).normalized()

    # Rigidly map the frame into local coordinates: X=width, Y=height,
    # Z=through-thickness. This preserves all analytic surfaces and radii.
    world_to_local = cq.Matrix([
        [width_dir.x,  width_dir.y,  width_dir.z,  0.0],
        [height_dir.x, height_dir.y, height_dir.z, 0.0],
        [normal.x,     normal.y,     normal.z,     0.0],
        [0.0,          0.0,          0.0,          1.0]
    ])
    local_solid = solid.transformShape(world_to_local)
    bb = local_solid.BoundingBox()
    center_y = 0.5 * (bb.ymin + bb.ymax)

    increase = 5.0
    half_increase = increase / 2.0
    margin = max(bb.xlen, bb.ylen, bb.zlen) + 20.0

    x0 = bb.xmin - margin
    z0 = bb.zmin - margin
    box_dx = bb.xlen + 2.0 * margin
    box_dz = bb.zlen + 2.0 * margin

    # Separate the model through its central straight side spans. Moving the
    # two halves apart retains all original corners, blends, lands, and wall
    # profiles without scaling them.
    lower_box = cq.Solid.makeBox(
        box_dx,
        (center_y - bb.ymin) + margin,
        box_dz,
        cq.Vector(x0, bb.ymin - margin, z0)
    )
    upper_box = cq.Solid.makeBox(
        box_dx,
        (bb.ymax - center_y) + margin,
        box_dz,
        cq.Vector(x0, center_y, z0)
    )

    lower = local_solid.intersect(lower_box).translate((0.0, -half_increase, 0.0))
    upper = local_solid.intersect(upper_box).translate((0.0, half_increase, 0.0))

    # The profile is constant through the central portion of each straight
    # side. Reuse a 5 mm-wide central piece of the original model as the exact
    # profile-preserving extension. A tiny overlap makes the final fuse robust.
    overlap = 0.01
    bridge_y0 = center_y - half_increase - overlap
    bridge_dy = increase + 2.0 * overlap
    bridge_box = cq.Solid.makeBox(
        box_dx,
        bridge_dy,
        box_dz,
        cq.Vector(x0, bridge_y0, z0)
    )
    bridge = local_solid.intersect(bridge_box)

    stretched_local = lower.fuse(bridge).fuse(upper).clean()

    # Transform back to the original model orientation.
    local_to_world = cq.Matrix([
        [width_dir.x, height_dir.x, normal.x, 0.0],
        [width_dir.y, height_dir.y, normal.y, 0.0],
        [width_dir.z, height_dir.z, normal.z, 0.0],
        [0.0,         0.0,          0.0,      1.0]
    ])
    result = stretched_local.transformShape(local_to_world).clean()

    result_solids = result.Solids()
    if len(result_solids) != 1:
        raise ValueError(f"Expected one fused solid after stretching, got {len(result_solids)}")
    result = result_solids[0]

    result_local = result.transformShape(world_to_local)
    result_bb = result_local.BoundingBox()
    print(f"Original local height: {bb.ylen:.6f} mm")
    print(f"Modified local height: {result_bb.ylen:.6f} mm")
    print(f"Height increase: {result_bb.ylen - bb.ylen:.6f} mm")
    print(f"Width change: {result_bb.xlen - bb.xlen:.6f} mm")
    print(f"Result valid: {result.isValid()}")

    return cq.Workplane("XY").newObject([result])