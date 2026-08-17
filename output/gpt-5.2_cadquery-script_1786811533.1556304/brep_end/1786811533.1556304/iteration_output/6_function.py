def my_cad_function(args):
    import os
    import cadquery as cq

    rib_t = 1.5  # mm (rib thickness)

    if "input_file" not in args:
        print("No input_file provided; cannot edit model.")
        return None

    input_file = os.path.expanduser(args["input_file"])
    wp = cq.importers.importStep(input_file)
    shp = wp.val() if hasattr(wp, "val") else wp

    bb = shp.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    try:
        print(f"Valid: {shp.isValid()}")
    except Exception:
        pass
    print(f"BBOX lens x={bb.xlen:.3f} y={bb.ylen:.3f} z={bb.zlen:.3f}")

    # --- Detect a dominant side face (normal ~ +/-Y) to choose which side to place the rib on ---
    side = None
    side_area = -1.0
    side_c = None

    try:
        faces = shp.Faces()
    except Exception:
        faces = []

    for f in faces:
        try:
            if hasattr(f, "geomType") and f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            a = f.Area()
            c = f.Center()
        except Exception:
            continue

        if abs(n.y) > 0.90 and abs(n.x) < 0.35 and abs(n.z) < 0.35:
            if a > side_area:
                side = f
                side_area = a
                side_c = c

    # Default to Y-min if we can't detect
    if side is None or side_c is None:
        at_ymin = True
        print("WARNING: Could not detect a dominant +/-Y planar side face; using bbox.ymin")
    else:
        at_ymin = abs(side_c.y - bb.ymin) <= abs(side_c.y - bb.ymax)
        print(
            f"Selected side face area={side_area:.3f}, center y={side_c.y:.3f} -> {'ymin' if at_ymin else 'ymax'}"
        )

    # Place rib on the selected side and extrude into the part
    y_attach = bb.ymin if at_ymin else bb.ymax
    y_dir = +1.0 if at_ymin else -1.0  # interior direction from the side face

    # Small inset so the rib definitely intersects the existing body during boolean fuse
    inset = 0.05  # mm
    y_plane = y_attach + y_dir * inset

    # --- Triangular gusset profile on XZ, then extrude along Y by exactly 1.5mm ---
    xlen, ylen, zlen = bb.xlen, bb.ylen, bb.zlen

    x0 = bb.xmin + 0.12 * xlen
    x1 = bb.xmax - 0.12 * xlen
    if x1 <= x0:
        x0, x1 = bb.xmin + 0.5, bb.xmax - 0.5
    xm = 0.5 * (x0 + x1)

    z0 = bb.zmin + 0.06 * zlen
    z2 = min(bb.zmin + 0.78 * zlen, bb.zmax - 0.25)
    if z2 <= z0 + 0.5:
        z0 = bb.zmin + 0.5
        z2 = bb.zmax - 0.5

    tri_xz = [(x0, z0), (x1, z0), (xm, z2)]

    print(f"Rib thickness: {rib_t}mm")
    print(f"Rib placement: y_plane={y_plane:.3f}, extrude {'+Y' if y_dir > 0 else '-Y'}")
    print(f"Rib triangle (XZ): {tri_xz}")

    rib_wp = (
        cq.Workplane("XZ", origin=(0, y_plane, 0))
        .polyline(tri_xz)
        .close()
        .extrude(y_dir * rib_t)
    )
    rib_shape = rib_wp.val()

    # --- Fuse with original using OCC boolean (more reliable than WP union for imported STEP compounds) ---
    try:
        vol0 = shp.Volume()
    except Exception:
        vol0 = None

    try:
        result_shape = shp.fuse(rib_shape)
    except Exception as e:
        print("Fuse failed, falling back to Workplane union. Error:", e)
        result_shape = cq.Workplane(obj=shp).union(rib_wp).val()

    # Debug checks
    try:
        bb2 = result_shape.BoundingBox()
        print(f"New BBOX lens x={bb2.xlen:.3f} y={bb2.ylen:.3f} z={bb2.zlen:.3f}")
        if vol0 is not None:
            vol1 = result_shape.Volume()
            print(f"Volume before: {vol0:.3f} mm^3")
            print(f"Volume after : {vol1:.3f} mm^3")
            print(f"Delta volume : {vol1 - vol0:.3f} mm^3")
    except Exception as e:
        print("Post-boolean analysis failed:", e)

    return result_shape
