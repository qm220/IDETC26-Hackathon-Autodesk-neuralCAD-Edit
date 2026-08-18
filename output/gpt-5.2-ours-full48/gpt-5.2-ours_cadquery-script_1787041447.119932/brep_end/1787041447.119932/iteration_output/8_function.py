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
        print(
            f"Solid[{i}] bbox: x={bb.xlen:.3f} y={bb.ylen:.3f} z={bb.zlen:.3f} "
            f"center=({c.x:.3f},{c.y:.3f},{c.z:.3f})"
        )

    if len(solids) != 3:
        print("WARNING: Expected 3 solids; returning original model")
        return model

    # identify: clamp (largest Y), vertical (largest Z of remaining), diagonal (other)
    clamp_i = max(range(3), key=lambda i: solids[i].BoundingBox().ylen)
    rem = [i for i in range(3) if i != clamp_i]
    vert_i = max(rem, key=lambda i: solids[i].BoundingBox().zlen)
    diag_i = [i for i in rem if i != vert_i][0]

    diagonal = solids[diag_i]
    vertical = solids[vert_i]
    clamp = solids[clamp_i]
    print(f"Identified clamp_i={clamp_i}, vertical_i={vert_i}, diagonal_i={diag_i}")

    # Requested R = 0.635 cm = 6.35 mm
    R_nom = 6.35
    R_try = [R_nom - 0.01, R_nom - 0.05, R_nom - 0.10]

    def v_unit(v: cq.Vector):
        L = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        if L < 1e-12:
            return None
        return cq.Vector(v.x / L, v.y / L, v.z / L)

    def dot(a: cq.Vector, b: cq.Vector):
        return a.x * b.x + a.y * b.y + a.z * b.z

    def edge_dir(edge):
        vs = list(edge.Vertices())
        if len(vs) < 2:
            return None
        p0 = vs[0].Center()
        p1 = vs[-1].Center()
        return v_unit(cq.Vector(p1.x - p0.x, p1.y - p0.y, p1.z - p0.z))

    # diagonal axis approx from bbox (long in XZ)
    bb = diagonal.BoundingBox()
    diag_axis = v_unit(cq.Vector(bb.xlen, 0.0, bb.zlen))
    if diag_axis is None:
        diag_axis = cq.Vector(1, 0, 0)
    print(f"Diagonal axis approx (unit): ({diag_axis.x:.3f},{diag_axis.y:.3f},{diag_axis.z:.3f})")

    # OCP surface interrogation
    def surf_adaptor(face):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        return BRepAdaptor_Surface(face.wrapped)

    def is_plane(face):
        from OCP.GeomAbs import GeomAbs_Plane
        return int(surf_adaptor(face).GetType()) == int(GeomAbs_Plane)

    def is_cylinder(face):
        from OCP.GeomAbs import GeomAbs_Cylinder
        return int(surf_adaptor(face).GetType()) == int(GeomAbs_Cylinder)

    def plane_normal_and_point(face):
        ad = surf_adaptor(face)
        pln = ad.Plane()
        n = pln.Axis().Direction()
        o = pln.Location()
        return cq.Vector(n.X(), n.Y(), n.Z()), cq.Vector(o.X(), o.Y(), o.Z())

    def cyl_axis_radius(face):
        ad = surf_adaptor(face)
        cy = ad.Cylinder()
        ax = cy.Axis()
        d = ax.Direction()
        o = ax.Location()
        return cq.Vector(d.X(), d.Y(), d.Z()), cq.Vector(o.X(), o.Y(), o.Z()), float(cy.Radius())

    # Estimate diagonal member OD radius: largest cylinder radius whose axis ~diag_axis
    cyl_rads = []
    for f in diagonal.Faces():
        try:
            if not is_cylinder(f):
                continue
            d, o, r = cyl_axis_radius(f)
            du = v_unit(d)
            if du is None:
                continue
            if abs(dot(du, diag_axis)) > 0.98:
                cyl_rads.append(r)
        except Exception:
            continue

    if not cyl_rads:
        print("No cylinder faces aligned with diagonal axis found; returning original model")
        return model

    od_r = max(cyl_rads)
    print(f"Estimated diagonal OD radius: {od_r:.4f} mm (from {len(cyl_rads)} cyl faces)")

    # Find the 'blade' long sharp edge: LINE edge aligned with diag_axis, adjacent to (plane + OD cylinder)
    # Additionally require plane to be a true secant cut of the cylinder (axis-to-plane distance < radius),
    # to avoid tangent cases.
    candidates = []
    for e in diagonal.Edges():
        try:
            if "LINE" not in str(e.geomType()).upper():
                continue
            L = float(e.Length())
            if L < 150.0:
                continue
            ed = edge_dir(e)
            if ed is None or abs(dot(ed, diag_axis)) < 0.98:
                continue

            faces = list(e.ancestors(diagonal, kind="Face"))
            if len(faces) < 2:
                continue

            plane_faces = [f for f in faces if is_plane(f)]
            cyl_faces = [f for f in faces if is_cylinder(f)]
            if not plane_faces or not cyl_faces:
                continue

            # choose an OD-ish cylinder among adjacent cyl faces
            od_adj = []
            for cf in cyl_faces:
                cd, co, cr = cyl_axis_radius(cf)
                cdu = v_unit(cd)
                if cdu is None:
                    continue
                if abs(dot(cdu, diag_axis)) < 0.98:
                    continue
                if abs(cr - od_r) > 0.15:  # tight tol around OD
                    continue
                od_adj.append((cf, cdu, co, cr))
            if not od_adj:
                continue

            # choose the most plausible plane: normal ~perp to diag_axis and plane contains cyl axis direction
            best = None
            for pf in plane_faces:
                pn, pp = plane_normal_and_point(pf)
                pnu = v_unit(pn)
                if pnu is None:
                    continue
                if abs(dot(pnu, diag_axis)) > 0.20:
                    continue

                for (cf, cdu, co, cr) in od_adj:
                    # plane should contain cylinder axis direction => normal ⟂ cyl axis
                    if abs(dot(pnu, cdu)) > 0.10:
                        continue
                    # distance from cylinder axis line to plane is constant when axis || plane
                    # use axis origin point co
                    dist = abs(dot(co - pp, pnu))
                    # secant cut gives two-line intersection when dist < r
                    if dist >= (cr - 0.05):
                        continue
                    best = (pf, cf, cr, dist)
                    break
                if best:
                    break

            if not best:
                continue

            ec = e.Center()
            candidates.append({
                "edge": e,
                "L": L,
                "center": ec,
                "dist": best[3],
            })
        except Exception:
            continue

    print(f"Plane-OD-cylinder long LINE edge candidates on diagonal: {len(candidates)}")
    candidates = sorted(candidates, key=lambda d: d["L"], reverse=True)
    for i, d in enumerate(candidates[:10]):
        c = d["center"]
        print(f"  cand[{i}] L={d['L']:.3f} center=({c.x:.3f},{c.y:.3f},{c.z:.3f}) axisPlaneDist={d['dist']:.3f}")

    if not candidates:
        print("No suitable 'blade' edge found on diagonal using plane-OD-cylinder criteria; returning original model")
        return model

    target_edge = candidates[0]["edge"]
    print(f"Targeting 1 edge (longest) for fillet: L={candidates[0]['L']:.3f} mm")

    def try_fillet_edge(solid, edge, radius):
        try:
            from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
            mk = BRepFilletAPI_MakeFillet(solid.wrapped)
            mk.Add(float(radius), edge.wrapped)
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
        print(f"Fillet attempt radius={r:.3f} mm (nom={R_nom:.3f})")
        ok, mod, msg = try_fillet_edge(diagonal, target_edge, r)
        print(f"  result ok={ok}, msg={msg}")
        last_msg = msg
        if ok:
            modified = mod
            break

    if modified is None:
        print(f"FAILED to apply fillet. Last message: {last_msg}")
        return model

    return cq.Compound.makeCompound([modified, vertical, clamp])
