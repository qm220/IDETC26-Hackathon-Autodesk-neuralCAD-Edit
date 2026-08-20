def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if not solids:
        raise ValueError("The input STEP file contains no solids")

    def heatsink_score(solid):
        planar = 0
        for face in solid.Faces():
            try:
                if face.geomType() == "PLANE":
                    planar += 1
            except Exception:
                pass
        bb = solid.BoundingBox()
        size_bonus = 15 if min(bb.xlen, bb.ylen, bb.zlen) > 8.0 else 0
        return len(solid.Faces()) + 1.8 * planar + size_bonus

    heatsink_index = max(range(len(solids)), key=lambda i: heatsink_score(solids[i]))
    heatsink = solids[heatsink_index]
    hb = heatsink.BoundingBox()
    rear_y = hb.ymax

    rear_circles = []
    for edge in heatsink.Edges():
        try:
            if edge.geomType() != "CIRCLE":
                continue
            eb = edge.BoundingBox()
            c = edge.Center()
            r = float(edge.radius())
            if eb.ylen < 0.10 and abs(c.y - rear_y) < 0.25 and 0.7 < r < 3.0:
                rear_circles.append({"x": c.x, "z": c.z, "r": r})
        except Exception:
            pass

    if not rear_circles:
        raise ValueError("No circular rear-face mounting entries were found")

    max_entry_radius = max(item["r"] for item in rear_circles)
    axis_candidates = [
        item for item in rear_circles
        if item["r"] >= max_entry_radius - 0.08
    ]

    axes = []
    for item in sorted(axis_candidates, key=lambda p: (p["z"], p["x"])):
        if not any(math.hypot(item["x"] - q["x"], item["z"] - q["z"]) < 0.25 for q in axes):
            axes.append(item)

    if len(axes) != 3:
        center_x = hb.center.x
        plausible = [
            p for p in axes
            if abs(p["x"] - center_x) < 0.40 * hb.xlen
            and abs(p["z"] - hb.center.z) < 0.40 * hb.zlen
        ]
        if len(plausible) == 3:
            axes = plausible
        else:
            raise ValueError("Expected three true rear mounting entries, found %d" % len(axes))

    axes = sorted(axes, key=lambda p: p["z"], reverse=True)
    top_pair = sorted(axes[:2], key=lambda p: p["x"])
    old_single = axes[2]

    if abs(top_pair[0]["z"] - top_pair[1]["z"]) > 0.5:
        possible_pairs = [
            (axes[0], axes[1], axes[2]),
            (axes[0], axes[2], axes[1]),
            (axes[1], axes[2], axes[0]),
        ]
        a, b, old_single = min(possible_pairs, key=lambda t: abs(t[0]["z"] - t[1]["z"]))
        top_pair = sorted([a, b], key=lambda p: p["x"])

    x_left = top_pair[0]["x"]
    x_right = top_pair[1]["x"]
    z_bottom = old_single["z"]

    copy_depth = min(7.0, 0.45 * hb.ylen)
    capture_radius = max_entry_radius + 0.20
    capture = cq.Solid.makeCylinder(
        capture_radius,
        copy_depth,
        cq.Vector(old_single["x"], rear_y - copy_depth, old_single["z"]),
        cq.Vector(0, 1, 0),
    )

    cavity = capture.cut(heatsink)
    if cavity.Volume() <= 1.0e-5:
        raise ValueError("Failed to extract the existing mounting-hole cavity")

    edited = heatsink.fuse(capture)

    for target_x in (x_left, x_right):
        moved_cavity = cavity.moved(
            cq.Location(cq.Vector(target_x - old_single["x"], 0, z_bottom - old_single["z"]))
        )
        edited = edited.cut(moved_cavity)

    try:
        edited = edited.clean()
    except Exception:
        pass

    if not edited.isValid():
        raise ValueError("The modified heatsink is not a valid solid")
    if len(edited.Solids()) != 1:
        raise ValueError("The modified heatsink unexpectedly contains %d solids" % len(edited.Solids()))

    output_solids = list(solids)
    output_solids[heatsink_index] = edited
    result = cq.Compound.makeCompound(output_solids)
    return cq.Workplane("XY").newObject([result])