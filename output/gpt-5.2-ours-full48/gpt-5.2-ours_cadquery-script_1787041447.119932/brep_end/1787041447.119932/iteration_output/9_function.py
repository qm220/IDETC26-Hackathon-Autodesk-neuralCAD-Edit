def my_cad_function(args):
    import cadquery as cq
    import os, math

    in_path = os.path.expanduser(args.get('input_file', ''))
    if not in_path or not os.path.exists(in_path):
        raise ValueError(f"Input STEP file not found: {in_path}")

    model = cq.importers.importStep(in_path)
    root = model.val() if hasattr(model, "val") else model
    solids = list(root.Solids())

    print(f"Loaded STEP: {in_path}")
    print(f"Num solids: {len(solids)}")
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        c = bb.center
        print(f"Solid[{i}] bbox: x={bb.xlen:.3f} y={bb.ylen:.3f} z={bb.zlen:.3f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f})")

    if len(solids) != 3:
        print("WARNING: Expected 3 solids; returning original model")
        return model

    # Identify solids by bounding box proportions
    clamp_i = max(range(3), key=lambda i: solids[i].BoundingBox().ylen)
    rem = [i for i in range(3) if i != clamp_i]
    vert_i = max(rem, key=lambda i: solids[i].BoundingBox().zlen)
    diag_i = [i for i in rem if i != vert_i][0]

    diagonal = solids[diag_i]
    vertical = solids[vert_i]
    clamp = solids[clamp_i]
    print(f"Identified clamp_i={clamp_i}, vertical_i={vert_i}, diagonal_i={diag_i}")

    # Requested radius: 0.635 cm = 6.35 mm
    R_nom = 6.35
    R_try = [R_nom, R_nom - 0.01, R_nom - 0.05, R_nom - 0.10, 6.00]

    def v_unit(v: cq.Vector):
        L = math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
        if L < 1e-12:
            return None
        return cq.Vector(v.x/L, v.y/L, v.z/L)

    def dot(a: cq.Vector, b: cq.Vector):
        return a.x*b.x + a.y*b.y + a.z*b.z

    def v_sub(a: cq.Vector, b: cq.Vector):
        return cq.Vector(a.x-b.x, a.y-b.y, a.z-b.z)

    def edge_chord_dir(edge):
        vs = list(edge.Vertices())
        if len(vs) < 2:
            return None
        p0 = vs[0].Center()
        p1 = vs[-1].Center()
        return v_unit(v_sub(p1, p0))

    # OCP surface interrogation
    def surf_adaptor(face):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        return BRepAdaptor_Surface(face.wrapped)

    def is_plane(face):
        from OCP.GeomAbs import GeomAbs_Plane
        return int(surf_adaptor(face).GetType()) == int(GeomAbs_Plane)

    def plane_normal_and_point(face):
        ad = surf_adaptor(face)
        pln = ad.Plane()
        n = pln.Axis().Direction()
        o = pln.Location()
        return cq.Vector(n.X(), n.Y(), n.Z()), cq.Vector(o.X(), o.Y(), o.Z())

    # Robust diagonal axis estimate (PCA/power-iteration on vertices); fallback to bbox
    pts = [v.Center() for v in diagonal.Vertices()]
    diag_axis = None
    if len(pts) >= 3:
        mx = sum(p.x for p in pts) / len(pts)
        my = sum(p.y for p in pts) / len(pts)
        mz = sum(p.z for p in pts) / len(pts)
        # covariance
        cxx=cxy=cxz=cyy=cyz=czz=0.0
        for p in pts:
            x=p.x-mx; y=p.y-my; z=p.z-mz
            cxx += x*x; cxy += x*y; cxz += x*z
            cyy += y*y; cyz += y*z; czz += z*z
        n = float(len(pts))
        cxx/=n; cxy/=n; cxz/=n; cyy/=n; cyz/=n; czz/=n
        # power iteration
        vx, vy, vz = 1.0, 0.0, 0.0
        for _ in range(40):
            nx = cxx*vx + cxy*vy + cxz*vz
            ny = cxy*vx + cyy*vy + cyz*vz
            nz = cxz*vx + cyz*vy + czz*vz
            L = math.sqrt(nx*nx + ny*ny + nz*nz)
            if L < 1e-12:
                break
            vx, vy, vz = nx/L, ny/L, nz/L
        diag_axis = v_unit(cq.Vector(vx, vy, vz))

    if diag_axis is None:
        bb = diagonal.BoundingBox()
        diag_axis = v_unit(cq.Vector(bb.xlen, 0.0, bb.zlen))

    if diag_axis is None:
        diag_axis = cq.Vector(1, 0, 0)

    print(f"Diagonal axis approx (unit): ({diag_axis.x:.3f},{diag_axis.y:.3f},{diag_axis.z:.3f})")

    # Choose the blade/flat planar face on diagonal: largest plane whose normal is ~perp to axis (not end-caps)
    plane_faces = []
    for f in diagonal.Faces():
        try:
            if not is_plane(f):
                continue
            n, p = plane_normal_and_point(f)
            nu = v_unit(n)
            if nu is None:
                continue
            # Exclude end faces (plane normal ~ parallel to axis)
            if abs(dot(nu, diag_axis)) > 0.25:
                continue
            plane_faces.append((f, float(f.Area()), nu))
        except Exception:
            continue

    print(f"Diagonal plane faces (excluding end-caps): {len(plane_faces)}")
    if not plane_faces:
        print("No suitable longitudinal planar face found on diagonal; returning original model")
        return model

    blade_face, blade_area, blade_nu = max(plane_faces, key=lambda t: t[1])
    print(f"Selected blade planar face area={blade_area:.3f}, normal=({blade_nu.x:.3f},{blade_nu.y:.3f},{blade_nu.z:.3f})")

    # Compute face normal at a 3D point by projecting to the face surface
    def normal_on_face_at_point(face, p: cq.Vector):
        try:
            from OCP.BRep import BRep_Tool
            from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
            from OCP.GeomLProp import GeomLProp_SLProps
            from OCP.gp import gp_Pnt

            hsurf = BRep_Tool.Surface(face.wrapped)
            proj = GeomAPI_ProjectPointOnSurf(gp_Pnt(p.x, p.y, p.z), hsurf)
            if proj.NbPoints() <= 0:
                return None
            u, v = proj.LowerDistanceParameters()
            props = GeomLProp_SLProps(hsurf, u, v, 1, 1e-6)
            if not props.IsNormalDefined():
                return None
            n = props.Normal()
            nu = v_unit(cq.Vector(n.X(), n.Y(), n.Z()))
            return nu
        except Exception:
            return None

    # Candidate long sharp edges on the blade_face running along the diagonal axis
    candidates = []
    for e in blade_face.Edges():
        try:
            L = float(e.Length())
            if L < 150.0:
                continue
            d = edge_chord_dir(e)
            if d is None:
                continue
            if abs(dot(d, diag_axis)) < 0.95:
                continue

            # Adjacent faces (within diagonal solid)
            adj_faces = list(e.ancestors(diagonal, kind="Face"))
            # Ensure blade_face is one of them
            if not any(af.isSame(blade_face) for af in adj_faces):
                continue
            other_faces = [af for af in adj_faces if not af.isSame(blade_face)]
            if not other_faces:
                continue
            other = other_faces[0]

            pc = e.Center()
            n1 = normal_on_face_at_point(blade_face, pc)
            n2 = normal_on_face_at_point(other, pc)
            if n1 is None or n2 is None:
                continue
            sharp = abs(dot(n1, n2)) < 0.95  # not tangent
            if not sharp:
                continue

            candidates.append({
                "edge": e,
                "L": L,
                "center": pc,
                "other_is_plane": is_plane(other)
            })
        except Exception:
            continue

    print(f"Long sharp edge candidates on blade face: {len(candidates)}")
    candidates = sorted(candidates, key=lambda c: (c["L"], c["center"].y), reverse=True)
    for i, c in enumerate(candidates[:10]):
        p = c["center"]
        print(f"  cand[{i}] L={c['L']:.3f} center=({p.x:.3f},{p.y:.3f},{p.z:.3f}) other_is_plane={c['other_is_plane']}")

    if not candidates:
        print("No suitable long sharp 'blade' edge found; returning original model")
        return model

    # Choose ONE long edge: prefer the longest, and if multiple, the one with higher Y (reads as 'upper' edge)
    target = candidates[0]
    target_edge = target["edge"]
    target_cy = target["center"].y
    print(f"Target edge: L={target['L']:.3f} center_y={target_cy:.3f}")

    # If the long edge is split into multiple segments, include same-style segments with similar Y center
    chain_edges = []
    for c in candidates:
        if abs(c["center"].y - target_cy) <= 1.5 and abs(c["L"] - target["L"]) <= 50.0:
            chain_edges.append(c["edge"])

    # Deduplicate by hashCode
    uniq = []
    seen = set()
    for e in chain_edges:
        try:
            h = e.hashCode()
        except Exception:
            h = id(e)
        if h in seen:
            continue
        seen.add(h)
        uniq.append(e)

    chain_edges = uniq
    print(f"Fillet will be applied to {len(chain_edges)} edge(s) (chain selection)")

    def try_fillet_edges(solid, edges, radius):
        try:
            from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
            mk = BRepFilletAPI_MakeFillet(solid.wrapped)
            for ed in edges:
                mk.Add(float(radius), ed.wrapped)
            mk.Build()
            if not mk.IsDone():
                return (False, None, "MakeFillet not done")
            res = cq.Shape.cast(mk.Shape())
            res_solids = list(res.Solids())
            if len(res_solids) != 1:
                return (False, None, f"Unexpected solids after fillet: {len(res_solids)}")
            return (True, res_solids[0], "ok")
        except Exception as e:
            return (False, None, str(e))

    modified = None
    last_msg = None
    for r in R_try:
        print(f"Fillet attempt radius={r:.3f} mm")
        ok, mod, msg = try_fillet_edges(diagonal, chain_edges, r)
        print(f"  result ok={ok}, msg={msg}")
        last_msg = msg
        if ok:
            modified = mod
            break

    if modified is None:
        print(f"FAILED to apply fillet. Last message: {last_msg}")
        return model

    # Return assembly-like compound with 3 solids
    return cq.Compound.makeCompound([modified, vertical, clamp])
