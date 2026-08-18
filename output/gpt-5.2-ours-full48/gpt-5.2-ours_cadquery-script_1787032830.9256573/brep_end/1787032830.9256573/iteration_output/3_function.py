def my_cad_function(args):
    import cadquery as cq
    import os
    from cadquery import selectors as sel

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
    button_raise = 2.0          # requested height above surrounding
    embed = 6.0                 # sink into body to guarantee boolean intersection (robust)
    gap = 1.0                   # separation between left/right buttons

    side_margin = 8.0           # keep away from outer sides
    front_margin = 6.0          # keep away from nose
    wheel_clear = 3.0           # keep-out distance from wheel region along Z

    draft_shrink = 1.2          # shrink top footprint vs bottom for softer sides
    top_edge_fillet = 0.6       # soften the top perimeter of each button mound
    base_edge_fillet = 1.0      # try to soften the button-to-shell intersection (best-effort)

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    # Axis assumption: Y is vertical, Z is length, X is width
    y_top = body_bb.ymax
    x_span = body_bb.xmax - body_bb.xmin
    z_span = body_bb.zmax - body_bb.zmin
    cx = 0.5 * (body_bb.xmin + body_bb.xmax)

    # ---------------- Button placement (forward/nose of wheel) ----------------
    if wheel_bb is not None:
        dist_to_zmax = abs(body_bb.zmax - wheel_bb.zmax)
        dist_to_zmin = abs(wheel_bb.zmin - body_bb.zmin)
        nose_is_zmax = dist_to_zmax < dist_to_zmin

        if nose_is_zmax:
            z_front_limit = body_bb.zmax - front_margin
            z_wheel_limit = wheel_bb.zmax + wheel_clear
            available = z_front_limit - z_wheel_limit
            if available < 8.0:
                print(f"Warning: limited Z space in front of wheel (available={available:.3f}). Using conservative placement.")
                btn_l = 16.0
                zc = clamp(wheel_bb.zmax + wheel_clear + btn_l / 2.0, body_bb.zmin, z_front_limit - btn_l / 2.0)
            else:
                btn_l = clamp(available * 0.70, 16.0, 26.0)
                zc = z_wheel_limit + btn_l / 2.0
                zc = min(zc, z_front_limit - btn_l / 2.0)
        else:
            z_front_limit = body_bb.zmin + front_margin
            z_wheel_limit = wheel_bb.zmin - wheel_clear
            available = z_wheel_limit - z_front_limit
            if available < 8.0:
                print(f"Warning: limited Z space in front of wheel (available={available:.3f}). Using conservative placement.")
                btn_l = 16.0
                zc = clamp(wheel_bb.zmin - wheel_clear - btn_l / 2.0, z_front_limit + btn_l / 2.0, body_bb.zmax)
            else:
                btn_l = clamp(available * 0.70, 16.0, 26.0)
                zc = z_wheel_limit - btn_l / 2.0
                zc = max(zc, z_front_limit + btn_l / 2.0)
    else:
        # Fallback placement near zmax end
        btn_l = 22.0
        zc = body_bb.zmax - front_margin - btn_l / 2.0

    # ---------------- Button sizing in X ----------------
    x_available = x_span - 2.0 * side_margin - gap
    btn_w = clamp(x_available / 2.0, 18.0, 28.0)

    # Centers in X, symmetric about midplane
    dx = (btn_w / 2.0) + (gap / 2.0)
    left_cx = cx - dx
    right_cx = cx + dx

    # Keep within side margins (rigid shift if needed)
    min_left = body_bb.xmin + side_margin + btn_w / 2.0
    max_right = body_bb.xmax - side_margin - btn_w / 2.0
    shift = 0.0
    if left_cx < min_left:
        shift = min_left - left_cx
    if right_cx > max_right:
        shift2 = max_right - right_cx
        shift = shift2 if shift == 0.0 else min(shift, shift2)
    left_cx += shift
    right_cx += shift

    # Rounded-rectangle corner radii
    r_bot = clamp(min(btn_w, btn_l) * 0.22, 2.0, 6.0)

    print(
        f"Button params: raise={button_raise:.2f}, embed={embed:.2f}, btn_w={btn_w:.2f}, btn_l={btn_l:.2f}, gap={gap:.2f}, "
        f"X centers=({left_cx:.2f}, {right_cx:.2f}), Z center={zc:.2f}, r_bot={r_bot:.2f}"
    )

    def make_button_mound(xc_local):
        # Create a lofted rounded-rectangle mound on XZ plane (normal is +Y)
        y0 = y_top - embed
        total_h = embed + button_raise

        top_w = max(6.0, btn_w - 2.0 * draft_shrink)
        top_l = max(6.0, btn_l - 2.0 * draft_shrink)
        r_top = clamp(r_bot - 0.6 * draft_shrink, 1.0, r_bot)

        wp = cq.Workplane("XZ").workplane(offset=y0).center(xc_local, zc)

        # Use Sketch fillet (2D) to avoid the previous "Cannot find a solid" error
        wp = wp.sketch().rect(btn_w, btn_l).vertices().fillet(r_bot).finalize()
        wp = wp.workplane(offset=total_h)
        wp = wp.sketch().rect(top_w, top_l).vertices().fillet(r_top).finalize()

        mound = wp.loft(combine=True)

        # Soften top perimeter (best-effort)
        try:
            mound = mound.faces(">Y").edges().fillet(top_edge_fillet)
        except Exception as e:
            print(f"Warning: top-edge fillet failed for mound at xc={xc_local:.2f}: {e}")

        return mound.val()

    left_btn = make_button_mound(left_cx)
    right_btn = make_button_mound(right_cx)

    # Union into body
    body_mod = cq.Workplane(obj=body).union(left_btn).union(right_btn)

    # Best-effort: soften intersection edges around each button region using bounding boxes
    def fillet_region(wp, xc_local):
        try:
            x0 = xc_local - btn_w / 2.0 - 4.0
            x1 = xc_local + btn_w / 2.0 + 4.0
            z0 = zc - btn_l / 2.0 - 4.0
            z1 = zc + btn_l / 2.0 + 4.0
            y0 = y_top - embed - 20.0
            y1 = y_top + button_raise + 10.0
            wp2 = wp.edges(sel.BoxSelector(cq.Vector(x0, y0, z0), cq.Vector(x1, y1, z1))).fillet(base_edge_fillet)
            return wp2
        except Exception as e:
            print(f"Warning: base/intersection fillet failed near xc={xc_local:.2f}: {e}")
            return wp

    body_mod = fillet_region(body_mod, left_cx)
    body_mod = fillet_region(body_mod, right_cx)

    # Preserve wheel as separate solid if present
    if wheel is not None:
        result = cq.Compound.makeCompound([body_mod.val(), wheel])
    else:
        result = body_mod.val()

    return result
