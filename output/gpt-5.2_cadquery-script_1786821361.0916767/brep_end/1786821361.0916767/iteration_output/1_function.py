def my_cad_function(args):
    import os
    import math
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

    # Identify "hole edges" robustly: circular, *closed* edges whose adjacent faces include
    # at least one CYLINDER face and at least one PLANE face.
    edge_list = []

    try:
        from OCP.TopExp import TopExp
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
        from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
        from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cylinder, GeomAbs_Plane

        occ_solid = base.wrapped if hasattr(base, "wrapped") else base

        e2f = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors(occ_solid, TopAbs_EDGE, TopAbs_FACE, e2f)

        circ_total = 0
        circ_closed = 0
        cyl_plane_candidates = 0

        for e in base.Edges():
            occ_e = e.wrapped
            try:
                c_ad = BRepAdaptor_Curve(occ_e)
                if c_ad.GetType() != GeomAbs_Circle:
                    continue
                circ_total += 1

                # Full circle check (exclude arcs/partial circles)
                r = float(c_ad.Circle().Radius())
                if r <= 1e-9:
                    continue
                L = float(e.Length())
                circ = 2.0 * math.pi * r
                # Tolerance: allow small modeling errors
                if abs(L - circ) > 0.05:
                    continue
                circ_closed += 1

                if not e2f.Contains(occ_e):
                    continue

                faces = e2f.FindFromKey(occ_e)
                has_cyl = False
                has_plane = False

                it = faces.cbegin()
                while it.More():
                    f = it.Value()
                    s_ad = BRepAdaptor_Surface(f, True)
                    st = s_ad.GetType()
                    if st == GeomAbs_Cylinder:
                        has_cyl = True
                    elif st == GeomAbs_Plane:
                        has_plane = True
                    it.Next()

                if has_cyl and has_plane:
                    cyl_plane_candidates += 1
                    edge_list.append(e)

            except Exception:
                # Skip problematic edges
                continue

        print(f"Circular edges (any): {circ_total}")
        print(f"Circular edges (full circle): {circ_closed}")
        print(f"Hole-edge candidates (cyl+plane): {cyl_plane_candidates}")

    except Exception as e:
        print(f"OCP-based edge classification failed, falling back to CQ selectors: {e}")
        try:
            # Less selective fallback: circle edges on cylindrical faces
            edge_list = cq.Workplane(obj=base).faces("%CYLINDER").edges("%CIRCLE").vals()
            print(f"Fallback selected edges: {len(edge_list)}")
        except Exception as e2:
            print(f"Fallback selection failed: {e2}")
            edge_list = []

    if not edge_list:
        print("No hole edges found to chamfer; returning original model.")
        return cq.Workplane(obj=base)

    # Apply chamfer
    try:
        wp = cq.Workplane(obj=base).newObject(edge_list)
        result = wp.chamfer(0.2)
        print(f"Applied 0.2 mm chamfer to {len(edge_list)} hole edges.")
        return result
    except Exception as e:
        print(f"Chamfer operation failed: {e}")
        # Return unmodified model for inspection
        return cq.Workplane(obj=base)
