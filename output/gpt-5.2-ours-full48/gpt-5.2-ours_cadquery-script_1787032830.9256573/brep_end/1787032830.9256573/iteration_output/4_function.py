def my_cad_function(args):
    import cadquery as cq
    import os
    from cadquery import selectors as sel

    input_file = os.path.expanduser(args.get("input_file", ""))
    shape_wp = cq.importers.importStep(input_file)

    # Extract solids (expect SOLID 0 = body, SOLID 1 = wheel)
    solids = cq.Workplane(obj=shape_wp.val()).solids().vals()
    if not solids:
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

    wheel_bb = None
    if wheel is not None:
        wheel_bb = wheel.BoundingBox()
        print(
            f"Wheel bbox: xmin={wheel_bb.xmin:.3f}, xmax={wheel_bb.xmax:.3f}, "
            f"ymin={wheel_bb.ymin:.3f}, ymax={wheel_bb.ymax:.3f}, "
            f"zmin={wheel_bb.zmin:.3f}, zmax={wheel_bb.zmax:.3f}"
        )

    # ---------- Parameters (mm) ----------
    button_raise = 2.0          # required height
    embed = 3.5                 # sinks into body to guarantee union and reduce fragile contact
    gap = 1.0                   # visual/feel split between buttons

    side_margin = 8.0           # keep away from outer side flanks
    front_margin = 6.0          # keep away from nose
    wheel_clear = 3.0           # keep-out from wheel opening region along Z

    draft_shrink = 1.0          # shrink top footprint vs bottom
    top_edge_fillet = 0.6       # comfort edge on top perimeter (best-effort)

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    # Assume: Y up, Z length, X width
    cx = 0.5 * (body_bb.xmin + body_bb.xmax)
    x_span = body_bb.xmax - body_bb.xmin

    # ---------- Determine "front" side and Z placement in front of wheel ----------
    # We place the buttons between the wheel and the nose end.
    if wheel_bb is not None:
        dist_to_zmax = abs(body_bb.zmax - wheel_bb.zmax)
        dist_to_zmin = abs(wheel_bb.zmin - body_bb.zmin)
        nose_is_zmax = dist_to_zmax < dist_to_zmin

        if nose_is_zmax:
            z_front_limit = body_bb.zmax - front_margin
            z_wheel_limit = wheel_bb.zmax + wheel_clear
            available = z_front_limit - z_wheel_limit

            if available <= 0:
                # No space forward of wheel; fallback: put just ahead of wheel with minimal footprint
                btn_l = 10.0
                zc = wheel_bb.zmax + wheel_clear + btn_l / 2.0
                print(f"Warning: no forward Z space (available={available:.3f}). Using fallback zc={zc:.3f}.")
            else:
                # Ensure button length does NOT exceed available space
                btn_l_target = clamp(available * 0.80, 8.0, 22.0)
                btn_l = min(btn_l_target, max(6.0, available - 0.5))
                zc = z_wheel_limit + btn_l / 2.0
        else:
            z_front_limit = body_bb.zmin + front_margin
            z_wheel_limit = wheel_bb.zmin - wheel_clear
            available = z_wheel_limit - z_front_limit

            if available <= 0:
                btn_l = 10.0
                zc = wheel_bb.zmin - wheel_clear - btn_l / 2.0
                print(f"Warning: no forward Z space (available={available:.3f}). Using fallback zc={zc:.3f}.")
            else:
                btn_l_target = clamp(available * 0.80, 8.0, 22.0)
                btn_l = min(btn_l_target, max(6.0, available - 0.5))
                zc = z_wheel_limit - btn_l / 2.0
    else:
        # No wheel detected: place near +Z end
        btn_l = 18.0
        zc = body_bb.zmax - front_margin - btn_l / 2.0

    # ---------- Button sizing in X ----------
    x_available = x_span - 2.0 * side_margin - gap
    btn_w = clamp(x_available / 2.0, 14.0, 28.0)

    dx = (btn_w / 2.0) + (gap / 2.0)
    left_cx = cx - dx
    right_cx = cx + dx

    # Clamp centers so pads stay within margins
    min_left = body_bb.xmin + side_margin + btn_w / 2.0
    max_right = body_bb.xmax - side_margin - btn_w / 2.0
    if left_cx < min_left:
        shift = min_left - left_cx
        left_cx += shift
        right_cx += shift
    if right_cx > max_right:
        shift = max_right - right_cx
        left_cx += shift
        right_cx += shift

    r_bot = clamp(min(btn_w, btn_l) * 0.22, 2.0, 6.0)

    print(
        f"Button params: raise={button_raise:.2f}, embed={embed:.2f}, btn_w={btn_w:.2f}, btn_l={btn_l:.2f}, gap={gap:.2f}, "
        f"X centers=({left_cx:.2f}, {right_cx:.2f}), Z center={zc:.2f}, r_bot={r_bot:.2f}"
    )

    # ---------- Local top height probe (to make ~2mm above local shell, not global ymax) ----------
    def local_top_y(xc_local, zc_local, probe_r=0.35):
        try:
            y_start = body_bb.ymin - 50.0
            y_len = (body_bb.ymax - body_bb.ymin) + 120.0
            probe = (
                cq.Workplane("XZ")
                .workplane(offset=y_start)
                .center(xc_local, zc_local)
                .circle(probe_r)
                .extrude(y_len)
            )
            inter = cq.Workplane(obj=body).intersect(probe)
            # If intersection fails/empty, fall back
            try:
                bb = inter.val().BoundingBox()
                if bb.ymax > -1e9:
                    return bb.ymax
            except Exception:
                pass
        except Exception as e:
            print(f"Warning: local_top_y probe failed at x={xc_local:.2f}, z={zc_local:.2f}: {e}")
        return body_bb.ymax

    # ---------- Build one button mound as a lofted rounded-rectangle (XZ plane, +Y is height) ----------
    def make_button_mound(xc_local):
        y_local = local_top_y(xc_local, zc)
        y0 = y_local - embed
        total_h = embed + button_raise

        top_w = max(6.0, btn_w - 2.0 * draft_shrink)
        top_l = max(6.0, btn_l - 2.0 * draft_shrink)
        r_top = clamp(r_bot - 0.6 * draft_shrink, 1.0, r_bot)

        wp = (
            cq.Workplane("XZ")
            .workplane(offset=y0)
            .center(xc_local, zc)
            .rect(btn_w, btn_l)
            .vertices()
            .fillet(r_bot)
            .workplane(offset=total_h)
            .rect(top_w, top_l)
            .vertices()
            .fillet(r_top)
        )

        mound_wp = wp.loft(combine=False)

        # Soften top perimeter (best-effort)
        try:
            mound_wp = mound_wp.faces(">Y").edges().fillet(top_edge_fillet)
        except Exception as e:
            print(f"Warning: top-edge fillet failed for mound at xc={xc_local:.2f}: {e}")

        return mound_wp

    left_btn = make_button_mound(left_cx)
    right_btn = make_button_mound(right_cx)

    # Union into body
    body_mod = cq.Workplane(obj=body).union(left_btn).union(right_btn)

    # Preserve wheel as separate solid if present
    if wheel is not None:
        result = cq.Compound.makeCompound([body_mod.val(), wheel])
    else:
        result = body_mod.val()

    return result
