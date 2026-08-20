def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if not solids:
        raise ValueError("The input STEP file contains no solids")

    # Identify the finned heatsink from its high face count and large number of
    # planar cooling-fin faces. All other exploded components remain untouched.
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

    print("Imported solids:", len(solids))
    print("Selected heatsink index:", heatsink_index)
    print("Heatsink bbox:", hb.xlen, hb.ylen, hb.zlen)

    # On this model the rear mounting holes have circular entry edges on the
    # +Y face. For modeled threaded holes, many additional circular-looking
    # thread/runout edges are eccentric to the true hole axis. The largest
    # circular entry edge is concentric with the actual mounting axis, so use
    # those edges rather than clustering every thread edge by its edge center.
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

    # Deduplicate coincident entry circles.
    axes = []
    for item in sorted(axis_candidates, key=lambda p: (p["z"], p["x"])):
        if not any(math.hypot(item["x"] - q["x"], item["z"] - q["z"]) < 0.25 for q in axes):
            axes.append(item)

    print("Rear mounting-axis candidates:")
    for item in axes:
        print("  x=%.3f z=%.3f entry_r=%.3f" % (item["x"], item["z"], item["r"]))

    if len(axes) != 3:
        # Prefer the three candidates forming two points on one row and one
        # centered point on the other row.
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

    # Determine the two-hole row and the centered third hole. In the source
    # geometry the pair is the upper row and the single hole is the lower row.
    axes = sorted(axes, key=lambda p: p["z"], reverse=True)
    top_pair = sorted(axes[:2], key=lambda p: p["x"])
    old_single = axes[2]

    row_tolerance = 0.5
    if abs(top_pair[0]["z"] - top_pair[1]["z"]) > row_tolerance:
        # General fallback: find the pair with the closest Z coordinates.
        possible_pairs = [
            (axes[0], axes[1], axes[2]),
            (axes[0], axes[2], axes[1]),
            (axes[1], axes[2], axes[0]),
        ]
        a, b, single = min(possible_pairs, key=lambda t: abs(t[0]["z"] - t[1]["z"]))
        top_pair = sorted([a, b], key=lambda p: p["x"])
        old_single = single

    x_left = top_pair[0]["x"]
    x_right = top_pair[1]["x"]
    z_top = 0.5 * (top_pair[0]["z"] + top_pair[1]["z"])
    z_bottom = old_single["z"]

    print("Existing three-point pattern:", [
        (round(top_pair[0]["x"], 3), round(top_pair[0]["z"], 3)),
        (round(top_pair[1]["x"], 3), round(top_pair[1]["z"], 3)),
        (round(old_single["x"], 3), round(old_single["z"], 3)),
    ])
    print("Target four-point pattern:", [
        (round(x_left, 3), round(z_top, 3)),
        (round(x_right, 3), round(z_top, 3)),
        (round(x_left, 3), round(z_bottom, 3)),
        (round(x_right, 3), round(z_bottom, 3)),
    ])

    # Copy the complete existing lower mounting-hole cavity, including its
    # modeled thread, runout, and entry relief. This gives the two new lower
    # holes exactly the same hole type as the original mounting system. The
    # already-correct upper pair is retained without alteration.
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

    # Restore local material at the obsolete centered lower mounting hole.
    edited = heatsink.fuse(capture)

    # Relocate copies of that exact cavity to the two lower corners. The old
    # centered point is thereby replaced by a symmetric two-point lower row.
    for target_x in (x_left, x_right):
        dx = target_x - old_single["x"]
        dz = z_bottom - old_single["z"]
        moved_cavity = cavity.moved(cq.Location(cq.Vector(dx, 0, dz)))
        edited = edited.cut(moved_cavity)

    try:
        edited = edited.clean()
    except Exception:
        pass

    if not edited.isValid():
        raise ValueError("The modified heatsink is not a valid solid")
    if len(edited.Solids()) != 1:
        raise ValueError("The modified heatsink unexpectedly contains %d solids" % len(edited.Solids()))

    print("Modified heatsink valid:", edited.isValid())
    print("Modified heatsink volume: %.3f" % edited.Volume())

    output_solids = list(solids)
    output_solids[heatsink_index] = edited
    result = cq.Compound.makeCompound(output_solids)
    return cq.Workplane("XY").newObject([result])