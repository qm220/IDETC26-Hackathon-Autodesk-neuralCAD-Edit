def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if not solids:
        raise ValueError("The imported STEP model contains no solids")

    model_bb = root.BoundingBox()
    model_dx = model_bb.xmax - model_bb.xmin
    model_dy = model_bb.ymax - model_bb.ymin
    model_dz = model_bb.zmax - model_bb.zmin

    def metrics(index, solid):
        bb = solid.BoundingBox()
        return {
            "index": index,
            "solid": solid,
            "bb": bb,
            "dx": bb.xmax - bb.xmin,
            "dy": bb.ymax - bb.ymin,
            "dz": bb.zmax - bb.zmin,
            "cx": 0.5 * (bb.xmin + bb.xmax),
            "cy": 0.5 * (bb.ymin + bb.ymax),
            "cz": 0.5 * (bb.zmin + bb.zmax),
            "faces": len(solid.Faces()),
        }

    data = [metrics(i, s) for i, s in enumerate(solids)]

    # Locate the shallow selector-scale arc first. In the source model it lies on
    # the front control plane, has a roughly 2:1 horizontal envelope, and has
    # three faces. This provides a stable positional reference even if STEP solid
    # ordering changes during import.
    arc_candidates = [
        d for d in data
        if d["faces"] <= 4
        and 40.0 <= d["dx"] <= 0.22 * model_dx
        and 20.0 <= d["dy"] <= 0.12 * model_dy
        and d["dx"] > 1.25 * d["dy"]
        and d["dz"] <= max(3.0, 0.015 * model_dz)
        and d["cz"] >= model_bb.zmax - 0.06 * model_dz
    ]

    arc_ref = None
    if arc_candidates:
        arc_ref = min(
            arc_candidates,
            key=lambda d: abs(d["dx"] / max(d["dy"], 1e-6) - 1.75)
        )

    # The requested source is a compact, six-faced, horizontally elongated
    # rounded button on the same shallow front plane. Face count distinguishes it
    # from the nearby three-faced scale arc and from the long panel rails/ribs.
    button_candidates = [
        d for d in data
        if d["faces"] == 6
        and 25.0 <= d["dx"] <= 0.22 * model_dx
        and 3.0 <= d["dy"] <= 0.06 * model_dy
        and d["dx"] >= 3.0 * d["dy"]
        and d["dz"] <= max(12.0, 0.04 * model_dz)
        and d["cz"] >= model_bb.zmax - 0.08 * model_dz
    ]

    if not button_candidates:
        raise ValueError("Could not identify the existing horizontal front-panel button")

    if arc_ref is not None:
        # The button is to the left of the rotary selector/scale and at nearly the
        # same height and front depth.
        positional = [
            d for d in button_candidates
            if d["cx"] < arc_ref["cx"] - 0.04 * model_dx
            and abs(d["cy"] - arc_ref["cy"]) < 0.12 * model_dy
            and abs(d["cz"] - arc_ref["cz"]) < max(15.0, 0.05 * model_dz)
        ]
        if positional:
            button_candidates = positional

        source = min(
            button_candidates,
            key=lambda d: (
                abs((arc_ref["cx"] - d["cx"]) - 0.25 * model_dx)
                + 1.5 * abs(d["cy"] - arc_ref["cy"])
                + 4.0 * abs(d["cz"] - arc_ref["cz"])
            )
        )
    else:
        source = max(
            button_candidates,
            key=lambda d: d["cz"] - 0.1 * abs(d["cy"] - 0.5 * (model_bb.ymin + model_bb.ymax))
        )

    # Equal translations preserve the exact source shape and orientation. A
    # 1.7-button-height pitch leaves a visible gap while keeping the new controls
    # local to the existing control-panel area.
    spacing = 1.7 * source["dy"]
    upper_button = source["solid"].moved(cq.Location(cq.Vector(0, spacing, 0)))
    lower_button = source["solid"].moved(cq.Location(cq.Vector(0, -spacing, 0)))

    result = cq.Compound.makeCompound(solids + [upper_button, lower_button])

    print("Imported solids: %d" % len(solids))
    if arc_ref is not None:
        print("Selector scale reference solid: %d" % arc_ref["index"])
    print("Selected horizontal button solid: %d" % source["index"])
    print(
        "Button bbox: dx=%.3f, dy=%.3f, dz=%.3f, faces=%d"
        % (source["dx"], source["dy"], source["dz"], source["faces"])
    )
    print(
        "Button center: (%.3f, %.3f, %.3f)"
        % (source["cx"], source["cy"], source["cz"])
    )
    print("Added exact copies at equal Y offsets +/-%.3f" % spacing)
    return result