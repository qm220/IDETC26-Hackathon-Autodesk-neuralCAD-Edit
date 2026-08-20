def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if not solids:
        raise ValueError("The imported STEP model contains no solids")

    def solid_info(index, solid):
        bb = solid.BoundingBox()
        return {
            "index": index,
            "solid": solid,
            "dx": bb.xmax - bb.xmin,
            "dy": bb.ymax - bb.ymin,
            "dz": bb.zmax - bb.zmin,
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

    source = None
    if len(data) > 40:
        candidate = data[40]
        if (candidate["dx"] > 2.5 * max(candidate["dy"], 1e-9)
                and candidate["dx"] > 2.5 * max(candidate["dz"], 1e-9)
                and 4 <= candidate["faces"] <= 10):
            source = candidate

    if source is None:
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
            if d["dy"] >= 0.12 * model_dy or d["dz"] >= 0.12 * model_dz:
                continue
            candidates.append(d)

        if not candidates:
            raise ValueError("Could not identify the existing horizontal front-panel button")

        zmid = 0.5 * (model_bb.zmin + model_bb.zmax)
        source = min(
            candidates,
            key=lambda d: (
                4.0 * abs(d["faces"] - 6)
                + abs(d["dx"] / max(d["dy"], 1e-9) - 5.0)
                - 2.0 * abs(d["cz"] - zmid) / max(model_dz, 1e-9)
            ),
        )

    pitch = 2.2 * source["dy"]
    upper_button = source["solid"].moved(cq.Location(cq.Vector(0.0, pitch, 0.0)))
    lower_button = source["solid"].moved(cq.Location(cq.Vector(0.0, -pitch, 0.0)))
    return cq.Compound.makeCompound(solids + [upper_button, lower_button])