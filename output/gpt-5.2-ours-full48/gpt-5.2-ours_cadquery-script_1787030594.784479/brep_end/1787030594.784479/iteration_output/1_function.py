def my_cad_function(args):
    import cadquery as cq
    import os

    # ---- Load model ----
    input_file = os.path.expanduser(args.get("input_file", ""))
    shape_wp = cq.importers.importStep(input_file)
    shp = shape_wp.val() if hasattr(shape_wp, "val") else shape_wp

    bb = shp.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {shp.isValid()}")
    print(f"Faces: {len(shp.Faces())}, Solids: {len(shp.Solids())}")
    print(f"BBox xmin/xmax: {bb.xmin:.3f}/{bb.xmax:.3f}")
    print(f"BBox ymin/ymax: {bb.ymin:.3f}/{bb.ymax:.3f}")
    print(f"BBox zmin/zmax: {bb.zmin:.3f}/{bb.zmax:.3f}")
    print(f"BBox center: ({bb.center.x:.3f}, {bb.center.y:.3f}, {bb.center.z:.3f})")

    # ---- Robustly find a large horizontal planar "top tank" face ----
    # Many STEP faces have inconsistent orientation, so don't rely on ">Y".
    # Instead, find planar faces that are nearly constant in Y (thin bbox in Y),
    # then choose the highest-Y among the large ones.
    y_flat_tol = 0.5  # mm
    # area threshold relative to overall size
    ref_area = max(1.0, bb.xlen * bb.zlen)
    min_area = 0.03 * ref_area  # ~3% of top footprint

    candidates = []  # (y, area, face)
    for f in shp.Faces():
        try:
            if hasattr(f, "geomType") and f.geomType() == "PLANE":
                fb = f.BoundingBox()
                if (fb.ymax - fb.ymin) <= y_flat_tol and f.Area() >= min_area:
                    candidates.append((fb.ymax, f.Area(), f))
        except Exception:
            continue

    if candidates:
        # take the highest plane, then largest area within a small y-band
        y_max = max(c[0] for c in candidates)
        near = [c for c in candidates if abs(c[0] - y_max) < 2.0]
        y_top_plane, a_top, f_top = max(near, key=lambda t: t[1])
        fc = f_top.Center()
        cx, cz = fc.x, fc.z
        print(
            f"Top face found: y={y_top_plane:.3f}, area={a_top:.1f}, center=({cx:.3f},{fc.y:.3f},{cz:.3f})"
        )
    else:
        # fallback
        y_top_plane = bb.ymax
        cx, cz = bb.center.x, 0.0
        print("WARNING: No large horizontal planar face found; falling back to bbox.ymax and cz=0.")
        print(f"Fallback top plane: y={y_top_plane:.3f}, (cx,cz)=({cx:.3f},{cz:.3f})")

    # If the chosen cz is suspiciously far from mid-span due to protruding end ports,
    # prefer global z=0 as the stated design intent is centered between fan bays.
    if abs(cz) > 0.15 * bb.zlen:
        print(f"NOTE: cz={cz:.3f} seems offset vs main span; overriding cz -> 0.0")
        cz = 0.0

    print(f"Neck placement: y={y_top_plane:.3f}, cx={cx:.3f}, cz={cz:.3f}")

    # ---- Parameters (mm) ----
    neck_od = 42.0
    neck_id = 32.0
    neck_h = 28.0

    cut_depth_into_tank = 45.0  # deeper to ensure we break into the tank volume

    seat_h = 3.0
    seat_od = 54.0

    # simple bayonet-lug visual approximation
    lug_len = 14.0   # along X
    lug_depth = 8.0  # along Z
    lug_thk = 2.5    # along +Y

    # Cap (simplified separate solid)
    cap_od = 62.0
    cap_h = 25.0
    cap_insert_depth = 16.0
    cap_clearance = 0.7

    # ---- Build workplanes ----
    top_wpl = cq.Workplane("XZ", origin=(0, y_top_plane, 0)).center(cx, cz)

    # 1) Create pouring opening into tank
    cut_tool = top_wpl.circle(neck_id / 2.0).extrude(-cut_depth_into_tank)
    modified = cq.Workplane(obj=shp).cut(cut_tool)

    # 2) Create/standardize filler neck
    neck = top_wpl.circle(neck_od / 2.0).circle(neck_id / 2.0).extrude(neck_h)

    # 3) Add a seal seat / top land (simple ring)
    seat_wpl = cq.Workplane(
        "XZ", origin=(0, y_top_plane + neck_h - seat_h, 0)
    ).center(cx, cz)
    seat = seat_wpl.circle(seat_od / 2.0).circle(neck_od / 2.0).extrude(seat_h)

    # 4) Add two bayonet lugs near neck top
    lug_y = y_top_plane + neck_h - lug_thk
    lugs_wpl = cq.Workplane("XZ", origin=(0, lug_y, 0)).center(cx, cz)
    lug_r = neck_od / 2.0 + lug_depth / 2.0
    lugs = (
        lugs_wpl
        .pushPoints([(0, lug_r), (0, -lug_r)])
        .rect(lug_len, lug_depth)
        .extrude(lug_thk)
    )

    # Union filler features onto radiator
    modified = modified.union(neck).union(seat).union(lugs)

    # ---- Create cap as separate body ----
    cap_y0 = y_top_plane + neck_h - cap_insert_depth
    cap_wpl = cq.Workplane("XZ", origin=(0, cap_y0, 0)).center(cx, cz)
    cap_solid = cap_wpl.circle(cap_od / 2.0).extrude(cap_h)

    inner_id = neck_od + 2.0 * cap_clearance
    inner_cut = cap_wpl.circle(inner_id / 2.0).extrude(cap_insert_depth + 6.0)
    cap_solid = cap_solid.cut(inner_cut)

    # Shallow top recess for visual detail
    recess = (
        cq.Workplane("XZ", origin=(0, cap_y0 + cap_h - 3.0, 0))
        .center(cx, cz)
        .circle((cap_od - 10.0) / 2.0)
        .extrude(3.0)
    )
    cap_solid = cap_solid.cut(recess)

    # ---- Return assembly so cap stays separate ----
    asm = cq.Assembly(name="radiator_with_filler")
    asm.add(modified, name="radiator")
    asm.add(cap_solid, name="cap")

    print("Created filler opening + neck + seat + lugs, and a separate simplified cap.")
    return asm
