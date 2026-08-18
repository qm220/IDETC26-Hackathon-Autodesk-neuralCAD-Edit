def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    # The enlarged head occupies x=0..100. Its existing lower-side edge
    # treatments are reflected about the thickness midplane z=-395 so the
    # previously sharp upper/left-side edges receive exactly matching radii.
    z_mid = -395.0
    mirrored = original.mirror("XY", (0.0, 0.0, z_mid))

    # Localize the symmetry operation to the enlarged head. A small overlap at
    # x=100 makes the final fusion robust and preserves the arm, blind bore,
    # and underside relief pocket outside the head.
    bb = original.BoundingBox()
    margin = 5.0
    overlap = 0.02

    head_clip = cq.Solid.makeBox(
        100.0 + overlap + margin,
        (bb.ymax - bb.ymin) + 2.0 * margin,
        (bb.zmax - bb.zmin) + 2.0 * margin,
        cq.Vector(-margin, bb.ymin - margin, bb.zmin - margin)
    )
    body_clip = cq.Solid.makeBox(
        (bb.xmax - (100.0 - overlap)) + margin,
        (bb.ymax - bb.ymin) + 2.0 * margin,
        (bb.zmax - bb.zmin) + 2.0 * margin,
        cq.Vector(100.0 - overlap, bb.ymin - margin, bb.zmin - margin)
    )

    original_head = original.intersect(head_clip)
    mirrored_head = mirrored.intersect(head_clip)

    # Intersection retains the existing rounded lower side while trimming the
    # opposite side to the reflected R30/R5 envelope.
    rounded_head = original_head.intersect(mirrored_head)
    unchanged_body = original.intersect(body_clip)
    result = rounded_head.fuse(unchanged_body)

    try:
        result = result.clean()
    except Exception:
        pass

    print("Original valid:", original.isValid())
    print("Result valid:", result.isValid())
    print("Original volume:", round(original.Volume(), 6))
    print("Result volume:", round(result.Volume(), 6))
    print("Removed by matched head radii:", round(original.Volume() - result.Volume(), 6))
    print("Result solids:", len(result.Solids()))

    return cq.Workplane("XY").newObject([result])