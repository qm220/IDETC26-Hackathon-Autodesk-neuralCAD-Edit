def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args.get("input_file", ""))
    shape_wp = cq.importers.importStep(input_file)

    # Extract solids from STEP (expecting: SOLID 0 body + SOLID 1 wheel)
    solids = cq.Workplane(obj=shape_wp.val()).solids().vals()
    if len(solids) < 1:
        raise ValueError("No solids found in imported STEP")

    # Identify main body as the largest-volume solid
    solids_sorted = sorted(solids, key=lambda s: s.Volume(), reverse=True)
    body = solids_sorted[0]
    wheel = solids_sorted[1] if len(solids_sorted) > 1 else None

    body_bb = body.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Solid count: {len(solids_sorted)}")
    print(f"Body bbox: xmin={body_bb.xmin:.3f}, xmax={body_bb.xmax:.3f}, ymin={body_bb.ymin:.3f}, ymax={body_bb.ymax:.3f}, zmin={body_bb.zmin:.3f}, zmax={body_bb.zmax:.3f}")
    if wheel:
        wheel_bb = wheel.BoundingBox()
        print(f"Wheel bbox: xmin={wheel_bb.xmin:.3f}, xmax={wheel_bb.xmax:.3f}, ymin={wheel_bb.ymin:.3f}, ymax={wheel_bb.ymax:.3f}, zmin={wheel_bb.zmin:.3f}, zmax={wheel_bb.zmax:.3f}")
    else:
        wheel_bb = None
        print("No second solid detected (wheel not found). Will only modify body.")

    # --- Parameters (mm) ---
    button_raise = 2.0          # requested height
    gap = 1.0                   # split between buttons
    btn_w = 12.0                # width (left-right) per button
    btn_l = 22.0                # length (front-back) per button
    corner_r = 3.0              # rounded-rectangle footprint corner radius

    # Embed pad into body to guarantee union on curved/freeform top
    embed = 2.0
    pad_thickness = button_raise + embed  # total pad thickness

    # Placement derived from wheel if present
    cx = (body_bb.xmin + body_bb.xmax) / 2.0

    if wheel_bb:
        # Place forward (nose side) of wheel opening: just ahead of wheel ymin
        desired_center_y = wheel_bb.ymin - (btn_l / 2.0 + 2.0)
    else:
        # Fallback: place in front third of the body
        desired_center_y = body_bb.ymin + (body_bb.ymax - body_bb.ymin) * 0.35

    # Clamp within the body bbox in Y
    y_margin = 2.0
    cy = max(body_bb.ymin + btn_l / 2.0 + y_margin, min(desired_center_y, body_bb.ymax - btn_l / 2.0 - y_margin))

    # Button centers in X, symmetric about midplane
    dx = (btn_w / 2.0) + (gap / 2.0)
    left_cx = cx - dx
    right_cx = cx + dx

    # Z positioning: top around body zmax; ensure intersection by embedding
    z_top_ref = body_bb.zmax
    pad_bottom_z = z_top_ref - embed

    def _button_pad(xc, yc):
        # Create a rounded-rectangle pad extruded upward, then positioned to intersect body
        # Sketch fillet gives ergonomic footprint; solid edge fillets soften the top.
        pad = (
            cq.Workplane("XY")
            .center(xc, yc)
            .sketch()
            .rect(btn_w, btn_l)
            .vertices()
            .fillet(corner_r)
            .finalize()
            .extrude(pad_thickness)
            .translate((0, 0, pad_bottom_z))
        )

        # Soften exposed edges for comfort
        # Fillet vertical edges and top perimeter edges
        try:
            pad = pad.edges("|Z").fillet(1.0)
        except Exception as e:
            print(f"Warning: could not fillet vertical edges on pad at x={xc:.2f}, y={yc:.2f}: {e}")
        try:
            pad = pad.faces(">Z").edges().fillet(0.8)
        except Exception as e:
            print(f"Warning: could not fillet top edges on pad at x={xc:.2f}, y={yc:.2f}: {e}")

        return pad

    left_pad = _button_pad(left_cx, cy)
    right_pad = _button_pad(right_cx, cy)

    # Union pads to the body
    body_mod = cq.Workplane(obj=body).union(left_pad).union(right_pad)

    # Return as compound preserving wheel as separate solid if present
    if wheel is not None:
        result = cq.Compound.makeCompound([body_mod.val(), wheel])
    else:
        result = body_mod.val()

    return result
