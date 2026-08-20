def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    solids = root.Solids()
    if len(solids) != 1:
        raise ValueError("Expected one connected input solid, found %d" % len(solids))
    solid = solids[0]
    faces = solid.Faces()

    print("Input valid:", solid.isValid())
    print("Input solids:", len(solids))
    print("Input faces:", len(faces))
    print("Input volume: %.6f mm^3" % solid.Volume())

    # Inspect and bind the STEP-analysis face indices to the loaded geometry.
    for i, face in enumerate(faces):
        c = face.Center()
        geom_type = face.geomType()
        try:
            n = face.normalAt()
            normal_text = "(%.6f, %.6f, %.6f)" % (n.x, n.y, n.z)
        except Exception:
            normal_text = "n/a"
        print("FACE %d: type=%s center=(%.6f, %.6f, %.6f) normal=%s area=%.6f" %
              (i, geom_type, c.x, c.y, c.z, normal_text, face.Area()))

    if len(faces) <= 34:
        raise ValueError("The loaded STEP does not contain grounded FACE 12 and FACE 34")

    fixed_face = faces[12]
    moving_face = faces[34]
    if fixed_face.geomType() != "PLANE" or moving_face.geomType() != "PLANE":
        raise ValueError("Grounded FACE 12 and FACE 34 must both be planar")

    c_fixed = fixed_face.Center()
    c_moving = moving_face.Center()
    n_fixed = fixed_face.normalAt().normalized()
    n_moving = moving_face.normalAt().normalized()

    # Establish the local thickness direction from fixed FACE 12 toward FACE 34.
    center_delta = c_moving - c_fixed
    signed_separation = center_delta.dot(n_fixed)
    if abs(signed_separation) < 1.0e-7:
        raise ValueError("Could not establish a separation between FACE 12 and FACE 34")
    direction = n_fixed if signed_separation > 0.0 else -n_fixed
    original_separation = center_delta.dot(direction)

    print("Bound FACE 12 as fixed annular datum at (%.6f, %.6f, %.6f)" %
          (c_fixed.x, c_fixed.y, c_fixed.z))
    print("Bound FACE 34 as moving annular side at (%.6f, %.6f, %.6f)" %
          (c_moving.x, c_moving.y, c_moving.z))
    print("Local height direction: (%.9f, %.9f, %.9f)" %
          (direction.x, direction.y, direction.z))
    print("Grounded annular-face separation: %.6f mm" % original_separation)
    print("Opposing-normal dot product: %.9f" % n_fixed.dot(n_moving))

    increase = 5.0
    displacement = direction.multiply(increase)

    # Fuse the original solid with a copy translated toward FACE 34. Because the
    # copies overlap through the existing prismatic middle region, this delays
    # the moving-side edge treatments by exactly 5 mm while retaining FACE 12,
    # the complete in-plane rounded-rectangle profile, and all original fillet
    # radii. This is equivalent to inserting 5 mm into the local extrusion depth.
    shifted = solid.translate((displacement.x, displacement.y, displacement.z))
    result = solid.fuse(shifted)
    try:
        result = result.clean()
    except Exception:
        pass

    result_solids = result.Solids()
    if len(result_solids) != 1:
        raise ValueError("Height extension did not produce one connected solid")
    final_solid = result_solids[0]
    if not final_solid.isValid():
        raise ValueError("Resulting extended frame is invalid")

    # Verify the total extent along the locally derived height direction.
    def projected_vertex_range(shape, axis):
        values = [v.Center().dot(axis) for v in shape.Vertices()]
        return min(values), max(values)

    old_min, old_max = projected_vertex_range(solid, direction)
    new_min, new_max = projected_vertex_range(final_solid, direction)
    old_height = old_max - old_min
    new_height = new_max - new_min

    print("Original local overall height: %.6f mm" % old_height)
    print("Final local overall height: %.6f mm" % new_height)
    print("Measured height increase: %.6f mm" % (new_height - old_height))
    print("Fixed-side displacement: %.6f mm" % (new_min - old_min))
    print("Result valid:", final_solid.isValid())
    print("Result solids:", len(result_solids))
    print("Result volume: %.6f mm^3" % final_solid.Volume())

    if abs((new_height - old_height) - increase) > 1.0e-5:
        raise ValueError("Final local height did not increase by exactly 5 mm")
    if abs(new_min - old_min) > 1.0e-5:
        raise ValueError("FACE 12 side was not retained as the fixed datum")

    return cq.Workplane(obj=final_solid)
