def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    result = imported.val()

    # Add three matching socket hubs, retaining the original hub at x=0.
    # Each new hub has a 14 mm OD, 10 mm blind bore, and a rounded root.
    for x in (24.0, 48.0, 72.0):
        root_sphere = cq.Solid.makeSphere(
            7.0,
            cq.Vector(x, 24.0, 4.0)
        )
        root_clip = cq.Solid.makeBox(
            14.0, 6.0, 14.0,
            cq.Vector(x - 7.0, 19.0, -3.0)
        )
        rounded_root = root_sphere.intersect(root_clip)

        outer_hub = cq.Solid.makeCylinder(
            7.0, 10.0,
            cq.Vector(x, 24.0, 4.0),
            cq.Vector(0.0, 1.0, 0.0)
        )

        hub_body = rounded_root.fuse(outer_hub)

        # Cut from the open front at y=34 back to a blind floor at y=25.
        bore = cq.Solid.makeCylinder(
            5.0, 9.2,
            cq.Vector(x, 25.0, 4.0),
            cq.Vector(0.0, 1.0, 0.0)
        )
        hub_body = hub_body.cut(bore)
        result = result.fuse(hub_body)

    # Add three transverse stabilizing feet between adjacent holders.
    # The feet match the original plate thickness and widen the footprint
    # symmetrically from y=3 to y=31.
    for x in (12.0, 36.0, 60.0):
        foot = cq.Solid.makeBox(
            4.0, 28.0, 4.0,
            cq.Vector(x - 2.0, 3.0, 2.0)
        )
        result = result.fuse(foot)

    result = result.clean()
    print("Added three socket hubs for four total holders.")
    print("Added three paired transverse stabilizing feet.")
    print(f"Result valid: {result.isValid()}")
    print(f"Result solids: {len(result.Solids())}")
    bbox = result.BoundingBox()
    print(f"Bounding box: X={bbox.xlen:.3f}, Y={bbox.ylen:.3f}, Z={bbox.zlen:.3f} mm")

    return cq.Workplane("XY").newObject([result])