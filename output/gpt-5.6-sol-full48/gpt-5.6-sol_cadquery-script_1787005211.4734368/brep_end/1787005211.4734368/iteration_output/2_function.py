def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val()

    solids = sorted(list(root.Solids()), key=lambda s: s.Volume(), reverse=True)
    if len(solids) < 2:
        raise ValueError(f"Expected the housing and wheel solids, but found {len(solids)} solid(s)")

    housing = solids[0]
    wheel = solids[1]
    button_height = 2.0

    crown_normal = cq.Vector(-0.0021, 0.9734, 0.2290).normalized()
    offset_vector = crown_normal.multiply(button_height)
    raised_housing = housing.translate(offset_vector)

    plane = cq.Plane(
        origin=(0.0, 40.0, 0.0),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, -1.0, 0.0)
    )

    def make_rounded_prism(center_x, center_z, width=19.0, length=74.0, radius=4.0):
        prism_wp = (
            cq.Workplane(plane)
            .center(center_x, center_z)
            .rect(width, length)
            .extrude(35.0)
        )
        try:
            prism_wp = prism_wp.edges("|Y").fillet(radius)
        except Exception as exc:
            print(f"Footprint corner fillet fallback: {exc}")
        return prism_wp.val()

    left_prism = make_rounded_prism(center_x=13.5, center_z=24.0)
    right_prism = make_rounded_prism(center_x=41.5, center_z=24.0)

    def make_button(prism, name):
        raw_cap = raised_housing.intersect(prism).cut(housing)
        cap_solids = sorted(list(raw_cap.Solids()), key=lambda s: s.Volume(), reverse=True)
        if not cap_solids:
            raise ValueError(f"{name} button construction produced no solid")

        cap = cap_solids[0]
        bb = cap.BoundingBox()
        print(
            f"{name} button: volume={cap.Volume():.3f}, faces={len(cap.Faces())}, "
            f"bbox=({bb.xmin:.3f}, {bb.ymin:.3f}, {bb.zmin:.3f}) to "
            f"({bb.xmax:.3f}, {bb.ymax:.3f}, {bb.zmax:.3f})"
        )
        return cap

    left_button = make_button(left_prism, "Left")
    right_button = make_button(right_prism, "Right")

    result = cq.Compound.makeCompound([
        housing,
        wheel,
        left_button,
        right_button
    ])

    print(f"Source solids: {len(solids)}")
    print(f"Result solids: {len(result.Solids())}")
    print(f"Result valid: {result.isValid()}")
    print("Operation finished: two separate 2 mm conformal click buttons were added to the forward-central upper crown on opposite sides of the scroll wheel.")

    return cq.Workplane(obj=result)