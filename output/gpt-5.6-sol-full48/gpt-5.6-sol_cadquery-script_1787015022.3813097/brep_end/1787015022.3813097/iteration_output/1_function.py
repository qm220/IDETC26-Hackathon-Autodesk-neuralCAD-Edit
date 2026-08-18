def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    # STEP import may return a Compound. Extract the actual solid before using
    # solid-only methods such as Volume(), which caused the previous failure.
    solids = imported.solids().vals()
    if not solids:
        try:
            solids = imported.val().Solids()
        except Exception:
            solids = []
    if not solids:
        raise ValueError("The imported STEP file contains no solid bodies")

    body = max(solids, key=lambda s: s.Volume())
    bbox = body.BoundingBox()
    input_volume = body.Volume()

    print(f"Imported solids: {len(solids)}")
    print(f"Input valid: {body.isValid()}")
    print(f"Input volume: {input_volume:.6f} mm^3")
    print(
        f"Input bbox: x=({bbox.xmin:.3f},{bbox.xmax:.3f}), "
        f"y=({bbox.ymin:.3f},{bbox.ymax:.3f}), "
        f"z=({bbox.zmin:.3f},{bbox.zmax:.3f})"
    )

    # Find the transverse, full-thickness planar face at the closed root of
    # the open-ended U-shaped jaw slot. It is centered about X=0, has an
    # approximately 10 mm X extent, and has negligible Z extent.
    candidates = []
    for i, face in enumerate(body.Faces()):
        fb = face.BoundingBox()
        geom_type = face.geomType()
        if geom_type == "PLANE":
            center = face.Center()
            if (
                fb.ylen > 0.90 * bbox.ylen
                and fb.zlen < 0.05
                and 8.0 < fb.xlen < 12.5
                and abs(0.5 * (fb.xmin + fb.xmax)) < 1.0
            ):
                candidates.append(face)
                print(
                    f"Slot-root candidate face {i}: center="
                    f"({center.x:.3f},{center.y:.3f},{center.z:.3f}), "
                    f"size=({fb.xlen:.3f},{fb.ylen:.3f},{fb.zlen:.3f})"
                )

    if not candidates:
        raise ValueError("Could not identify the full-thickness slot-root face")

    # The open jaw is at the negative-Z end. Select the matching candidate
    # nearest that end if several transverse faces satisfy the filters.
    root_face = min(candidates, key=lambda f: f.Center().z)
    old_root_z = root_face.Center().z

    jaw_half_width = 10.0
    root_radius = 5.0
    depth_reduction = 10.0

    # Moving the root toward negative Z moves it toward the open jaw tips and
    # therefore makes the slot exactly 10 mm shallower.
    new_root_z = old_root_z - depth_reduction
    new_tangent_z = new_root_z - root_radius

    print(f"Old root-flat Z: {old_root_z:.6f} mm")
    print(f"New root-flat Z: {new_root_z:.6f} mm")
    print(f"Requested depth reduction: {depth_reduction:.6f} mm")
    print("Jaw flats remain at X=-10 and X=+10: separation = 20 mm")

    # Construct the material that replaces the deepest 10 mm of the slot.
    # Its negative-Z boundary is the relocated root: an R5 corner, a 10 mm
    # transverse root flat, and another R5 corner. The profile overlaps the
    # original solid slightly beyond the old root to guarantee a robust union.
    overlap_z = old_root_z + 1.0
    r_mid = root_radius / (2.0 ** 0.5)

    top_down_plane = cq.Plane(
        origin=(0.0, bbox.ymax, 0.0),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, -1.0, 0.0),
    )

    fill = (
        cq.Workplane(top_down_plane)
        .moveTo(-jaw_half_width, new_tangent_z)
        .threePointArc(
            (-5.0 - r_mid, new_tangent_z + r_mid),
            (-5.0, new_root_z),
        )
        .lineTo(5.0, new_root_z)
        .threePointArc(
            (5.0 + r_mid, new_tangent_z + r_mid),
            (jaw_half_width, new_tangent_z),
        )
        .lineTo(jaw_half_width, overlap_z)
        .lineTo(-jaw_half_width, overlap_z)
        .close()
        .extrude(bbox.ylen)
    )

    base = cq.Workplane("XY").newObject([body])
    result = base.union(fill).clean()
    output_solids = result.solids().vals()

    if len(output_solids) != 1:
        raise ValueError(
            f"Expected one solid after editing, but obtained {len(output_solids)}"
        )

    result_shape = output_solids[0]
    output_volume = result_shape.Volume()

    print(f"Output valid: {result_shape.isValid()}")
    print(f"Output solids: {len(output_solids)}")
    print(f"Output faces: {len(result_shape.Faces())}")
    print(f"Output volume: {output_volume:.6f} mm^3")
    print(f"Added volume: {output_volume - input_volume:.6f} mm^3")
    print("Nominal edited jaw geometry: X flats = -10/+10 mm, R5 root corners")

    if not result_shape.isValid():
        raise ValueError("The edited wrench is not a valid solid")
    if output_volume <= input_volume:
        raise ValueError("The shallower cutout did not add material as expected")

    return cq.Workplane("XY").newObject([result_shape])