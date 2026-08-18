def my_cad_function(args):
    import cadquery as cq
    import os, math

    if "input_file" not in args:
        raise ValueError("args['input_file'] is required for edit tasks")

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shp = model.val() if hasattr(model, "val") else model
    bbox = shp.BoundingBox()

    print(f"Loaded STEP: {input_file}")
    print(f"IsValid: {shp.isValid()}")
    print(
        "BBox: "
        f"xmin={bbox.xmin:.4f}, xmax={bbox.xmax:.4f}, "
        f"ymin={bbox.ymin:.4f}, ymax={bbox.ymax:.4f}, "
        f"zmin={bbox.zmin:.4f}, zmax={bbox.zmax:.4f}"
    )

    # Infer thickness axis as smallest bbox dimension
    lens = {"X": float(bbox.xlen), "Y": float(bbox.ylen), "Z": float(bbox.zlen)}
    thk_axis = min(lens, key=lens.get)
    thk = lens[thk_axis]
    if thk <= 1e-9:
        raise ValueError("Invalid thickness detected")

    # Choose sketch plane & selectors based on thickness axis
    if thk_axis == "Y":
        bottom_sel = "<Y"
        plane = "XZ"  # u=X, v=Z
        u_name, v_name = "x", "z"
        offset_min = float(bbox.ymin)
        axis_vec = (0.0, 1.0, 0.0)
        # in-plane axes: u->X, v->Z
        u_axis = (1.0, 0.0, 0.0)
        v_axis = (0.0, 0.0, 1.0)
    elif thk_axis == "X":
        bottom_sel = "<X"
        plane = "YZ"  # u=Y, v=Z
        u_name, v_name = "y", "z"
        offset_min = float(bbox.xmin)
        axis_vec = (1.0, 0.0, 0.0)
        u_axis = (0.0, 1.0, 0.0)
        v_axis = (0.0, 0.0, 1.0)
    else:  # thk_axis == "Z"
        bottom_sel = "<Z"
        plane = "XY"  # u=X, v=Y
        u_name, v_name = "x", "y"
        offset_min = float(bbox.zmin)
        axis_vec = (0.0, 0.0, 1.0)
        u_axis = (1.0, 0.0, 0.0)
        v_axis = (0.0, 1.0, 0.0)

    print(f"Detected thickness axis: {thk_axis} (thk={thk:.4f}), using sketch plane {plane} and bottom selector {bottom_sel}")

    # Pick a bottom face (largest area) normal to thickness axis
    bottom_faces = model.faces(bottom_sel).vals()
    print(f"Bottom faces ({bottom_sel}) count: {len(bottom_faces)}")
    if not bottom_faces:
        raise ValueError(f"No bottom faces found with selector {bottom_sel}")
    bottom_face = max(bottom_faces, key=lambda f: f.Area())

    # Find circular edge for the ring through-hole on that bottom face.
    # Prefer full circles with radius near 10 mm.
    circ_edges = cq.Workplane(obj=bottom_face).edges("%Circle").vals()
    print(f"Bottom face circle-typed edges found (pre-filter): {len(circ_edges)}")

    hole_edge = None
    best = 1e99
    for e in circ_edges:
        try:
            r = float(e.radius())
            L = float(e.Length())
        except Exception:
            continue
        if not (7.0 <= r <= 13.0):
            continue
        full_ratio = L / (2.0 * math.pi * r) if r > 1e-9 else 0.0
        # Favor nearly full circles
        penalty = 0.0 if full_ratio > 0.85 else 10.0
        score = abs(r - 10.0) + penalty
        if score < best:
            best = score
            hole_edge = e

    if hole_edge is None:
        raise ValueError("Failed to locate the ring through-hole circular edge on the bottom face")

    hole_r = float(hole_edge.radius())
    c = hole_edge.Center()
    cx, cy, cz = float(c.x), float(c.y), float(c.z)
    print(f"Chosen hole reference: r={hole_r:.6f}, center=({cx:.6f}, {cy:.6f}, {cz:.6f}), score={best:.6f}")

    # Map global center -> sketch (u,v)
    u0 = {"x": cx, "y": cy, "z": cz}[u_name]
    v0 = {"x": cx, "y": cy, "z": cz}[v_name]

    # Determine in-plane desired direction for one hex FLAT to be parallel to handle direction.
    # Use major bbox axis as "handle" direction, projected into the sketch plane.
    major_axis = max(lens, key=lens.get)
    if major_axis == thk_axis:
        # if thickness somehow is also major (unlikely), pick second major
        major_axis = sorted(lens.keys(), key=lambda k: lens[k], reverse=True)[1]

    axis_unit = {
        "X": (1.0, 0.0, 0.0),
        "Y": (0.0, 1.0, 0.0),
        "Z": (0.0, 0.0, 1.0),
    }[major_axis]

    def dot(a, b):
        return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

    du = dot(axis_unit, u_axis)
    dv = dot(axis_unit, v_axis)
    if abs(du) + abs(dv) < 1e-9:
        # projection vanished; fall back to another axis
        fallback = "Z" if major_axis != "Z" and thk_axis != "Z" else ("Y" if thk_axis != "Y" else "X")
        axis_unit = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}[fallback]
        du = dot(axis_unit, u_axis)
        dv = dot(axis_unit, v_axis)

    theta = math.atan2(dv, du)  # desired edge direction angle in (u,v)
    ang0 = theta - 2.0 * math.pi / 3.0  # vertex angle so that first edge is aligned with theta

    # -----------------------------
    # 1) Fill existing cylindrical through-hole (REPLACE strategy)
    # IMPORTANT: do NOT overshoot thickness to avoid creating bosses.
    # Slightly oversize radius helps guarantee a clean union with the old hole wall.
    # -----------------------------
    plug_r = hole_r + 0.05
    plug = (
        cq.Workplane(plane)
        .workplane(offset=offset_min)
        .center(u0, v0)
        .circle(plug_r)
        .extrude(thk)
    )

    filled = model.union(plug)

    # -----------------------------
    # 2) Cut an inscribed hex THROUGH ALL (vertices on original hole circle)
    # Cut is allowed to overshoot; it doesn't add material.
    # -----------------------------
    pts = []
    for i in range(6):
        a = ang0 + i * (math.pi / 3.0)
        pts.append((hole_r * math.cos(a), hole_r * math.sin(a)))

    cut_extra = max(2.0, 0.1 * thk)
    hex_prism = (
        cq.Workplane(plane)
        .workplane(offset=offset_min - cut_extra)
        .center(u0, v0)
        .polyline(pts)
        .close()
        .extrude(thk + 2.0 * cut_extra)
    )

    result = filled.cut(hex_prism)

    out = result.val() if hasattr(result, "val") else result
    print(f"Result valid: {out.isValid()}")
    print(f"Result faces: {len(out.Faces())}")

    # Debug validation: check if any full circular edge of radius ~ hole_r remains at the same center on the bottom face.
    # (Should be 0 if cylindrical hole was fully replaced by hex.)
    try:
        new_bottom_face = max(result.faces(bottom_sel).vals(), key=lambda f: f.Area())
        new_circs = cq.Workplane(obj=new_bottom_face).edges("%Circle").vals()
        remain = 0
        for e in new_circs:
            try:
                r = float(e.radius())
                L = float(e.Length())
                cc = e.Center()
            except Exception:
                continue
            if abs(r - hole_r) > 0.15:
                continue
            # center match in 3D
            if (cc.sub(c)).Length > 0.5:
                continue
            full_ratio = L / (2.0 * math.pi * r) if r > 1e-9 else 0.0
            if full_ratio > 0.85:
                remain += 1
        print(f"Remaining bottom-face circular edges at hole center with r~{hole_r:.3f}: {remain}")
    except Exception as ex:
        print(f"Validation check skipped due to: {ex}")

    return result
