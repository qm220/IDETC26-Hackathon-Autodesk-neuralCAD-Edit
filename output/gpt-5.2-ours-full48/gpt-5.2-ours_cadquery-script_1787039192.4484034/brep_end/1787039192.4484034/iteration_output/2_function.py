def my_cad_function(args):
    import os
    import cadquery as cq

    input_path = os.path.expanduser(args.get("input_file", ""))
    if not input_path or not os.path.exists(input_path):
        raise ValueError(f"Input STEP file not found: {input_path}")

    wp = cq.importers.importStep(input_path)
    base = wp.val()  # Solid

    print("Loaded STEP")
    print(f"  valid={base.isValid()} faces={len(base.Faces())} edges={len(base.Edges())}")
    bb = base.BoundingBox()
    print(
        f"  bbox: xmin={bb.xmin:.3f} xmax={bb.xmax:.3f} "
        f"ymin={bb.ymin:.3f} ymax={bb.ymax:.3f} zmin={bb.zmin:.3f} zmax={bb.zmax:.3f}"
    )

    # --- Identify outer-envelope R10 fillet faces (cylinders and torus minors) ---
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Torus

    R_BIG = 10.0
    r_tol = 0.35
    env_tol = 0.50

    def touches_outer_xy(face_bb, solid_bb):
        return (
            abs(face_bb.xmax - solid_bb.xmax) < env_tol
            or abs(face_bb.xmin - solid_bb.xmin) < env_tol
            or abs(face_bb.ymax - solid_bb.ymax) < env_tol
            or abs(face_bb.ymin - solid_bb.ymin) < env_tol
        )

    faces_to_remove = []  # TopoDS_Face
    cyl_rs = []
    tor_min_rs = []

    for f in base.Faces():
        fbb = f.BoundingBox()
        if not touches_outer_xy(fbb, bb):
            continue

        ad = BRepAdaptor_Surface(f.wrapped, True)
        st = ad.GetType()
        if st == GeomAbs_Cylinder:
            r = float(ad.Cylinder().Radius())
            cyl_rs.append(r)
            if abs(r - R_BIG) <= r_tol:
                faces_to_remove.append(f.wrapped)
        elif st == GeomAbs_Torus:
            t = ad.Torus()
            minor = float(t.MinorRadius())
            tor_min_rs.append(minor)
            if abs(minor - R_BIG) <= r_tol:
                faces_to_remove.append(f.wrapped)

    def _summ(rs):
        rs = sorted(rs)
        if not rs:
            return "n=0"
        return f"n={len(rs)} min/med/max={rs[0]:.3f}/{rs[len(rs)//2]:.3f}/{rs[-1]:.3f}"

    print("Outer-touching cylinder radii:", _summ(cyl_rs))
    print("Outer-touching torus minor radii:", _summ(tor_min_rs))
    print(f"Faces marked for removal (outer-envelope R~{R_BIG}): {len(faces_to_remove)}")

    # --- Remove the R10 fillet faces using OCCT defeaturing ---
    defeatured = base
    if faces_to_remove:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing
        from OCP.TopTools import TopTools_ListOfShape

        df = BRepAlgoAPI_Defeaturing()

        # Debug: show relevant methods to match this environment
        try:
            m = [n for n in dir(df) if ("Face" in n or "Faces" in n or "Shape" in n or "Build" in n or "Add" in n or "Set" in n)]
            print("BRepAlgoAPI_Defeaturing methods (filtered):", sorted(m))
        except Exception:
            pass

        if hasattr(df, "SetShape"):
            df.SetShape(base.wrapped)
        else:
            # fallback to constructor that may take the shape
            try:
                df = BRepAlgoAPI_Defeaturing(base.wrapped)
            except Exception as e:
                raise RuntimeError(f"Cannot set base shape for defeaturing tool: {e}")

        lst = TopTools_ListOfShape()
        for fw in faces_to_remove:
            lst.Append(fw)

        added = False
        # Prefer the methods we saw in last iteration: AddFaceToRemove/AddFacesToRemove
        if hasattr(df, "AddFacesToRemove"):
            try:
                df.AddFacesToRemove(lst)
                added = True
            except Exception as e:
                print("AddFacesToRemove failed:", e)
        if (not added) and hasattr(df, "AddFaceToRemove"):
            try:
                for fw in faces_to_remove:
                    df.AddFaceToRemove(fw)
                added = True
            except Exception as e:
                print("AddFaceToRemove failed:", e)

        if not added:
            print("Defeaturing: could not add faces-to-remove with available API; skipping removal.")
        else:
            try:
                # improve robustness
                if hasattr(df, "SetFuzzyValue"):
                    df.SetFuzzyValue(1e-4)
            except Exception:
                pass

            df.Build()
            if hasattr(df, "IsDone") and not df.IsDone():
                print("Defeaturing tool reports IsDone()=False; skipping removal.")
            else:
                out = df.Shape()
                defeatured = cq.Shape.cast(out)
                print("Defeaturing completed")
                print(f"  defeatured valid={defeatured.isValid()} faces={len(defeatured.Faces())} edges={len(defeatured.Edges())}")

    # --- Apply new uniform fillet radius R2 on the outer perimeter edges of BOTH broad planar faces ---
    R_NEW = 2.0

    # Find the two largest planar faces (the two broad annular faces)
    from OCP.GeomAbs import GeomAbs_Plane

    planar_faces = []
    for f in defeatured.Faces():
        ad = BRepAdaptor_Surface(f.wrapped, True)
        if ad.GetType() == GeomAbs_Plane:
            planar_faces.append((f.Area(), f))

    planar_faces.sort(key=lambda t: t[0], reverse=True)
    print(f"Planar faces found: {len(planar_faces)}")
    if planar_faces:
        print("  top planar areas:", [round(a, 3) for a, _ in planar_faces[:5]])

    broad_faces = [pf for _, pf in planar_faces[:2]]

    # Collect outer-wire edges from those broad faces (outer boundary only, not the inner cutout)
    edge_map = {}
    outer_edges = []
    for i, pf in enumerate(broad_faces):
        try:
            ow = pf.outerWire()
            for e in ow.Edges():
                try:
                    hk = int(e.hashCode())
                except Exception:
                    hk = id(e.wrapped)
                if hk not in edge_map:
                    edge_map[hk] = e
                    outer_edges.append(e)
        except Exception as e:
            print(f"Failed extracting outerWire edges for broad face {i}: {e}")

    print(f"Candidate outer-perimeter sharp edges for new fillet R{R_NEW}: {len(outer_edges)}")

    result = defeatured
    if outer_edges:
        try:
            result = defeatured.fillet(R_NEW, outer_edges)
            print("Applied new fillet successfully")
            print(f"  result valid={result.isValid()} faces={len(result.Faces())} edges={len(result.Edges())}")
        except Exception as e:
            print(f"Fillet operation failed: {e}")
            print("Returning defeatured (or original) for inspection")
            result = defeatured
    else:
        print("No candidate edges found for fillet; returning defeatured (or original).")

    # --- Post-check: count remaining outer-envelope R10 fillet faces ---
    bbR = result.BoundingBox()
    cyl10 = 0
    tor10 = 0
    for f in result.Faces():
        fbb = f.BoundingBox()
        if not touches_outer_xy(fbb, bbR):
            continue
        ad = BRepAdaptor_Surface(f.wrapped, True)
        st = ad.GetType()
        if st == GeomAbs_Cylinder:
            r = float(ad.Cylinder().Radius())
            if abs(r - R_BIG) <= r_tol:
                cyl10 += 1
        elif st == GeomAbs_Torus:
            minor = float(ad.Torus().MinorRadius())
            if abs(minor - R_BIG) <= r_tol:
                tor10 += 1
    print(f"Post-check outer-envelope: cylinder faces with R~10: {cyl10}, torus minor R~10: {tor10}")

    return result
