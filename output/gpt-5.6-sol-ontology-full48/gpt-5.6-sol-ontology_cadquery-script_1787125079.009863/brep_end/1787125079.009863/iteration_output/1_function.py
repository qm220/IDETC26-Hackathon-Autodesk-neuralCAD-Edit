def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print("=== INPUT INSPECTION ===")
    print(f"Valid: {shape.isValid()}, solids={len(shape.Solids())}, faces={len(shape.Faces())}")
    bb = shape.BoundingBox()
    print(f"BBox: x={bb.xmin:.6f}..{bb.xmax:.6f}, y={bb.ymin:.6f}..{bb.ymax:.6f}, z={bb.zmin:.6f}..{bb.zmax:.6f}")

    # The inspected STEP topology confirms that the enlarged grip is R02 at
    # x=0..100 and that its correspondence plane is Y=260. The -Y half has
    # the complete 30 mm grip-corner treatment, while the corresponding +Y
    # half contains the deficient transition. Repair only this localized half;
    # do not mirror the shank, bore, pocket, or complete solid.
    y_mid = 260.0

    # Extract the reference half of the enlarged grip (x <= 100, y <= 260).
    # The box extends slightly beyond the model in the other directions while
    # terminating exactly at the grip/shank boundary x=100 and center plane.
    reference_box = cq.Solid.makeBox(
        105.0, 70.0, 130.0,
        cq.Vector(-5.0, 190.0, -460.0)
    )
    reference_half = shape.intersect(reference_box)
    print(
        f"Reference grip half: valid={reference_half.isValid()}, "
        f"solids={len(reference_half.Solids())}, faces={len(reference_half.Faces())}"
    )

    # Reflect only the localized grip half across y=260. This transfers the
    # corresponding existing 30 mm major blends and associated 5 mm peripheral
    # transitions without copying unrelated asymmetric shank geometry.
    repaired_positive_half = reference_half.mirror(
        "XZ", cq.Vector(0.0, y_mid, 0.0)
    )

    # Remove the deficient +Y half of R02, retaining the entire original model
    # elsewhere. The reflected reference geometry then replaces that local
    # region and reconnects to the untouched shank at x=100.
    replacement_box = cq.Solid.makeBox(
        105.0, 70.0, 130.0,
        cq.Vector(-5.0, y_mid, -460.0)
    )
    retained = shape.cut(replacement_box)
    final_shape = retained.fuse(repaired_positive_half)

    try:
        final_shape = final_shape.clean()
    except Exception as exc:
        print(f"Shape clean skipped: {exc}")

    print("=== RESULT INSPECTION ===")
    print(
        f"Valid: {final_shape.isValid()}, solids={len(final_shape.Solids())}, "
        f"faces={len(final_shape.Faces())}, edges={len(final_shape.Edges())}"
    )
    result_bb = final_shape.BoundingBox()
    print(
        f"BBox: x={result_bb.xmin:.6f}..{result_bb.xmax:.6f}, "
        f"y={result_bb.ymin:.6f}..{result_bb.ymax:.6f}, "
        f"z={result_bb.zmin:.6f}..{result_bb.zmax:.6f}"
    )

    # Report the resulting +Y grip blend surfaces for visual/topological
    # confirmation after execution.
    for i, face in enumerate(final_shape.Faces()):
        fbb = face.BoundingBox()
        if fbb.xmin <= 100.1 and fbb.ymax >= 289.9:
            c = face.Center()
            try:
                geom = face.geomType()
            except Exception:
                geom = "UNKNOWN"
            print(
                f"RESULT FACE {i}: type={geom}, area={face.Area():.6f}, "
                f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
                f"bbox=({fbb.xmin:.6f}..{fbb.xmax:.6f}, "
                f"{fbb.ymin:.6f}..{fbb.ymax:.6f}, "
                f"{fbb.zmin:.6f}..{fbb.zmax:.6f})"
            )

    return cq.Workplane("XY").newObject([final_shape])