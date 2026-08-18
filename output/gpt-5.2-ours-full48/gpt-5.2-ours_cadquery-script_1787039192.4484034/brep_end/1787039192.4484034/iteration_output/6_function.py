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
    bb0 = base.BoundingBox()
    dx0, dy0, dz0 = (bb0.xmax - bb0.xmin), (bb0.ymax - bb0.ymin), (bb0.zmax - bb0.zmin)
    print(
        f"  bbox: xmin={bb0.xmin:.3f} xmax={bb0.xmax:.3f} (dx={dx0:.3f})  "
        f"ymin={bb0.ymin:.3f} ymax={bb0.ymax:.3f} (dy={dy0:.3f})  "
        f"zmin={bb0.zmin:.3f} zmax={bb0.zmax:.3f} (dz={dz0:.3f})"
    )

    # -----------------------
    # Parameters
    # -----------------------
    R_OLD = 10.0
    R_NEW = 2.0

    r_tol = 0.35
    env_tol = 1.0          # proximity to bbox extremes in the in-plane axes
    t_edge_tol = 1.5       # proximity to thickness extremes
    min_edge_len = 3.0

    # Determine thickness axis as the smallest bbox dimension
    dims0 = {"X": dx0, "Y": dy0, "Z": dz0}
    thickness_axis = min(dims0, key=dims0.get)
    print(f"Thickness axis inferred from bbox: {thickness_axis} (dims={dims0})")

    # -----------------------
    # OCCT helpers
    # -----------------------
    from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Torus

    def coord_along(p, axis: str) -> float:
        if axis == "X":
            return float(p.X())
        if axis == "Y":
            return float(p.Y())
        return float(p.Z())

    def bbox_minmax_along(bb, axis: str):
        if axis == "X":
            return bb.xmin, bb.xmax
        if axis == "Y":
            return bb.ymin, bb.ymax
        return bb.zmin, bb.zmax

    def is_outer_perimeter_point(p, bb, thickness_axis: str) -> bool:
        x, y, z = float(p.X()), float(p.Y()), float(p.Z())
        # "in-plane" axes are the two axes other than thickness_axis
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

    def count_r_faces(shape: cq.Shape, r_target: float):
        cyl = 0
        tor = 0
        for f in shape.Faces():
            ad = BRepAdaptor_Surface(f.wrapped, True)
            st = ad.GetType()
            if st == GeomAbs_Cylinder:
                if abs(float(ad.Cylinder().Radius()) - r_target) <= r_tol:
                    cyl += 1
            elif st == GeomAbs_Torus:
                # for rolling-ball blends, minor radius corresponds to fillet size
                if abs(float(ad.Torus().MinorRadius()) - r_target) <= r_tol:
                    tor += 1
        return cyl, tor

    # -----------------------
    # 1) Remove the all-around R10 fillet faces (cyl R10 + torus minor R10)
    # -----------------------
    c10, t10 = count_r_faces(base, R_OLD)
    print(f"Initial R~{R_OLD} faces detected: cylinders={c10}, torus(minor)={t10}")

    current = base

    for p in range(3):
        faces_r10 = []
        for f in current.Faces():
            ad = BRepAdaptor_Surface(f.wrapped, True)
            st = ad.GetType()
            if st == GeomAbs_Cylinder:
                if abs(float(ad.Cylinder().Radius()) - R_OLD) <= r_tol:
                    faces_r10.append(f.wrapped)
            elif st == GeomAbs_Torus:
                if abs(float(ad.Torus().MinorRadius()) - R_OLD) <= r_tol:
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

            new_shape = cq.Shape.cast(df.Shape())

            # Fix shape after defeaturing
            try:
                fixer = ShapeFix_Shape(new_shape.wrapped)
                fixer.Perform()
                new_shape = cq.Shape.cast(fixer.Shape())
            except Exception as e:
                print("  ShapeFix failed (continuing):", e)

            current = new_shape
            c10, t10 = count_r_faces(current, R_OLD)
            print(
                f"  After pass {p+1}: valid={current.isValid()} faces={len(current.Faces())} edges={len(current.Edges())}  "
                f"remaining R~{R_OLD}: cyl={c10}, tor(minor)={t10}"
            )
            if c10 == 0 and t10 == 0:
                break

        except Exception as e:
            print("Defeaturing exception:", e)
            break

    c10, t10 = count_r_faces(current, R_OLD)
    if c10 != 0 or t10 != 0:
        print(
            f"WARNING: R~{R_OLD} surfaces still present after defeaturing (cyl={c10}, tor={t10}). "
            f"Returning without adding new fillet to avoid stacking."
        )
        return current

    # -----------------------
    # 2) Add uniform R2 fillet on the same outer perimeter edge loops (both sides)
    #    Avoid TopTools_ListIteratorOfListOfShape (not available in this environment).
    #    Select by: (a) edge midpoint near outer bbox in-plane extremes, and
    #               (b) edge midpoint near thickness min/max.
    # -----------------------
    bb = current.BoundingBox()
    tmin, tmax = bbox_minmax_along(bb, thickness_axis)

    edges_to_fillet = []
    for e in current.Edges():
        ew = e.wrapped

        # length filter
        try:
            if float(e.Length()) < min_edge_len:
                continue
        except Exception:
            pass

        # midpoint
        try:
            ac = BRepAdaptor_Curve(ew)
            u0, u1 = float(ac.FirstParameter()), float(ac.LastParameter())
            um = 0.5 * (u0 + u1)
            p = ac.Value(um)
        except Exception:
            continue

        # near outer perimeter in the in-plane axes
        if not is_outer_perimeter_point(p, bb, thickness_axis):
            continue

        # near one of the two broad sides (thickness extremes)
        tv = coord_along(p, thickness_axis)
        if not (abs(tv - tmin) < t_edge_tol or abs(tv - tmax) < t_edge_tol):
            continue

        edges_to_fillet.append(ew)

    # Deduplicate by HashCode
    dedup = {}
    uniq = []
    for ew in edges_to_fillet:
        try:
            hk = int(ew.HashCode(10**9))
        except Exception:
            hk = id(ew)
        if hk in dedup:
            continue
        dedup[hk] = True
        uniq.append(ew)
    edges_to_fillet = uniq

    print(f"Edges selected for new R{R_NEW} fillet: {len(edges_to_fillet)}")
    if len(edges_to_fillet) == 0:
        print("No edges found for refillet; returning current for inspection.")
        return current

    # Apply fillet
    try:
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
        from OCP.ShapeFix import ShapeFix_Shape

        mk = BRepFilletAPI_MakeFillet(current.wrapped)
        for ew in edges_to_fillet:
            mk.Add(R_NEW, ew)
        mk.Build()
        if hasattr(mk, "IsDone") and not mk.IsDone():
            print("Fillet tool IsDone()=False; returning current.")
            return current

        result = cq.Shape.cast(mk.Shape())

        # Light fix
        try:
            fixer = ShapeFix_Shape(result.wrapped)
            fixer.Perform()
            result = cq.Shape.cast(fixer.Shape())
        except Exception:
            pass

        print("Applied new fillet")
        print(f"  result valid={result.isValid()} faces={len(result.Faces())} edges={len(result.Edges())}")

        c10, t10 = count_r_faces(result, R_OLD)
        c2, t2 = count_r_faces(result, R_NEW)
        print(f"Post-check: remaining R~{R_OLD}: cyl={c10}, tor(minor)={t10}")
        print(f"Post-check: detected R~{R_NEW}: cyl={c2}, tor(minor)={t2}")

        return result

    except Exception as e:
        print("Fillet exception:", e)
        return current
