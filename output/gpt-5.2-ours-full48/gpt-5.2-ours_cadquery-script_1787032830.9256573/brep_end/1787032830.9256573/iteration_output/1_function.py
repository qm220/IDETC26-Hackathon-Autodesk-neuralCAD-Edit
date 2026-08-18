def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args.get("input_file", ""))
    shape_wp = cq.importers.importStep(input_file)

    # Extract solids from STEP (expecting: SOLID 0 body + SOLID 1 wheel)
    solids = cq.Workplane(obj=shape_wp.val()).solids().vals()
    if len(solids) < 1:
        raise ValueError("No solids found in imported STEP")

    solids_sorted = sorted(solids, key=lambda s: s.Volume(), reverse=True)
    body = solids_sorted[0]
    wheel = solids_sorted[1] if len(solids_sorted) > 1 else None

    body_bb = body.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Solid count: {len(solids_sorted)}")
    print(
        f"Body bbox: xmin={body_bb.xmin:.3f}, xmax={body_bb.xmax:.3f}, "
        f"ymin={body_bb.ymin:.3f}, ymax={body_bb.ymax:.3f}, "
        f"zmin={body_bb.zmin:.3f}, zmax={body_bb.zmax:.3f}"
    )
    if wheel is not None:
        wheel_bb = wheel.BoundingBox()
        print(
            f"Wheel bbox: xmin={wheel_bb.xmin:.3f}, xmax={wheel_bb.xmax:.3f}, "
            f"ymin={wheel_bb.ymin:.3f}, ymax={wheel_bb.ymax:.3f}, "
            f"zmin={wheel_bb.zmin:.3f}, zmax={wheel_bb.zmax:.3f}"
        )
    else:
        wheel_bb = None
        print("No second solid detected (wheel not found). Will only modify body.")

    # --- Parameters (mm) ---
    button_raise = 2.0            # requested height
    gap = 1.0                     # split between buttons (visual/feel)
    top_fillet = 0.8              # comfort fillet on top edge of button
    front_margin = 6.0            # keep some space to the front edge
    wheel_clear = 2.0             # keep-out distance from wheel opening region
    slice_thickness = 6.0         # how much of the top shell we lift (ensures overlap for boolean)

    # Coordinate assumption from planning + bbox: Y is "up" (top shell near ymax)
    y_top = body_bb.ymax

    x_span = body_bb.xmax - body_bb.xmin
    z_span = body_bb.zmax - body_bb.zmin
    cx = 0.5 * (body_bb.xmin + body_bb.xmax)

    # Button sizing: make them proportional to body width; conservative length so they fit before the wheel
    total_btn_band = x_span * 0.78
    btn_w = max(14.0, min(28.0, 0.5 * (total_btn_band - gap)))  # per-button width in X

    default_btn_l = 20.0
    min_btn_l = 10.0

    # Decide which Z end is the "nose" (assume wheel is closer to nose end)
    if wheel_bb is not None:
        dist_to_zmax = abs(body_bb.zmax - wheel_bb.zmax)
        dist_to_zmin = abs(wheel_bb.zmin - body_bb.zmin)
        nose_is_zmax = dist_to_zmax < dist_to_zmin

        if nose_is_zmax:
            available = (body_bb.zmax - front_margin) - (wheel_bb.zmax + wheel_clear)
        else:
            available = (wheel_bb.zmin - wheel_clear) - (body_bb.zmin + front_margin)

        if available <= 0:
            # Fallback: still add very small buttons near nose without guaranteeing full clearance
            print(f"Warning: no available Z space between wheel and nose (available={available:.3f}). Using minimal button length.")
            btn_l = min_btn_l
        else:
            btn_l = max(min_btn_l, min(default_btn_l, available * 0.95))

        if nose_is_zmax:
            zc = (wheel_bb.zmax + wheel_clear) + btn_l / 2.0
            zc = min(zc, body_bb.zmax - front_margin - btn_l / 2.0)
        else:
            zc = (wheel_bb.zmin - wheel_clear) - btn_l / 2.0
            zc = max(zc, body_bb.zmin + front_margin + btn_l / 2.0)
    else:
        # Fallback if no wheel: place near zmax end
        btn_l = default_btn_l
        zc = body_bb.zmax - front_margin - btn_l / 2.0

    # Button centers in X, symmetric about midplane
    dx = (btn_w / 2.0) + (gap / 2.0)
    left_cx = cx - dx
    right_cx = cx + dx

    # Keep within body X extents
    x_side_margin = 3.0
    if left_cx - btn_w / 2.0 < body_bb.xmin + x_side_margin:
        left_cx = body_bb.xmin + x_side_margin + btn_w / 2.0
        right_cx = left_cx + (btn_w + gap)
    if right_cx + btn_w / 2.0 > body_bb.xmax - x_side_margin:
        right_cx = body_bb.xmax - x_side_margin - btn_w / 2.0
        left_cx = right_cx - (btn_w + gap)

    corner_r = max(2.0, min(5.0, min(btn_w, btn_l) * 0.18))

    print(
        f"Button params: raise={button_raise}, btn_w={btn_w:.2f}, btn_l={btn_l:.2f}, gap={gap}, "
        f"centers X=({left_cx:.2f}, {right_cx:.2f}), Z={zc:.2f}, corner_r={corner_r:.2f}"
    )

    def make_button_cap(xc, zc_local):
        # Cutter is a rounded-rectangle prism in XZ, extruded in +Y to cover a top slice
        # Bottom of cutter starts below top surface so intersect captures a thick slice for robust union.
        cutter_h = slice_thickness + 3.0
        cutter = (
            cq.Workplane("XZ")
            .center(xc, zc_local)
            .sketch()
            .rect(btn_w, btn_l)
            .vertices()
            .fillet(corner_r)
            .finalize()
            .extrude(cutter_h)
            .translate((0, y_top - slice_thickness - 1.0, 0))
        )

        # Intersect body with cutter to get the local top slice
        cap = cq.Workplane(obj=body).intersect(cutter).val()

        # Lift by requested button height (Y is up)
        cap_up = cap.translate((0, button_raise, 0))

        # Comfort: fillet top perimeter edges of the raised cap
        try:
            cap_up = cq.Workplane(obj=cap_up).faces(">Y").edges().fillet(top_fillet).val()
        except Exception as e:
            print(f"Warning: could not fillet top edges on button cap at x={xc:.2f}, z={zc_local:.2f}: {e}")

        return cap_up

    left_cap = make_button_cap(left_cx, zc)
    right_cap = make_button_cap(right_cx, zc)

    # Union caps into the body
    body_mod = cq.Workplane(obj=body).union(left_cap).union(right_cap)

    # Return as compound preserving wheel as separate solid if present
    if wheel is not None:
        result = cq.Compound.makeCompound([body_mod.val(), wheel])
    else:
        result = body_mod.val()

    return result
