def my_cad_function(args):
    import os, math
    import cadquery as cq

    if "input_file" not in args:
        print("No input_file provided.")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    base = model.val() if hasattr(model, "val") else model

    print(f"Loaded STEP: {input_file}")
    try:
        print(f"Is Valid: {base.isValid()}")
        print(f"Faces: {len(base.Faces())}, Edges: {len(base.Edges())}, Solids: {len(base.Solids())}")
    except Exception as e:
        print(f"Basic shape stats failed: {e}")

    # --- Find hole mouth edges (circle edges bordering a plane + an INTERNAL cylinder) ---
    targets = []  # list of dicts: {"center": cq.Vector, "r": float}

    try:
        from OCP.TopExp import TopExp_MapShapesAndAncestors
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
        from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
        from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cylinder, GeomAbs_Plane

        occ_shape = base.wrapped if hasattr(base, "wrapped") else base

        e2f = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp_MapShapesAndAncestors(occ_shape, TopAbs_EDGE, TopAbs_FACE, e2f)

        circ_any = 0
        circ_full = 0
        hole_mouth = 0

        for e in base.Edges():
            occ_e = e.wrapped
            try:
                c_ad = BRepAdaptor_Curve(occ_e)
                if c_ad.GetType() != GeomAbs_Circle:
                    continue
                circ_any += 1

                r = float(c_ad.Circle().Radius())
                if r <= 1e-9:
                    continue

                L = float(e.Length())
                if abs(L - 2.0 * math.pi * r) > 0.05:  # full circle check (mm)
                    continue
                circ_full += 1

                if not e2f.Contains(occ_e):
                    continue

                faces = e2f.FindFromKey(occ_e)
                has_plane = False
                has_internal_cyl = False

                # OCP list supports cbegin()/More()/Next() in most builds
                it = faces.cbegin()
                while it.More():
                    f = it.Value()
                    s_ad = BRepAdaptor_Surface(f, True)
                    st = s_ad.GetType()
                    if st == GeomAbs_Plane:
                        has_plane = True
                    elif st == GeomAbs_Cylinder:
                        # internal cylindrical faces of holes are typically REVERSED
                        try:
                            if f.Orientation() == TopAbs_REVERSED:
                                has_internal_cyl = True
                        except Exception:
                            pass
                    it.Next()

                if has_plane and has_internal_cyl:
                    # store target by geometric signature
                    try:
                        c = e.Center()  # for circles this is the circle center
                    except Exception:
                        c = e.CenterOfMass()
                    targets.append({"center": cq.Vector(c.x, c.y, c.z), "r": r})
                    hole_mouth += 1

            except Exception:
                continue

        print(f"Circular edges (any): {circ_any}")
        print(f"Circular edges (full): {circ_full}")
        print(f"Hole-mouth edge candidates (plane + internal cyl): {hole_mouth}")

    except Exception as e:
        print(f"OCP adjacency classification failed: {e}")
        targets = []

    if not targets:
        # Fallback: chamfer full-circle edges only (more conservative than %CYLINDER->%CIRCLE)
        fb = []
        for e in base.Edges():
            try:
                if str(getattr(e, "geomType", lambda: "")()).upper() != "CIRCLE":
                    continue
                r = float(e.radius())
                if r <= 1e-9:
                    continue
                L = float(e.Length())
                if abs(L - 2.0 * math.pi * r) > 0.05:
                    continue
                try:
                    c = e.Center()
                except Exception:
                    c = e.CenterOfMass()
                fb.append({"center": cq.Vector(c.x, c.y, c.z), "r": r})
            except Exception:
                pass
        targets = fb
        print(f"Fallback targets (all full circles): {len(targets)}")

    if not targets:
        print("No hole edges found to chamfer; returning original model.")
        return cq.Workplane(obj=base)

    # --- Apply chamfer: try all-at-once; if it fails, do sequential edge-by-edge ---
    def find_matching_edge(shape, center_vec, r, r_tol=0.02, c_tol=0.5):
        """Find a full-circle edge in 'shape' matching radius and center."""
        best = None
        best_d = 1e99
        for ed in shape.Edges():
            try:
                gt = str(getattr(ed, "geomType", lambda: "")()).upper()
                if gt != "CIRCLE":
                    continue
                rr = float(ed.radius())
                if abs(rr - r) > r_tol:
                    continue
                # full circle check
                if abs(float(ed.Length()) - 2.0 * math.pi * rr) > 0.05:
                    continue
                try:
                    cc = ed.Center()
                except Exception:
                    cc = ed.CenterOfMass()
                cv = cq.Vector(cc.x, cc.y, cc.z)
                d = (cv - center_vec).Length
                if d < best_d and d <= c_tol:
                    best = ed
                    best_d = d
            except Exception:
                continue
        return best

    # Build initial edge objects to attempt all-at-once chamfer
    initial_edges = []
    for t in targets:
        ed = find_matching_edge(base, t["center"], t["r"], r_tol=0.02, c_tol=0.75)
        if ed is not None:
            initial_edges.append(ed)

    print(f"Matched edges in original shape: {len(initial_edges)}")

    # Attempt a single chamfer operation first
    if initial_edges:
        try:
            res = cq.Workplane(obj=base).newObject(initial_edges).chamfer(0.2)
            print(f"Applied 0.2 mm chamfer in one pass on {len(initial_edges)} edges.")
            return res
        except Exception as e:
            print(f"One-pass chamfer failed: {e}")

    # Sequential chamfer (more robust)
    current = base
    success = 0
    for t in targets:
        ed = find_matching_edge(current, t["center"], t["r"], r_tol=0.03, c_tol=1.0)
        if ed is None:
            continue
        try:
            current = cq.Workplane(obj=current).newObject([ed]).chamfer(0.2).val()
            success += 1
        except Exception:
            # skip edges that refuse chamfer
            continue

    print(f"Sequential chamfer successes: {success} / {len(targets)}")
    return cq.Workplane(obj=current)
