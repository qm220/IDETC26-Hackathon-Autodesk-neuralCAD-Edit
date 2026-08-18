def my_cad_function(args):
    import os
    import cadquery as cq

    input_path = os.path.expanduser(args.get("input_file", ""))
    if not input_path or not os.path.exists(input_path):
        raise ValueError(f"Input STEP file not found: {input_path}")

    wp = cq.importers.importStep(input_path)
    base = wp.val()  # Solid

    print("Loaded STEP")
    print(f"  type(base)={type(base)}")
    print(f"  isValid={base.isValid()}")
    print(f"  faces={len(base.Faces())}, edges={len(base.Edges())}")
    bb = base.BoundingBox()
    print(
        f"  bbox: xmin={bb.xmin:.3f} xmax={bb.xmax:.3f} "
        f"ymin={bb.ymin:.3f} ymax={bb.ymax:.3f} zmin={bb.zmin:.3f} zmax={bb.zmax:.3f}"
    )

    # --- Identify the largest all-around outer round (expected R10) via surface types on outer envelope ---
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Torus

    R_BIG = 10.0
    r_tol = 0.35
    env_tol = 0.50

    def touches_outer_xy(face_bb):
        return (
            abs(face_bb.xmax - bb.xmax) < env_tol or
            abs(face_bb.xmin - bb.xmin) < env_tol or
            abs(face_bb.ymax - bb.ymax) < env_tol or
            abs(face_bb.ymin - bb.ymin) < env_tol
        )

    faces_to_remove = []  # TopoDS_Face
    cyl_rs = []
    tor_min_rs = []

    for f in base.Faces():
        fbb = f.BoundingBox()
        if not touches_outer_xy(fbb):
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

    # --- Remove the fillet faces with OCCT defeaturing (robust to wrapper API differences) ---
    defeatured = base
    if faces_to_remove:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing
        from OCP.TopTools import TopTools_ListOfShape

        df = BRepAlgoAPI_Defeaturing()

        # Print methods once for debugging in this environment
        try:
            m = [n for n in dir(df) if ("Face" in n or "Shape" in n or "Build" in n or "Add" in n or "Set" in n)]
            print("BRepAlgoAPI_Defeaturing methods (filtered):", sorted(m))
        except Exception:
            pass

        # Set base shape
        if hasattr(df, "SetShape"):
            df.SetShape(base.wrapped)
        elif hasattr(df, "SetBase"):
            df.SetBase(base.wrapped)
        else:
            # try constructor that takes the shape
            try:
                df = BRepAlgoAPI_Defeaturing(base.wrapped)
            except Exception as e:
                raise RuntimeError(f"Cannot set base shape for defeaturing tool: {e}")

        # Add faces to remove (try several API variants)
        added = False
        if hasattr(df, "AddFace"):
            for fw in faces_to_remove:
                df.AddFace(fw)
            added = True
        elif hasattr(df, "AddFaces"):
            lst = TopTools_ListOfShape()
            for fw in faces_to_remove:
                lst.Append(fw)
            df.AddFaces(lst)
            added = True
        elif hasattr(df, "SetFacesToRemove"):
            lst = TopTools_ListOfShape()
            for fw in faces_to_remove:
                lst.Append(fw)
            df.SetFacesToRemove(lst)
            added = True
        elif hasattr(df, "SetFaces"):
            lst = TopTools_ListOfShape()
            for fw in faces_to_remove:
                lst.Append(fw)
            df.SetFaces(lst)
            added = True

        if not added:
            print("Defeaturing: no supported method found to pass faces-to-remove; skipping removal.")
        else:
            df.Build()
            if hasattr(df, "IsDone") and not df.IsDone():
                print("Defeaturing tool reports IsDone()=False; skipping removal.")
            else:
                out = df.Shape()
                defeatured = cq.Shape.cast(out)
                print("Defeaturing completed")
                print(f"  defeatured valid={defeatured.isValid()} faces={len(defeatured.Faces())} edges={len(defeatured.Edges())}")

    # --- Apply new uniform fillet radius (match the small blends: R2) ---
    R_NEW = 2.0

    bb2 = defeatured.BoundingBox()
    e_env_tol = 0.50
    z_flat_tol = 0.10

    def edge_on_outer_envelope_xy(ebb):
        return (
            abs(ebb.xmax - bb2.xmax) < e_env_tol or
            abs(ebb.xmin - bb2.xmin) < e_env_tol or
            abs(ebb.ymax - bb2.ymax) < e_env_tol or
            abs(ebb.ymin - bb2.ymin) < e_env_tol
        )

    def edge_is_on_broad_face_plane(ebb):
        # broad-face perimeter edges lie nearly at constant Z (or constant thickness axis)
        return abs(ebb.zmax - ebb.zmin) < z_flat_tol

    candidate_edges = []
    for e in defeatured.Edges():
        ebb = e.BoundingBox()
        if not edge_on_outer_envelope_xy(ebb):
            continue
        if not edge_is_on_broad_face_plane(ebb):
            continue
        candidate_edges.append(e)

    print(f"Candidate outer-perimeter edges for new fillet R{R_NEW}: {len(candidate_edges)}")

    result = defeatured
    if candidate_edges:
        try:
            result = defeatured.fillet(R_NEW, candidate_edges)
            print("Applied new fillet successfully")
            print(f"  result valid={result.isValid()} faces={len(result.Faces())} edges={len(result.Edges())}")
        except Exception as e:
            print(f"Fillet operation failed: {e}")
            print("Returning defeatured (or original) for inspection")
            result = defeatured
    else:
        print("No candidate edges found for fillet; returning defeatured (or original).")

    # --- Post-check: report remaining outer-envelope R10 cylindrical/torus-minor surfaces if any ---
    bbR = result.BoundingBox()

    def touches_outer_xy_R(face_bb):
        return (
            abs(face_bb.xmax - bbR.xmax) < env_tol or
            abs(face_bb.xmin - bbR.xmin) < env_tol or
            abs(face_bb.ymax - bbR.ymax) < env_tol or
            abs(face_bb.ymin - bbR.ymin) < env_tol
        )

    cyl10 = 0
    tor10 = 0
    for f in result.Faces():
        fbb = f.BoundingBox()
        if not touches_outer_xy_R(fbb):
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
