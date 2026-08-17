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
    print(f"Valid: {shp.isValid()}")
    print(f"BBOX center=({cx:.3f},{cy:.3f},{cz:.3f})")
    print(f"BBOX lens x={xlen:.3f} y={ylen:.3f} z={zlen:.3f}")

    # --- Find good attachment faces (prefer large planar faces with normals ~ +/-X) ---
    faces = shp.Faces()
    x_pos = []  # (score, area, face, center)
    x_neg = []

    for f in faces:
        try:
            if hasattr(f, "geomType") and f.geomType() != "PLANE":
                continue
            n = f.normalAt()
            a = f.Area()
            c = f.Center()
        except Exception:
            continue

        if abs(n.x) > 0.88 and abs(n.y) < 0.35 and abs(n.z) < 0.35:
            # Prefer faces closer to the model center in X (often inner faces), but keep area as main weight
            clos = abs(c.x - cx)
            score = a / (1.0 + clos)
            if n.x >= 0:
                x_pos.append((score, a, f, c, n))
            else:
                x_neg.append((score, a, f, c, n))

    x_pos.sort(key=lambda t: (t[0], t[1]), reverse=True)
    x_neg.sort(key=lambda t: (t[0], t[1]), reverse=True)

    # Fallback planes if face detection is weak
    x_planes = []
    if x_pos:
        x_planes.append((x_pos[0][3].x, "+X_face", x_pos[0][1]))
    if x_neg:
        x_planes.append((x_neg[0][3].x, "-X_face", x_neg[0][1]))

    if len(x_planes) < 2:
        # ensure two ribs at least
        x_planes = [(bbox.xmin, "bbox_xmin", 0.0), (bbox.xmax, "bbox_xmax", 0.0)]

    print("Selected rib attachment X-planes:")
    for xp, tag, area in x_planes:
        print(f"  {tag}: x={xp:.3f} (area={area:.3f})")

    # --- Rib profile in YZ (triangular gusset), extruded along X by rib_t (both=True for guaranteed overlap) ---
    # Make it substantial but not gigantic
    eps = 0.25  # small overlap helper
    y0 = bbox.ymin + 0.12 * ylen
    y1 = bbox.ymax - 0.12 * ylen
    z0 = bbox.zmin + 0.05 * zlen
    z_apex = bbox.zmin + 0.70 * zlen

    # Keep reasonable bounds
    if y1 - y0 < 1.0:
        y0, y1 = bbox.ymin + 0.2, bbox.ymax - 0.2
    if z_apex - z0 < 1.0:
        z0, z_apex = bbox.zmin + 0.2, bbox.zmax - 0.2

    tri_pts = [(y0, z0), (y1, z0), (cy, z_apex)]
    print(f"Rib thickness={rib_t}mm")
    print(f"Rib YZ triangle pts: {tri_pts}")

    ribs = []
    for xp, tag, _area in x_planes[:2]:
        # Slightly bias the sketch plane inward so both=True extrusion definitely intersects the body
        # (If xp is exactly on a face, this helps avoid a zero-overlap boolean.)
        x_origin = xp
        rib = (
            cq.Workplane("YZ", origin=(x_origin, 0, 0))
            .polyline(tri_pts)
            .close()
            .extrude(rib_t, both=True)
        )
        ribs.append(rib)
        print(f"  Added rib on plane {tag} at x={x_origin:.3f}, extrude both +/-{rib_t/2:.3f} along X")

    rib_solid = ribs[0]
    for r in ribs[1:]:
        rib_solid = rib_solid.union(r)

    # Union ribs to the existing part
    try:
        result = cq.Workplane(obj=shp).union(rib_solid)
    except Exception as e:
        print("Union via Workplane(obj=shp) failed; trying model.union. Error:", e)
        result = model.union(rib_solid)

    print("Done: added 1.5mm thick reinforcement ribs (triangular gussets) attached to +/-X faces.")
    return result
