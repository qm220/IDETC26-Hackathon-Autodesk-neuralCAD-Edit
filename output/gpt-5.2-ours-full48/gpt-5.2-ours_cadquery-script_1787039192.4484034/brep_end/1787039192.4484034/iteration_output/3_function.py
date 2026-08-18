def my_cad_function(args):
    import os
    import cadquery as cq

    input_path = os.path.expanduser(args.get("input_file", ""))
    if not input_path or not os.path.exists(input_path):
        raise ValueError(f"Input STEP file not found: {input_path}")

    wp = cq.importers.importStep(input_path)
    base = wp.val()

    print("Loaded STEP")
    print(f"  valid={base.isValid()} faces={len(base.Faces())} edges={len(base.Edges())}")
    bb = base.BoundingBox()
    dx, dy, dz = (bb.xmax - bb.xmin), (bb.ymax - bb.ymin), (bb.zmax - bb.zmin)
    print(
        f"  bbox: xmin={bb.xmin:.3f} xmax={bb.xmax:.3f} (dx={dx:.3f})  "
        f"ymin={bb.ymin:.3f} ymax={bb.ymax:.3f} (dy={dy:.3f})  "
        f"zmin={bb.zmin:.3f} zmax={bb.zmax:.3f} (dz={dz:.3f})"
    )

    # -----------------------
    # Parameters
    # -----------------------
    R_OLD = 10.0
    R_NEW = 2.0
    r_tol = 0.35
    env_tol = 0.75  # outer-perimeter proximity in in-plane directions
    face_extreme_tol = 1.0  # how close the broad faces are to bbox extremes along thickness axis

    # Determine thickness axis as the smallest bbox dimension
    dims = {"X": dx, "Y": dy, "Z": dz}
    thickness_axis = min(dims, key=dims.get)
    print(f"Thickness axis inferred from bbox: {thickness_axis} (dims={dims})")

    # -----------------------
    # Helpers
    # -----------------------
    from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Plane

    def count_r10_faces(shape: cq.Shape):
        cyl10 = 0
        tor10 = 0
        all_cyl = []
        all_tor = []
        for f in shape.Faces():
            ad = BRepAdaptor_Surface(f.wrapped, True)
            st = ad.GetType()
            if st == GeomAbs_Cylinder:
                r = float(ad.Cylinder().Radius())
                all_cyl.append(r)
                if abs(r - R_OLD) <= r_tol:
                    cyl10 += 1
            elif st == GeomAbs_Torus:
                minor = float(ad.Torus().MinorRadius())
                all_tor.append(minor)
                if abs(minor - R_OLD) <= r_tol:
                    tor10 += 1
        all_cyl = sorted(all_cyl)
        all_tor = sorted(all_tor)
        def _summ(rs):
            if not rs:
                return "n=0"
            return f"n={len(rs)} min/med/max={rs[0]:.3f}/{rs[len(rs)//2]:.3f}/{rs[-1]:.3f}"
        return cyl10, tor10, _summ(all_cyl), _summ(all_tor)

    def is_outer_perimeter_point(p, bb, thickness_axis):
        # Check if point is near bbox extremes in the in-plane axes (axes not equal to thickness)
        x, y, z = float(p.X()), float(p.Y()), float(p.Z())
        if thickness_axis == "X":
            return (
                abs(y - bb.ymin) < env_tol or abs(y - bb.ymax) < env_tol or
                abs(z - bb.zmin) < env_tol or abs(z - bb.zmax) < env_tol
            )
        if thickness_axis == "Y":
            return (
                abs(x - bb.xmin) < env_tol or abs(x - bb.xmax) < env_tol or
                abs(z - bb.zmin) < env_tol or abs(z - bb.zmax) < env_tol
            )
        # thickness_axis == "Z"
        return (
            abs(x - bb.xmin) < env_tol or abs(x - bb.xmax) < env_tol or
            abs(y - bb.ymin) < env_tol or abs(y - bb.ymax) < env_tol
        )

    def face_center_coord_along(face: cq.Face, axis: str):
        c = face.Center()
        if axis == "X":
            return float(c.x)
        if axis == "Y":
            return float(c.y)
        return float(c.z)

    def bbox_minmax_along(bb, axis: str):
        if axis == "X":
            return bb.xmin, bb.xmax
        if axis == "Y":
            return bb.ymin, bb.ymax
        return bb.zmin, bb.zmax

    def face_plane_normal(face: cq.Face):
        ad = BRepAdaptor_Surface(face.wrapped, True)
        if ad.GetType() != GeomAbs_Plane:
            return None
        # gp_Pln -> Axis().Direction() is plane normal
        d = ad.Plane().Axis().Direction()
        return (float(d.X()), float(d.Y()), float(d.Z()))

    def aligned_with_axis(n, axis: str, cos_tol=0.95):
        if n is None:
            return False
        nx, ny, nz = n
        if axis == "X":
            return abs(nx) >= cos_tol
        if axis == "Y":
            return abs(ny) >= cos_tol
        return abs(nz) >= cos_tol

    # -----------------------
    # 1) Remove the all-around R10 fillet faces (cylinder R10 + torus minor R10)
    # -----------------------
    cyl10, tor10, cyl_summ, tor_summ = count_r10_faces(base)
    print("Initial surface radii summary:")
    print("  cylinders:", cyl_summ)
    print("  torus minor:", tor_summ)
    print(f"  R~{R_OLD} faces detected: cylinders={cyl10}, torus(minor)={tor10}")

    current = base

    # Multi-pass defeaturing (some kernels remove only a subset per pass)
    for p in range(3):
        faces_r10 = []  # TopoDS_Face
        for f in current.Faces():
            ad = BRepAdaptor_Surface(f.wrapped, True)
            st = ad.GetType()
            if st == GeomAbs_Cylinder:
                r = float(ad.Cylinder().Radius())
                if abs(r - R_OLD) <= r_tol:
                    faces_r10.append(f.wrapped)
            elif st == GeomAbs_Torus:
                minor = float(ad.Torus().MinorRadius())
                if abs(minor - R_OLD) <= r_tol:
                    faces_r10.append(f.wrapped)

        print(f"Defeaturing pass {p+1}: faces marked for removal={len(faces_r10)}")
        if not faces_r10:
            break

        try:
            from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing
            from OCP.TopTools import TopTools_ListOfShape
            from OCP.ShapeFix import ShapeFix_Shape

            df = BRepAlgoAPI_Defeaturing()
            if hasattr(df, "SetShape"):
                df.SetShape(current.wrapped)
            else:
                df = BRepAlgoAPI_Defeaturing(current.wrapped)

            lst = TopTools_ListOfShape()
            for fw in faces_r10:
                lst.Append(fw)

            added = False
            if hasattr(df, "AddFacesToRemove"):
                try:
                    df.AddFacesToRemove(lst)
                    added = True
                except Exception as e:
                    print("  AddFacesToRemove failed:", e)
            if (not added) and hasattr(df, "AddFaceToRemove"):
                try:
                    for fw in faces_r10:
                        df.AddFaceToRemove(fw)
                    added = True
                except Exception as e:
                    print("  AddFaceToRemove failed:", e)

            if not added:
                print("  Defeaturing API could not add faces-to-remove; aborting removal.")
                break

            # robustness knobs
            try:
                if hasattr(df, "SetFuzzyValue"):
                    df.SetFuzzyValue(1e-4)
                if hasattr(df, "SetUseOBB"):
                    df.SetUseOBB(True)
            except Exception:
                pass

            df.Build()
            if hasattr(df, "IsDone") and not df.IsDone():
                print("  Defeaturing IsDone()=False; aborting removal.")
                break

            out = df.Shape()
            new_shape = cq.Shape.cast(out)

            # Fix shape after defeaturing
            try:
                fixer = ShapeFix_Shape(new_shape.wrapped)
                fixer.Perform()
                new_shape = cq.Shape.cast(fixer.Shape())
            except Exception as e:
                print("  ShapeFix failed (continuing):", e)

            current = new_shape
            c10, t10, _, _ = count_r10_faces(current)
            print(
                f"  After pass {p+1}: valid={current.isValid()} faces={len(current.Faces())} edges={len(current.Edges())}  "
                f"remaining R~{R_OLD}: cyl={c10}, tor(minor)={t10}"
            )
            if c10 == 0 and t10 == 0:
                break

        except Exception as e:
            print("Defeaturing exception:", e)
            break

    # -----------------------
    # 2) Add uniform R2 fillet around the same outer edge loop (both broad sides)
    # -----------------------
    c10, t10, _, _ = count_r10_faces(current)
    if c10 != 0 or t10 != 0:
        print(
            f"WARNING: R~{R_OLD} surfaces still present after defeaturing (cyl={c10}, tor={t10}). "
            f"Skipping re-fillet so we don't stack fillets on tangent edges."
        )
        return current

    # Identify the two broad outer planar faces: planar faces near min/max bbox along thickness axis
    plane_faces = []
    for f in current.Faces():
        ad = BRepAdaptor_Surface(f.wrapped, True)
        if ad.GetType() != GeomAbs_Plane:
            continue
        n = face_plane_normal(f)
        if not aligned_with_axis(n, thickness_axis, cos_tol=0.95):
            continue
        plane_faces.append(f)

    print(f"Planar faces aligned with thickness axis: {len(plane_faces)}")

    tmin, tmax = bbox_minmax_along(current.BoundingBox(), thickness_axis)
    outer_planes = []
    for f in plane_faces:
        c = face_center_coord_along(f, thickness_axis)
        if abs(c - tmin) < face_extreme_tol or abs(c - tmax) < face_extreme_tol:
            outer_planes.append(f)

    print(f"Outer-most planar faces (candidate broad faces): {len(outer_planes)}")
    if len(outer_planes) < 2:
        print("Could not reliably find the two broad outer faces; returning current for inspection.")
        return current

    # Collect outer-perimeter edges from these outer faces, excluding inner opening edges by bbox test
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer

    edge_set = {}
    edges_to_fillet = []  # TopoDS_Edge

    cbb = current.BoundingBox()

    for fi, f in enumerate(outer_planes):
        exp = TopExp_Explorer(f.wrapped, TopAbs_EDGE)
        while exp.More():
            e = exp.Current()
            exp.Next()

            # dedupe
            try:
                hk = int(e.HashCode(10**9))
            except Exception:
                hk = id(e)
            if hk in edge_set:
                continue

            # midpoint test
            try:
                ac = BRepAdaptor_Curve(e)
                u0, u1 = float(ac.FirstParameter()), float(ac.LastParameter())
                um = 0.5 * (u0 + u1)
                p = ac.Value(um)
            except Exception:
                continue

            if not is_outer_perimeter_point(p, cbb, thickness_axis):
                continue

            edge_set[hk] = True
            edges_to_fillet.append(e)

    print(f"Edges selected for new R{R_NEW} fillet (outer perimeter loop): {len(edges_to_fillet)}")
    if not edges_to_fillet:
        print("No suitable edges found for new fillet; returning current for inspection.")
        return current

    # Apply fillet using OCCT directly for stability
    try:
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

        mk = BRepFilletAPI_MakeFillet(current.wrapped)
        for e in edges_to_fillet:
            mk.Add(R_NEW, e)
        mk.Build()
        if hasattr(mk, "IsDone") and not mk.IsDone():
            print("Fillet tool IsDone()=False; returning current.")
            return current

        result = cq.Shape.cast(mk.Shape())
        print("Applied new fillet")
        print(f"  result valid={result.isValid()} faces={len(result.Faces())} edges={len(result.Edges())}")

        # Post-check: ensure no remaining R10 blends
        c10, t10, cyl_summ2, tor_summ2 = count_r10_faces(result)
        print("Post surface radii summary:")
        print("  cylinders:", cyl_summ2)
        print("  torus minor:", tor_summ2)
        print(f"  remaining R~{R_OLD}: cylinders={c10}, torus(minor)={t10}")

        return result

    except Exception as e:
        print("Fillet exception:", e)
        return current
