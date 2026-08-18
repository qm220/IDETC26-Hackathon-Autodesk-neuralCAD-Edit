def my_cad_function(args):
    import cadquery as cq
    import os

    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit task")

    input_file = os.path.expanduser(args["input_file"])
    wp = cq.importers.importStep(input_file)
    shape = wp.val() if hasattr(wp, "val") else wp

    # Collect solids; if multiple, fuse them into one base
    solids = list(shape.Solids()) if hasattr(shape, "Solids") else []
    if len(solids) == 0:
        base = shape
    else:
        base = solids[0]
        for s in solids[1:]:
            base = base.fuse(s)

    if not hasattr(base, "BoundingBox"):
        raise ValueError("Imported object does not support BoundingBox()")

    bbox = base.BoundingBox()
    Lx = float(bbox.xmax - bbox.xmin)

    print(f"Loaded STEP: {input_file}")
    try:
        print(f"Base is valid: {base.isValid()}")
    except Exception as e:
        print(f"Base validity check failed: {e}")

    print(f"BBOX xmin/xmax: {bbox.xmin:.4f} / {bbox.xmax:.4f}")
    print(f"BBOX ymin/ymax: {bbox.ymin:.4f} / {bbox.ymax:.4f}")
    print(f"BBOX zmin/zmax: {bbox.zmin:.4f} / {bbox.zmax:.4f}")

    # Try to find the square end face (planar face at global xmax)
    tol_x = max(1e-3, 1e-4 * max(Lx, 1.0))
    end_faces = []

    for f in base.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            fbb = f.BoundingBox()
            # A planar end face at x=xmax should have both xmin and xmax ~ global xmax
            if abs(fbb.xmax - bbox.xmax) <= tol_x and abs(fbb.xmin - bbox.xmax) <= tol_x:
                end_faces.append((f.Area(), f, fbb))
        except Exception:
            continue

    print(f"Planar end-face candidates at xmax: {len(end_faces)} (tol_x={tol_x:.6f})")

    if end_faces:
        end_faces.sort(key=lambda t: t[0], reverse=True)
        area, face, fbb = end_faces[0]
        # Prefer face center for plane origin, but be robust to tuple return types
        c_raw = face.Center()
        if isinstance(c_raw, cq.Vector):
            c = c_raw
        else:
            # assume (x,y,z)
            c = cq.Vector(float(c_raw[0]), float(c_raw[1]), float(c_raw[2]))
        x0 = float(c.x)
        print(f"Selected end face area={area:.4f}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f})")
    else:
        # Robust fallback: use the global bbox xmax as the end plane
        x0 = float(bbox.xmax)
        c = cq.Vector(x0, 0.0, 0.0)
        print("No suitable planar face found at xmax; using fallback mirror plane at x=bbox.xmax")

    # Mirror plane: x = x0 (normal along +X). Orientation does not matter for mirror.
    mirror_plane = cq.Plane(origin=c, normal=cq.Vector(1, 0, 0), xDir=cq.Vector(0, 0, 1))

    mirrored = base.mirror(mirror_plane)

    # Union (merge) original + mirrored into one body
    try:
        result = base.fuse(mirrored)
    except Exception:
        # fallback to union if fuse unavailable
        result = base.union(mirrored)

    rb = result.BoundingBox()
    print(f"Result BBOX xmin/xmax: {rb.xmin:.4f} / {rb.xmax:.4f}")
    try:
        print(f"Result valid: {result.isValid()}")
    except Exception as e:
        print(f"Result validity check failed: {e}")

    # Solid count debug
    try:
        rsol = list(result.Solids())
        print(f"Result solids: {len(rsol)}")
    except Exception as e:
        print(f"Result solids count failed: {e}")

    return cq.Workplane(obj=result)
