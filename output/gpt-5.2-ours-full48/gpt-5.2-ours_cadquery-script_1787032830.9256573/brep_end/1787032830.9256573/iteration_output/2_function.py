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

    # ---------------- Parameters (mm) ----------------
    button_raise = 2.0          # requested button height above surrounding top
    embed = 1.0                 # how much to sink the button into the shell to guarantee boolean intersection
    gap = 1.0                   # separation between left/right buttons

    side_margin = 8.0           # keep button away from body sides
    front_margin = 6.0          # keep button away from nose end
    wheel_clear = 2.0           # keep-out distance from wheel region in Z

    draft_shrink = 1.2          # shrink top footprint vs bottom to create sloped sides (comfort)
    top_edge_fillet = 0.6       # soften the top perimeter

    # Axis assumption (based on bbox proportions + planning stage): Y is vertical (top near ymax), Z is length, X is width
    y_top = body_bb.ymax
    x_span = body_bb.xmax - body_bb.xmin
    z_span = body_bb.zmax - body_bb.zmin
    cx = 0.5 * (body_bb.xmin + body_bb.xmax)

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    # ---------------- Button sizing ----------------
    # Width: fit within body width with side margins and the center gap
    x_available = x_span - 2.0 * side_margin - gap
    btn_w = clamp(x_available / 2.0, 16.0, 28.0)

    # Length: based on available Z space between wheel and nose
    if wheel_bb is not None:
        # Decide which Z end is the "nose" (wheel usually closer to nose)
        dist_to_zmax = abs(body_bb.zmax - wheel_bb.zmax)
        dist_to_zmin = abs(wheel_bb.zmin - body_bb.zmin)
        nose_is_zmax = dist_to_zmax < dist_to_zmin

        if nose_is_zmax:
            available = (body_bb.zmax - front_margin) - (wheel_bb.zmax + wheel_clear)
        else:
            available = (wheel_bb.zmin - wheel_clear) - (body_bb.zmin + front_margin)

        if available <= 5.0:
            print(f"Warning: limited Z space between wheel and nose (available={available:.3f}). Using conservative button length.")
            btn_l = 16.0
        else:
            btn_l = clamp(available * 0.75, 16.0, 26.0)

        if nose_is_zmax:
            zc = (wheel_bb.zmax + wheel_clear) + btn_l / 2.0
            zc = min(zc, body_bb.zmax - front_margin - btn_l / 2.0)
        else:
            zc = (wheel_bb.zmin - wheel_clear) - btn_l / 2.0
            zc = max(zc, body_bb.zmin + front_margin + btn_l / 2.0)
    else:
        # Fallback if no wheel: place near zmax end
        btn_l = 22.0
        zc = body_bb.zmax - front_margin - btn_l / 2.0

    # Centers in X, symmetric about midplane
    dx = (btn_w / 2.0) + (gap / 2.0)
    left_cx = cx - dx
    right_cx = cx + dx

    # Final sanity to keep within X bounds
    left_cx = clamp(left_cx, body_bb.xmin + side_margin + btn_w / 2.0, body_bb.xmax - side_margin - btn_w / 2.0)
    right_cx = clamp(right_cx, body_bb.xmin + side_margin + btn_w / 2.0, body_bb.xmax - side_margin - btn_w / 2.0)

    # If clamping collapsed the gap too much, re-derive from left
    if right_cx - left_cx < (btn_w + gap) * 0.95:
        left_cx = cx - dx
        right_cx = cx + dx
        # clamp pair as a rigid set
        min_left = body_bb.xmin + side_margin + btn_w / 2.0
        max_right = body_bb.xmax - side_margin - btn_w / 2.0
        shift = 0.0
        if left_cx < min_left:
            shift = min_left - left_cx
        if right_cx > max_right:
            shift = min(shift, max_right - right_cx) if shift != 0.0 else (max_right - right_cx)
        left_cx += shift
        right_cx += shift

    corner_r_bot = clamp(min(btn_w, btn_l) * 0.18, 2.0, 5.0)

    print(
        f"Button params: raise={button_raise:.2f}, embed={embed:.2f}, btn_w={btn_w:.2f}, btn_l={btn_l:.2f}, gap={gap:.2f}, "
        f"X centers=({left_cx:.2f}, {right_cx:.2f}), Z center={zc:.2f}, r_bot={corner_r_bot:.2f}"
    )

    def make_button_mound(xc, zc_local):
        total_h = button_raise + embed
        y0 = y_top - embed

        top_w = max(6.0, btn_w - 2.0 * draft_shrink)
        top_l = max(6.0, btn_l - 2.0 * draft_shrink)
        corner_r_top = clamp(corner_r_bot - draft_shrink * 0.6, 1.0, corner_r_bot)

        # Lofted mound: bottom footprint slightly larger, top footprint slightly smaller
        mound = (
            cq.Workplane("XZ")
            .workplane(offset=y0)
            .center(xc, zc_local)
            .rect(btn_w, btn_l)
            .vertices()
            .fillet(corner_r_bot)
            .workplane(offset=total_h)
            .rect(top_w, top_l)
            .vertices()
            .fillet(corner_r_top)
            .loft(combine=True)
        )

        # Comfort: soften top perimeter (may fail on some lofts; keep robust)
        try:
            mound = mound.faces(">Y").edges().fillet(top_edge_fillet)
        except Exception as e:
            print(f"Warning: top fillet failed at xc={xc:.2f}, zc={zc_local:.2f}: {e}")

        return mound.val()

    left_btn = make_button_mound(left_cx, zc)
    right_btn = make_button_mound(right_cx, zc)

    # Union into body
    body_mod = cq.Workplane(obj=body).union(left_btn).union(right_btn)

    # Preserve wheel as separate solid if present
    if wheel is not None:
        result = cq.Compound.makeCompound([body_mod.val(), wheel])
    else:
        result = body_mod.val()

    return result
