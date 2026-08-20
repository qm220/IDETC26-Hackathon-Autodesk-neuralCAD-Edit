def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()

    # Locate the planar floor of the existing front rounded-end relief pocket.
    # The source B-rep identifies this floor at z = -10 mm. Its outer wire is
    # the exact slot profile that must be preserved.
    candidates = []
    for face in source_shape.Faces():
        try:
            vertices = face.Vertices()
            if not vertices or face.geomType() != "PLANE":
                continue

            z_values = [v.Center().z for v in vertices]
            z_span = max(z_values) - min(z_values)
            center = face.Center()
            area = face.Area()
            edge_count = len(face.outerWire().Edges())

            if z_span < 1.0e-5 and abs(center.z + 10.0) < 0.1:
                candidates.append((face, area, edge_count, center))
                print(
                    "Pocket-floor candidate: "
                    f"center=({center.x:.4f}, {center.y:.4f}, {center.z:.4f}), "
                    f"area={area:.4f}, edges={edge_count}"
                )
        except Exception:
            continue

    if not candidates:
        raise ValueError("Could not locate the existing slot pocket floor at z=-10 mm")

    # A capsule/rounded slot boundary consists of two straight and two curved
    # edges. Prefer that exact topology, then the smaller candidate if needed.
    capsule_candidates = [item for item in candidates if item[2] == 4]
    if capsule_candidates:
        pocket_face = min(capsule_candidates, key=lambda item: item[1])[0]
    else:
        pocket_face = min(candidates, key=lambda item: item[1])[0]

    slot_wire = pocket_face.outerWire()

    # Extrude the preserved profile in both thickness directions. This spans
    # the complete part regardless of which side of the pocket floor contains
    # the remaining central web.
    cutter_front = cq.Solid.extrudeLinear(
        slot_wire, [], cq.Vector(0.0, 0.0, 100.0)
    )
    cutter_rear = cq.Solid.extrudeLinear(
        slot_wire, [], cq.Vector(0.0, 0.0, -100.0)
    )
    cutter = cutter_front.fuse(cutter_rear)

    result_shape = source_shape.cut(cutter)

    if not result_shape.isValid():
        raise ValueError("The through-slot boolean operation produced an invalid shape")

    print(f"Original volume: {source_shape.Volume():.6f} mm^3")
    print(f"Modified volume: {result_shape.Volume():.6f} mm^3")
    print(f"Removed volume: {source_shape.Volume() - result_shape.Volume():.6f} mm^3")
    print(f"Result solids: {len(result_shape.Solids())}")

    return cq.Workplane("XY").newObject([result_shape])