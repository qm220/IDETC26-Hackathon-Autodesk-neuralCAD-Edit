def my_cad_function(args):
    import os
    import cadquery as cq

    rib_t = 1.5  # mm

    if "input_file" not in args:
        print("No input_file provided; cannot edit model.")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shp = model.val() if hasattr(model, "val") else model

    bbox = shp.BoundingBox()
    cx, cy, cz = bbox.center.x, bbox.center.y, bbox.center.z
    xlen, ylen, zlen = bbox.xlen, bbox.ylen, bbox.zlen

    print("Loaded STEP:", input_file)
    try:
        print(f"Valid: {shp.isValid()}")
    except Exception:
        pass
    print(f"BBOX center=({cx:.3f},{cy:.3f},{cz:.3f})")
    print(f"BBOX lens x={xlen:.3f} y={ylen:.3f} z={zlen:.3f}")

    # --- Create two external triangular gusset ribs (1.5mm) on Y-min and Y-max sides ---
    # Sketch in XZ, extrude outward along +/-Y so the ribs are clearly visible and increase support.
    eps = 0.20   # small overlap to ensure boolean union
    inset = 0.05 # sketch plane slightly inside the side face

    # Rib footprint (in XZ): keep it central so it doesn't interfere with end features
    rib_len_x = max(5.0, min(0.45 * xlen, xlen - 2.0))
    rib_h_z = max(4.0, min(0.60 * zlen, zlen - 2.0))

    x0 = cx - rib_len_x / 2.0
    x1 = cx + rib_len_x / 2.0
    z0 = bbox.zmin + 0.08 * zlen
    z2 = min(z0 + rib_h_z, bbox.zmax - 0.20)

    tri_xz = [(x0, z0), (x1, z0), (cx, z2)]
    print(f"Rib thickness={rib_t}mm")
    print(f"Rib triangle XZ pts: {tri_xz}")

    ribs = []

    # Y-min rib (extrude outward -> -Y)
    y_plane_min = bbox.ymin + inset
    rib_min = (
        cq.Workplane("XZ", origin=(0, y_plane_min, 0))
        .polyline(tri_xz)
        .close()
        .extrude(-(rib_t + eps))
    )
    ribs.append(rib_min)
    print(f"Added rib at Y-min (y={y_plane_min:.3f}), extrude {-(rib_t + eps):.3f} along Y")

    # Y-max rib (extrude outward -> +Y)
    y_plane_max = bbox.ymax - inset
    rib_max = (
        cq.Workplane("XZ", origin=(0, y_plane_max, 0))
        .polyline(tri_xz)
        .close()
        .extrude((rib_t + eps))
    )
    ribs.append(rib_max)
    print(f"Added rib at Y-max (y={y_plane_max:.3f}), extrude {(rib_t + eps):.3f} along Y")

    rib_solid = ribs[0].union(ribs[1])

    # Union to the original model
    try:
        result = cq.Workplane(obj=shp).union(rib_solid)
    except Exception as e:
        print("Union via Workplane(obj=shp) failed; trying model.union. Error:", e)
        result = model.union(rib_solid)

    # Debug: verify bbox change (should grow in Y) and volume delta
    try:
        res_shape = result.val() if hasattr(result, "val") else result
        rb = res_shape.BoundingBox()
        print(f"New BBOX lens x={rb.xlen:.3f} y={rb.ylen:.3f} z={rb.zlen:.3f}")
        print(f"Y range before: [{bbox.ymin:.3f},{bbox.ymax:.3f}] after: [{rb.ymin:.3f},{rb.ymax:.3f}]")
        print(f"Volume before: {shp.Volume():.3f} mm^3")
        print(f"Volume after : {res_shape.Volume():.3f} mm^3")
        print(f"Delta volume : {res_shape.Volume()-shp.Volume():.3f} mm^3")
    except Exception as e:
        print("Post-union analysis failed:", e)

    print("Done: added 1.5mm reinforcement ribs.")
    return result
