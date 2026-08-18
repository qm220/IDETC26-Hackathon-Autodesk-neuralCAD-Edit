def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    body = model.val()
    bbox = body.BoundingBox()

    print(f"Input valid: {body.isValid()}")
    print(f"Input volume: {body.Volume():.6f} mm^3")
    print(f"Input bbox: x=({bbox.xmin:.3f},{bbox.xmax:.3f}), y=({bbox.ymin:.3f},{bbox.ymax:.3f}), z=({bbox.zmin:.3f},{bbox.zmax:.3f})")

    # Locate the transverse planar face at the closed end of the open-jaw slot.
    # It spans the full thickness, is centered laterally, is about 10 mm wide,
    # and has effectively no extent in Z.
    candidates = []
    for i, face in enumerate(body.Faces()):
        fb = face.BoundingBox()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        if geom_type == "PLANE":
            print(f"Planar face {i}: xlen={fb.xlen:.3f}, ylen={fb.ylen:.3f}, zlen={fb.zlen:.3f}, center=({face.Center().x:.3f},{face.Center().y:.3f},{face.Center().z:.3f})")
            if (fb.ylen > 0.90 * bbox.ylen and
                fb.zlen < 0.05 and
                8.0 < fb.xlen < 12.5 and
                abs((fb.xmin + fb.xmax) * 0.5) < 1.0):
                candidates.append(face)

    if not candidates:
        raise ValueError("Could not identify the full-thickness slot-root planar face")

    # The open jaw is at the negative-Z end, so choose the negative-Z candidate
    # if more than one geometrically similar face is present.
    root_face = sorted(candidates, key=lambda f: f.Center().z)[0]
    root_box = root_face.BoundingBox()
    old_root_z = 0.5 * (root_box.zmin + root_box.zmax)

    jaw_half_width = 10.0
    root_radius = 5.0
    depth_reduction = 10.0
    new_root_z = old_root_z - depth_reduction
    new_tangent_z = new_root_z - root_radius

    print(f"Identified old slot-root Z: {old_root_z:.6f} mm")
    print(f"Relocated slot-root Z: {new_root_z:.6f} mm")
    print("Jaw flats retained at x=-10 and x=+10 (20 mm separation)")

    # Add only the material between the old and relocated rounded roots.
    # The lower boundary reproduces the existing R5 tangent construction:
    # straight jaw flats at x=+/-10, quarter-circle blends, and a 10 mm
    # transverse root flat between x=-5 and x=+5.
    overlap_z = old_root_z + 2.0
    r_mid = root_radius / (2.0 ** 0.5)

    sketch_plane = cq.Plane(
        origin=(0.0, bbox.ymax, 0.0),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, -1.0, 0.0)
    )

    fill = (cq.Workplane(sketch_plane)
        .moveTo(-jaw_half_width, new_tangent_z)
        .threePointArc((-5.0 - r_mid, new_tangent_z + r_mid),
                       (-5.0, new_root_z))
        .lineTo(5.0, new_root_z)
        .threePointArc((5.0 + r_mid, new_tangent_z + r_mid),
                       (jaw_half_width, new_tangent_z))
        .lineTo(jaw_half_width, overlap_z)
        .lineTo(-jaw_half_width, overlap_z)
        .close()
        .extrude(bbox.ylen)
    )

    result = model.union(fill).clean()
    result_shape = result.val()
    print(f"Output valid: {result_shape.isValid()}")
    print(f"Output volume: {result_shape.Volume():.6f} mm^3")
    print(f"Added volume: {result_shape.Volume() - body.Volume():.6f} mm^3")
    print(f"Output solids: {len(result_shape.Solids())}, faces: {len(result_shape.Faces())}")

    if not result_shape.isValid() or len(result_shape.Solids()) != 1:
        raise ValueError("Edited wrench did not produce one valid solid")

    return result