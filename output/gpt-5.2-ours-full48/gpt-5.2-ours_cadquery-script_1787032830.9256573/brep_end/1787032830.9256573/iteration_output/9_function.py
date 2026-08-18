def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args.get("input_file", ""))
    shape = cq.importers.importStep(input_file)

    solids = cq.Workplane(obj=shape.val()).solids().vals()
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

    # ---------------- Parameters (mm) ----------------
    button_raise = 2.0          # REQUIRED height
    embed = 4.0                 # ensures pad intersects body for reliable union
    gap = 1.0                   # split between L/R buttons

    side_margin = 8.0           # keep away from extreme sides
    front_margin = 6.0          # keep away from nose tip
    wheel_clear_z = 3.0         # keep rear of buttons away from wheel opening region

    desired_btn_l = 12.0        # will be clamped to available space
    min_btn_l = 8.0

    # edge comfort
    perim_corner_fillet = None  # computed from size
    top_edge_fillet = 0.8

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    # Assume: X=width, Y=up, Z=length (matches bbox: Y is small span)
    cx = 0.5 * (body_bb.xmin + body_bb.xmax)
    x_span = body_bb.xmax - body_bb.xmin

    # Button width in X (symmetric with center gap)
    x_available = x_span - 2.0 * side_margin - gap
    btn_w = clamp(x_available / 2.0, 14.0, 30.0)
    dx = (btn_w / 2.0) + (gap / 2.0)
    left_cx = cx - dx
    right_cx = cx + dx

    # Clamp centers to stay within side margins
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

    # ---------------- Robust local-top probe via intersection ----------------
    def probe_intersection_bbox(xc_local, zc_local, probe_r=2.0):
        """Return BoundingBox of body ∩ (vertical cylinder at XZ=(xc,zc)), or None if no hit."""
        y_start = body_bb.ymin - 60.0
        y_len = (body_bb.ymax - body_bb.ymin) + 120.0
        probe = (
            cq.Workplane("XZ")
            .transformed(offset=(0, y_start, 0))
            .center(xc_local, zc_local)
            .circle(probe_r)
            .extrude(y_len)
        )
        inter = cq.Workplane(obj=body).intersect(probe)
        inter_solids = inter.solids().vals()
        if not inter_solids:
            return None
        inter_solids = sorted(inter_solids, key=lambda s: s.Volume(), reverse=True)
        return inter_solids[0].BoundingBox()

    def local_top_y(xc_local, zc_local):
        bb = probe_intersection_bbox(xc_local, zc_local, probe_r=2.0)
        if bb is None:
            return None
        return bb.ymax

    def point_hits_body(xc_local, zc_local):
        return probe_intersection_bbox(xc_local, zc_local, probe_r=2.5) is not None

    # ---------------- Choose button Z location (forward of wheel opening) ----------------
    if wheel_bb is not None:
        dist_to_zmax = abs(body_bb.zmax - wheel_bb.zmax)
        dist_to_zmin = abs(wheel_bb.zmin - body_bb.zmin)
        nose_is_zmax = dist_to_zmax < dist_to_zmin
        direction = 1.0 if nose_is_zmax else -1.0

        if direction > 0:
            avail = (body_bb.zmax - front_margin) - (wheel_bb.zmax + wheel_clear_z)
        else:
            avail = (wheel_bb.zmin - wheel_clear_z) - (body_bb.zmin + front_margin)

        # Feasible maximum button length given margins/clearance
        max_btn_l = max(4.0, avail)  # can be small; we'll clamp later
        btn_l = clamp(desired_btn_l, min_btn_l, max_btn_l)

        if direction > 0:
            zmin_center = wheel_bb.zmax + wheel_clear_z + btn_l / 2.0
            zmax_center = body_bb.zmax - front_margin - btn_l / 2.0
        else:
            zmax_center = wheel_bb.zmin - wheel_clear_z - btn_l / 2.0
            zmin_center = body_bb.zmin + front_margin + btn_l / 2.0

        # If constraints are tight, clamp center into valid range
        if zmin_center > zmax_center:
            # still try: reduce button length further to minimum and recompute
            btn_l = clamp(btn_l, 4.0, min_btn_l)
            if direction > 0:
                zmin_center = wheel_bb.zmax + wheel_clear_z + btn_l / 2.0
                zmax_center = body_bb.zmax - front_margin - btn_l / 2.0
            else:
                zmax_center = wheel_bb.zmin - wheel_clear_z - btn_l / 2.0
                zmin_center = body_bb.zmin + front_margin + btn_l / 2.0

        zc0 = 0.5 * (zmin_center + zmax_center)

        # Scan around zc0 to ensure both pads land over solid material
        zc = None
        step = 1.5
        for i in range(0, 21):
            for s in (0, 1, -1):
                cand = zc0 + s * i * step
                if cand < body_bb.zmin + btn_l / 2.0 or cand > body_bb.zmax - btn_l / 2.0:
                    continue
                # enforce wheel clearance in Z
                if direction > 0:
                    if (cand - btn_l / 2.0) < (wheel_bb.zmax + wheel_clear_z):
                        continue
                    if (cand + btn_l / 2.0) > (body_bb.zmax - front_margin):
                        continue
                else:
                    if (cand + btn_l / 2.0) > (wheel_bb.zmin - wheel_clear_z):
                        continue
                    if (cand - btn_l / 2.0) < (body_bb.zmin + front_margin):
                        continue

                if point_hits_body(left_cx, cand) and point_hits_body(right_cx, cand):
                    zc = cand
                    break
            if zc is not None:
                break

        if zc is None:
            zc = zc0
            print(f"Warning: could not confirm pad placement over body via probe; using zc0={zc0:.3f}")

    else:
        # No wheel solid available: put buttons near front third
        btn_l = desired_btn_l
        zc = body_bb.zmax - front_margin - btn_l

    # Fillet sizing (3D edges)
    max_r = max(1.0, 0.5 * min(btn_w, btn_l) - 0.2)
    r = clamp(0.22 * min(btn_w, btn_l), 2.0, max_r)
    perim_corner_fillet = r

    print(
        f"Button params: raise={button_raise:.2f}, embed={embed:.2f}, btn_w={btn_w:.2f}, btn_l={btn_l:.2f}, gap={gap:.2f}, "
        f"X centers=({left_cx:.2f}, {right_cx:.2f}), zc={zc:.2f}, perim_r={perim_corner_fillet:.2f}"
    )

    # ---------------- Build pads ----------------
    def make_pad(xc_local):
        y_top = local_top_y(xc_local, zc)
        if y_top is None:
            # fallback: assume near top of bbox
            y_top = body_bb.ymax - 2.0
            print(f"Warning: local_top_y failed at xc={xc_local:.2f}, zc={zc:.2f}. Using y_top={y_top:.2f}")

        y0 = y_top - embed
        h = embed + button_raise

        wp = (
            cq.Workplane("XZ")
            .transformed(offset=(0, y0, 0))
            .center(xc_local, zc)
            .rect(btn_w, btn_l)
            .extrude(h)
        )

        # Round rectangle corners by filleting vertical edges
        try:
            wp = wp.edges("|Y").fillet(perim_corner_fillet)
        except Exception as e:
            print(f"Warning: vertical edge fillet failed at xc={xc_local:.2f}: {e}")

        # Comfort fillet around top edges
        try:
            wp = wp.faces(">Y").edges().fillet(min(top_edge_fillet, max(0.2, perim_corner_fillet * 0.6)))
        except Exception as e:
            print(f"Warning: top edge fillet failed at xc={xc_local:.2f}: {e}")

        return wp.val()

    left_pad = make_pad(left_cx)
    right_pad = make_pad(right_cx)

    # Union into body (pads are embedded for robust intersection)
    body_mod = cq.Workplane(obj=body).union(left_pad).union(right_pad).val()

    # Preserve wheel as separate solid
    if wheel is not None:
        return cq.Compound.makeCompound([body_mod, wheel])
    return body_mod
