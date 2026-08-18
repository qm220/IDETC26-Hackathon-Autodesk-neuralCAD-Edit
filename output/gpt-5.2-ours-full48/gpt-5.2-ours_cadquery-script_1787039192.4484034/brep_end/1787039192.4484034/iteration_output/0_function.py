def my_cad_function(args):
    import os, math
    import cadquery as cq

    input_path = os.path.expanduser(args.get("input_file", ""))
    if not input_path or not os.path.exists(input_path):
        raise ValueError(f"Input STEP file not found: {input_path}")

    # --- Load ---
    wp = cq.importers.importStep(input_path)
    base = wp.val()  # expected Solid

    print("Loaded STEP")
    print(f"  type(base)={type(base)}")
    print(f"  isValid={base.isValid()}")
    print(f"  faces={len(base.Faces())}, edges={len(base.Edges())}")

    bb = base.BoundingBox()
    print(f"  bbox: xmin={bb.xmin:.3f} xmax={bb.xmax:.3f} ymin={bb.ymin:.3f} ymax={bb.ymax:.3f} zmin={bb.zmin:.3f} zmax={bb.zmax:.3f}")

    # --- Identify the all-around large fillet faces (likely R10) and remove them via defeaturing ---
    # Strategy:
    # 1) Find faces whose underlying surface is CYLINDER with radius ~10 OR TORUS with minor radius ~10
    # 2) Additionally require that the face lies on the outside envelope (touches outer bbox in X/Y)
    # 3) Use OpenCascade BRepAlgoAPI_Defeaturing to delete/heal those faces

    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Torus
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing

    R_BIG = 10.0
    r_tol = 0.35
    env_tol = 0.50  # mm, for bbox touch test

    def touches_outer_xy(face_bb):
        return (
            abs(face_bb.xmax - bb.xmax) < env_tol or
            abs(face_bb.xmin - bb.xmin) < env_tol or
            abs(face_bb.ymax - bb.ymax) < env_tol or
            abs(face_bb.ymin - bb.ymin) < env_tol
        )

    faces_to_remove = []
    debug_radii = {"cyl": [], "tor_minor": []}

    for f in base.Faces():
        fbb = f.BoundingBox()
        if not touches_outer_xy(fbb):
            continue

        ad = BRepAdaptor_Surface(f.wrapped, True)
        st = ad.GetType()
        if st == GeomAbs_Cylinder:
            r = float(ad.Cylinder().Radius())
            debug_radii["cyl"].append(r)
            if abs(r - R_BIG) <= r_tol:
                faces_to_remove.append(f.wrapped)
        elif st == GeomAbs_Torus:
            tr = ad.Torus()
            minor = float(tr.MinorRadius())
            debug_radii["tor_minor"].append(minor)
            if abs(minor - R_BIG) <= r_tol:
                faces_to_remove.append(f.wrapped)

    print(f"Detected cylinder radii sample (outer-touching): n={len(debug_radii['cyl'])}")
    if debug_radii["cyl"]:
        # print a compact summary
        rs = sorted(debug_radii["cyl"])
        print(f"  cyl r min/med/max = {rs[0]:.3f} / {rs[len(rs)//2]:.3f} / {rs[-1]:.3f}")

    print(f"Detected torus minor radii sample (outer-touching): n={len(debug_radii['tor_minor'])}")
    if debug_radii["tor_minor"]:
        rs = sorted(debug_radii["tor_minor"])
        print(f"  tor minor r min/med/max = {rs[0]:.3f} / {rs[len(rs)//2]:.3f} / {rs[-1]:.3f}")

    print(f"Faces marked for removal (R~{R_BIG} on outer envelope): {len(faces_to_remove)}")

    defeatured_shape_wrapped = None
    if faces_to_remove:
        df = BRepAlgoAPI_Defeaturing()
        if hasattr(df, "SetShape"):
            df.SetShape(base.wrapped)
        elif hasattr(df, "SetBase"):
            df.SetBase(base.wrapped)
        else:
            # Fallback attempt: try constructor with shape
            try:
                df = BRepAlgoAPI_Defeaturing(base.wrapped)
            except Exception as e:
                raise RuntimeError(f"Cannot set base shape for defeaturing tool: {e}")

        if hasattr(df, "AddFace"):
            for fw in faces_to_remove:
                df.AddFace(fw)
        else:
            raise RuntimeError("BRepAlgoAPI_Defeaturing missing AddFace() in this environment")

        df.Build()
        if hasattr(df, "IsDone") and not df.IsDone():
            print("Defeaturing tool reports IsDone()=False; returning original for inspection")
            return base

        defeatured_shape_wrapped = df.Shape()
        defeatured = cq.Shape.cast(defeatured_shape_wrapped)
        print("Defeaturing completed")
        print(f"  defeatured type={type(defeatured)} valid={defeatured.isValid()}")
        print(f"  defeatured faces={len(defeatured.Faces())}, edges={len(defeatured.Edges())}")
    else:
        print("No R10 outer-envelope fillet faces found to remove; will attempt direct fillet selection on current geometry")
        defeatured = base

    # --- Add new uniform fillet radius (match others) ---
    # Interpreting request: set the previously-largest all-around fillet to R2.
    R_NEW = 2.0
    e_env_tol = 0.35
    z_flat_tol = 0.05

    bb2 = defeatured.BoundingBox()

    def edge_on_outer_envelope_xy(ebb):
        return (
            abs(ebb.xmax - bb2.xmax) < e_env_tol or
            abs(ebb.xmin - bb2.xmin) < e_env_tol or
            abs(ebb.ymax - bb2.ymax) < e_env_tol or
            abs(ebb.ymin - bb2.ymin) < e_env_tol
        )

    def edge_is_nearly_planar_in_z(ebb):
        return abs(ebb.zmax - ebb.zmin) < z_flat_tol

    candidate_edges = []
    for e in defeatured.Edges():
        ebb = e.BoundingBox()
        if not edge_on_outer_envelope_xy(ebb):
            continue
        # We expect the target outer loop edges to lie on the two broad faces (constant Z)
        if not edge_is_nearly_planar_in_z(ebb):
            continue
        candidate_edges.append(e)

    print(f"Candidate outer perimeter edges for new fillet R{R_NEW}: {len(candidate_edges)}")

    # Apply fillet
    try:
        result = defeatured.fillet(R_NEW, candidate_edges)
        print("Applied new fillet successfully")
        print(f"  result valid={result.isValid()} faces={len(result.Faces())} edges={len(result.Edges())}")
        return result
    except Exception as e:
        print(f"Fillet operation failed: {e}")
        print("Returning defeatured (or original) shape for inspection")
        return defeatured
