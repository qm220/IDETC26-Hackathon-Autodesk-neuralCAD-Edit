def my_cad_function(args):
    import cadquery as cq
    import os

    if "input_file" not in args:
        raise ValueError("Expected args['input_file'] for edit task")

    input_file = os.path.expanduser(args["input_file"])
    wp = cq.importers.importStep(input_file)
    shape = wp.val() if hasattr(wp, "val") else wp

    # If import produced a compound with multiple solids, use the first solid as the base
    solids = list(shape.Solids()) if hasattr(shape, "Solids") else []
    base = solids[0] if len(solids) > 0 else shape

    bbox = base.BoundingBox()
    print(f"Loaded STEP: {input_file}")
    print(f"Base is valid: {base.isValid()}")
    print(f"BBOX xmin/xmax: {bbox.xmin:.4f} / {bbox.xmax:.4f}")
    print(f"BBOX ymin/ymax: {bbox.ymin:.4f} / {bbox.ymax:.4f}")
    print(f"BBOX zmin/zmax: {bbox.zmin:.4f} / {bbox.zmax:.4f}")

    # Find the planar end face at the not-rounded (square) end.
    # Heuristic: planar faces whose center is at x ~= bbox.xmax and whose normal is ~ +/-X.
    tol_x = max(1e-3, 1e-4 * (bbox.xmax - bbox.xmin))
    candidates = []

    for f in base.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
            c = f.Center()
            # normalAt signature can vary; for planar faces any UV works
            try:
                n = f.normalAt(0, 0)
            except Exception:
                # fallback: try at face center param if supported
                n = f.normalAt(c)

            if abs(c.x - bbox.xmax) <= tol_x and abs(n.x) >= 0.9:
                candidates.append((f.Area(), f, c, n))
        except Exception:
            continue

    print(f"Candidate end faces near xmax: {len(candidates)} (tol_x={tol_x:.6f})")

    if not candidates:
        # Fallback: pick the planar face with center.x closest to bbox.xmax
        fallback = []
        for f in base.Faces():
            if f.geomType() != "PLANE":
                continue
            c = f.Center()
            try:
                n = f.normalAt(0, 0)
            except Exception:
                n = cq.Vector(1, 0, 0)
            fallback.append((abs(c.x - bbox.xmax), -f.Area(), f, c, n))
        if not fallback:
            raise ValueError("No planar faces found to define mirror plane")
        fallback.sort(key=lambda t: (t[0], t[1]))
        _, _, face, c, n = fallback[0]
        print("Using fallback planar face selection.")
    else:
        # Choose largest area among candidates at xmax
        candidates.sort(key=lambda t: t[0], reverse=True)
        _, face, c, n = candidates[0]

    print(f"Selected mirror face: center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), normal=({n.x:.4f},{n.y:.4f},{n.z:.4f}), area={face.Area():.4f}")

    # Build mirror plane coincident with the selected end face
    n_unit = cq.Vector(n.x, n.y, n.z).normalized()
    # Pick an xDir not parallel to normal
    xdir_try = cq.Vector(0, 0, 1)
    if abs(n_unit.dot(xdir_try)) > 0.95:
        xdir_try = cq.Vector(0, 1, 0)

    mirror_plane = cq.Plane(origin=c, normal=n_unit, xDir=xdir_try)

    mirrored = base.mirror(mirror_plane)
    result = base.union(mirrored)

    print(f"Result valid: {result.isValid()}")
    print(f"Result solids: {len(list(result.Solids())) if hasattr(result, 'Solids') else 'n/a'}")

    return cq.Workplane(obj=result)
