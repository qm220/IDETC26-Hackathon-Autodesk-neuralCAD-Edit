def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())

    if not solids:
        raise ValueError("The input STEP file contains no solids")

    print("Imported solids:", len(solids))
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        print(
            "solid %d: faces=%d volume=%.3f bbox=(%.3f, %.3f, %.3f) center=(%.3f, %.3f, %.3f)"
            % (
                i, len(solid.Faces()), solid.Volume(),
                bb.xlen, bb.ylen, bb.zlen,
                bb.center.x, bb.center.y, bb.center.z,
            )
        )

    # The finned heatsink has a large number of planar fin faces. Score solids
    # by face count, with a bonus for repeated planar faces, rather than relying
    # on the imported STEP solid ordering.
    def heatsink_score(solid):
        planar = 0
        for face in solid.Faces():
            try:
                if face.geomType() == "PLANE":
                    planar += 1
            except Exception:
                pass
        bb = solid.BoundingBox()
        dimensional_bonus = 10 if min(bb.xlen, bb.ylen, bb.zlen) > 8 else 0
        return len(solid.Faces()) + 1.8 * planar + dimensional_bonus

    heatsink_index = max(range(len(solids)), key=lambda i: heatsink_score(solids[i]))
    heatsink = solids[heatsink_index]
    hb = heatsink.BoundingBox()
    print("Selected heatsink solid index:", heatsink_index)
    print("Heatsink score:", heatsink_score(heatsink))

    # Find circular entry edges on the semantic rear (+Y) face. Circular edges
    # in that face have essentially zero Y extent and comparable X/Z extents.
    rear_y = hb.ymax
    raw_circles = []
    for edge in heatsink.Edges():
        try:
            if edge.geomType() != "CIRCLE":
                continue
            eb = edge.BoundingBox()
            c = edge.Center()
            r = float(edge.radius())
            if eb.ylen < 0.08 and abs(c.y - rear_y) < 1.25 and r > 0.45:
                raw_circles.append((c.x, c.y, c.z, r))
        except Exception:
            continue

    # Merge concentric circles belonging to a chamfer/thread/bore stack.
    groups = []
    for x, y, z, r in raw_circles:
        found = None
        for g in groups:
            if math.hypot(x - g["x"], z - g["z"]) < 0.18:
                found = g
                break
        if found is None:
            groups.append({"x": x, "z": z, "radii": [r]})
        else:
            found["radii"].append(r)

    for g in groups:
        g["rmin"] = min(g["radii"])
        g["rmax"] = max(g["radii"])

    groups.sort(key=lambda g: (g["z"], g["x"]))
    print("Rear +Y circular opening groups:")
    for g in groups:
        print("  center=(%.3f, %.3f), radii=%s" % (
            g["x"], g["z"], ",".join("%.3f" % r for r in sorted(g["radii"]))
        ))

    if len(groups) < 3:
        raise ValueError("Could not identify the rear three-point mounting pattern")

    # Separate the smaller mounting holes from the two substantially larger
    # functional bores. Prefer groups below 70 percent of the largest opening.
    largest_opening = max(g["rmax"] for g in groups)
    small_groups = [g for g in groups if g["rmax"] < 0.70 * largest_opening]

    # If thread/chamfer topology generated extra groups, retain the three groups
    # nearest the expected triangular mounting locations: one upper center and
    # two lower symmetric positions.
    if len(small_groups) != 3:
        center_x = hb.center.x
        center_z = hb.center.z
        plausible = [
            g for g in groups
            if g["rmax"] < 3.5
            and abs(g["x"] - center_x) < 0.48 * hb.xlen
            and abs(g["z"] - center_z) < 0.48 * hb.zlen
        ]
        if len(plausible) >= 3:
            # Choose the combination represented by the topmost near-center
            # point and the two lowest points on opposite sides.
            upper = min(plausible, key=lambda g: abs(g["x"] - center_x) - 0.25 * g["z"])
            below = sorted(
                [g for g in plausible if g is not upper],
                key=lambda g: g["z"]
            )
            lower_pool = below[:max(2, min(4, len(below)))]
            left = min(lower_pool, key=lambda g: g["x"])
            right = max(lower_pool, key=lambda g: g["x"])
            small_groups = [upper, left, right]

    if len(small_groups) != 3:
        raise ValueError("Rear mounting-hole classification was ambiguous: found %d candidates" % len(small_groups))

    small_groups.sort(key=lambda g: g["z"], reverse=True)
    upper = small_groups[0]
    lower_pair = sorted(small_groups[1:], key=lambda g: g["x"])

    # Confirm the triangular arrangement. The old upper point supplies the new
    # upper row height; the old lower pair supplies the symmetric X spacing and
    # lower row height. This changes only the mounting pattern while retaining
    # the heatsink envelope and all large passages.
    x_left = lower_pair[0]["x"]
    x_right = lower_pair[1]["x"]
    z_upper = upper["z"]
    z_lower = 0.5 * (lower_pair[0]["z"] + lower_pair[1]["z"])

    # Use the common existing mounting-hole geometry. The smallest entry radius
    # is the principal bore and the largest is the entry relief/chamfer radius.
    bore_radius = sum(g["rmin"] for g in small_groups) / 3.0
    entry_radius = sum(g["rmax"] for g in small_groups) / 3.0
    entry_radius = max(entry_radius, bore_radius)

    print("Old 3-point centers:", [(round(g["x"], 3), round(g["z"], 3)) for g in small_groups])
    print("New 4-point centers:", [
        (round(x_left, 3), round(z_upper, 3)),
        (round(x_right, 3), round(z_upper, 3)),
        (round(x_left, 3), round(z_lower, 3)),
        (round(x_right, 3), round(z_lower, 3)),
    ])
    print("Mounting bore radius=%.3f entry radius=%.3f" % (bore_radius, entry_radius))

    edited = heatsink

    # Heal the complete old hole chains by restoring material only inside
    # coaxial cylinders at the three obsolete mounting axes. The cylinders are
    # bounded by the heatsink's original front/rear planes.
    fill_radius = entry_radius + 0.20
    for g in small_groups:
        filler = cq.Solid.makeCylinder(
            fill_radius,
            hb.ylen,
            cq.Vector(g["x"], hb.ymin, g["z"]),
            cq.Vector(0, 1, 0),
        )
        edited = edited.fuse(filler)

    # Cut four rear mounting bores. Preserve a blind mounting depth typical of
    # the source rear threaded ports, and reproduce the visible entry relief.
    # The depth is constrained to the rear portion of the solid so it cannot
    # intersect front-side fins or unrelated functional geometry.
    hole_depth = min(6.0, 0.55 * hb.ylen)
    chamfer_depth = min(0.7, max(0.25, entry_radius - bore_radius + 0.25))
    new_centers = [
        (x_left, z_upper),
        (x_right, z_upper),
        (x_left, z_lower),
        (x_right, z_lower),
    ]

    for x, z in new_centers:
        bore = cq.Solid.makeCylinder(
            bore_radius,
            hole_depth + 0.05,
            cq.Vector(x, rear_y + 0.02, z),
            cq.Vector(0, -1, 0),
        )
        edited = edited.cut(bore)

        if entry_radius > bore_radius + 0.03:
            relief = cq.Solid.makeCone(
                entry_radius,
                bore_radius,
                chamfer_depth + 0.03,
                cq.Vector(x, rear_y + 0.02, z),
                cq.Vector(0, -1, 0),
            )
            edited = edited.cut(relief)

    try:
        edited = edited.clean()
    except Exception:
        pass

    if not edited.isValid():
        raise ValueError("Edited heatsink failed solid validity check")

    print("Edited heatsink valid:", edited.isValid())
    print("Edited heatsink solids:", len(edited.Solids()))
    print("Edited heatsink volume: %.3f" % edited.Volume())

    # Replace only the selected heatsink; preserve every other exploded-model
    # component exactly as imported.
    output_solids = list(solids)
    output_solids[heatsink_index] = edited
    result = cq.Compound.makeCompound(output_solids)
    return cq.Workplane("XY").newObject([result])