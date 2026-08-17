def my_cad_function(args):
    import os
    import cadquery as cq

    rib_t = 1.5  # mm (rib thickness)

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
    print(f"Valid: {shp.isValid()}")
    print(f"BBOX center=({cx:.3f},{cy:.3f},{cz:.3f})")
    print(f"BBOX lens x={xlen:.3f} y={ylen:.3f} z={zlen:.3f}")

    # Create two external gusset ribs (1.5mm thick) on the two side faces (Y min and Y max)
    # Triangle is drawn in XZ and extruded along +/-Y.
    eps = 0.20          # small overlap to guarantee boolean union
    inset = 0.05        # start plane slightly inside the side face so the rib overlaps the body

    # Rib footprint/height heuristics
    x0 = bbox.xmin + 0.18 * xlen
    x1 = bbox.xmax - 0.18 * xlen
    xmid = 0.5 * (x0 + x1)

    z_base = bbox.zmin - eps
    rib_h = max(3.5, min(0.55 * zlen, zlen - 0.8))
    z_apex = z_base + rib_h

    pts = [(x0, z_base), (x1, z_base), (xmid, z_apex)]

    print(f"Rib thickness={rib_t}mm")
    print(f"Rib triangle XZ pts: {pts}")

    ribs = []

    # Y-min side (extrude outward, i.e., -Y)
    y_plane_min = bbox.ymin + inset
    rib_min = (
        cq.Workplane("XZ", origin=(0, y_plane_min, 0))
        .polyline(pts)
        .close()
        .extrude(-(rib_t + eps))
    )
    ribs.append(rib_min)
    print(f"Added rib on Y-min at y={y_plane_min:.3f}, extrude {-(rib_t + eps):.3f} along Y")

    # Y-max side (extrude outward, i.e., +Y)
    y_plane_max = bbox.ymax - inset
    rib_max = (
        cq.Workplane("XZ", origin=(0, y_plane_max, 0))
        .polyline(pts)
        .close()
        .extrude((rib_t + eps))
    )
    ribs.append(rib_max)
    print(f"Added rib on Y-max at y={y_plane_max:.3f}, extrude {(rib_t + eps):.3f} along Y")

    rib_solid = ribs[0].union(ribs[1])

    try:
        result = cq.Workplane(obj=shp).union(rib_solid)
    except Exception as e:
        print("Union via Workplane(obj=shp) failed; trying model.union. Error:", e)
        result = model.union(rib_solid)

    print("Done: added 1.5mm ribs for reinforcement.")
    return result
