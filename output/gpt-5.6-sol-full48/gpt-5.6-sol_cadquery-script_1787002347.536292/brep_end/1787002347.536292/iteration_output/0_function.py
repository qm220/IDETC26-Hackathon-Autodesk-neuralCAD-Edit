def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model_wp = cq.importers.importStep(input_file)
    model = model_wp.val()

    bbox = model.BoundingBox()
    print("Original valid:", model.isValid())
    print(f"Original volume: {model.Volume():.6f} mm^3")
    print(f"Bounding box: x=({bbox.xmin:.3f}, {bbox.xmax:.3f}), y=({bbox.ymin:.3f}, {bbox.ymax:.3f}), z=({bbox.zmin:.3f}, {bbox.zmax:.3f})")

    # Locate the planar floor of the front blind guide slot. According to the
    # source geometry, this floor is normal to Z and lies at z=-10 mm.
    candidates = []
    for index, face in enumerate(model.Faces()):
        try:
            if face.geomType() != "PLANE":
                continue
            center = face.Center()
            normal = face.normalAt(center)
            if abs(abs(normal.z) - 1.0) > 1.0e-5:
                continue
            edge_types = [edge.geomType() for edge in face.outerWire().Edges()]
            print(f"Z-plane face {index}: z={center.z:.6f}, area={face.Area():.6f}, edges={edge_types}")
            if abs(center.z + 10.0) < 0.05:
                # An obround slot floor has two straight edges and two circular arcs.
                line_count = sum(1 for kind in edge_types if kind == "LINE")
                circle_count = sum(1 for kind in edge_types if kind == "CIRCLE")
                if line_count == 2 and circle_count == 2:
                    candidates.append(face)
        except Exception as exc:
            print(f"Skipped face {index}: {exc}")

    if not candidates:
        raise ValueError("Could not identify the obround front-slot floor at z=-10 mm")

    # Prefer the compact slot floor if more than one matching face is present.
    slot_floor = min(candidates, key=lambda face: face.Area())
    slot_center = slot_floor.Center()
    slot_wire = slot_floor.outerWire()
    print(f"Selected slot floor: center=({slot_center.x:.6f}, {slot_center.y:.6f}, {slot_center.z:.6f}), area={slot_floor.Area():.6f}")

    # Begin slightly in front of the old floor and extend beyond the complete
    # rear side. This preserves the exact existing obround profile while
    # removing both blind-pocket floors and all intervening frame material.
    start_offset = cq.Vector(0, 0, 0.5)
    cutter_wire = slot_wire.translate(start_offset)
    cut_distance = (bbox.zmax - bbox.zmin) + 20.0
    cutter = cq.Solid.extrudeLinear(
        cutter_wire,
        [],
        cq.Vector(0, 0, -cut_distance)
    )

    edited = model.cut(cutter)
    print("Edited valid:", edited.isValid())
    print(f"Edited volume: {edited.Volume():.6f} mm^3")
    print(f"Removed volume: {model.Volume() - edited.Volume():.6f} mm^3")
    print(f"Result solid count: {len(edited.Solids())}")

    if not edited.isValid():
        raise ValueError("Through-slot Boolean produced an invalid result")
    if edited.Volume() >= model.Volume():
        raise ValueError("Through-slot operation did not decrease model volume")
    if len(edited.Solids()) != 1:
        raise ValueError("Through-slot operation did not preserve a single bracket solid")

    return cq.Workplane(obj=edited)