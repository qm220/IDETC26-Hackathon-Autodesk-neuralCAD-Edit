def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if not solids:
        raise ValueError("The imported STEP model contains no solids")

    def solid_info(index, solid):
        bb = solid.BoundingBox()
        dx = bb.xmax - bb.xmin
        dy = bb.ymax - bb.ymin
        dz = bb.zmax - bb.zmin
        return {
            "index": index,
            "solid": solid,
            "dx": dx,
            "dy": dy,
            "dz": dz,
            "cx": 0.5 * (bb.xmin + bb.xmax),
            "cy": 0.5 * (bb.ymin + bb.ymax),
            "cz": 0.5 * (bb.zmin + bb.zmax),
            "faces": len(solid.Faces()),
        }

    data = [solid_info(i, solid) for i, solid in enumerate(solids)]
    model_bb = root.BoundingBox()
    model_dx = model_bb.xmax - model_bb.xmin
    model_dy = model_bb.ymax - model_bb.ymin
    model_dz = model_bb.zmax - model_bb.zmin

    # The planning data assigns the horizontal indicator button to solid 40.
    # Prefer that semantic identity, but verify its proportions so the function
    # remains safe if STEP import ordering changes.
    source = None
    if len(data) > 40:
        candidate = data[40]
        if (
            candidate["dx"] > 2.5 * max(candidate["dy"], 1e-9)
            and candidate["dx"] > 2.5 * max(candidate["dz"], 1e-9)
            and 4 <= candidate["faces"] <= 10
        ):
            source = candidate

    if source is None:
        # Geometry fallback: find a compact six-faced pill whose longest axis is
        # X. Horizontal ribs have only three faces, while dots and feet are not
        # strongly elongated. Favor the shallow exterior control-plane solids.
        candidates = []
        for d in data:
            if not (4 <= d["faces"] <= 10):
                continue
            if d["dx"] <= 3.0 * max(d["dy"], 1e-9):
                continue
            if d["dx"] <= 3.0 * max(d["dz"], 1e-9):
                continue
            if d["dx"] >= 0.35 * model_dx:
                continue
            if d["dy"] >= 0.12 * model_dy:
                continue
            if d["dz"] >= 0.12 * model_dz:
                continue
            candidates.append(d)

        if not candidates:
            raise ValueError("Could not identify the existing horizontal front-panel button")

        # The desired button has six faces and is substantially wider than tall.
        # Prefer candidates near either Z exterior because the front-depth sign
        # can differ between source-model coordinate conventions.
        zmid = 0.5 * (model_bb.zmin + model_bb.zmax)
        source = min(
            candidates,
            key=lambda d: (
                4.0 * abs(d["faces"] - 6)
                + abs(d["dx"] / max(d["dy"], 1e-9) - 5.0)
                - 2.0 * abs(d["cz"] - zmid) / max(model_dz, 1e-9)
            ),
        )

    # In this model X is horizontal across the control panel, Y is vertical in
    # its front view, and Z is the shallow panel-normal direction. Translate
    # exact copies only along Y to form a centered three-button column.
    # A 2.2-height pitch provides a clear equal gap while staying local to the
    # original upper control-panel region.
    pitch = 2.2 * source["dy"]
    if pitch <= 0:
        raise ValueError("Selected button has invalid height")

    upper_button = source["solid"].moved(
        cq.Location(cq.Vector(0.0, pitch, 0.0))
    )
    lower_button = source["solid"].moved(
        cq.Location(cq.Vector(0.0, -pitch, 0.0))
    )

    result = cq.Compound.makeCompound(solids + [upper_button, lower_button])

    print("Imported solids: %d" % len(solids))
    print("Selected horizontal button solid: %d" % source["index"])
    print(
        "Button bbox: dx=%.6f, dy=%.6f, dz=%.6f, faces=%d"
        % (source["dx"], source["dy"], source["dz"], source["faces"])
    )
    print(
        "Button center: (%.6f, %.6f, %.6f)"
        % (source["cx"], source["cy"], source["cz"])
    )
    print("Added exact copies at equal Y offsets +/-%.6f" % pitch)
    return result