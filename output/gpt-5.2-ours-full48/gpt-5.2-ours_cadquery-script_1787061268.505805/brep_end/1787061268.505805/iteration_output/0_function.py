def my_cad_function(args):
    import cadquery as cq
    import os
    
    input_file = os.path.expanduser(args.get('input_file', ''))
    shape_wp = cq.importers.importStep(input_file)
    root_shape = shape_wp.val() if hasattr(shape_wp, 'val') else shape_wp

    # Collect solids
    wp_root = cq.Workplane(obj=root_shape)
    solids = wp_root.solids().vals()
    print(f"Loaded STEP: {input_file}")
    print(f"Total solids found: {len(solids)}")

    # Heatsink candidate heuristic: positive X block, y span ~[-18,0], z max ~30, x max ~56
    def score_heatsink(s):
        bb = s.BoundingBox()
        score = 0.0
        # Prefer positive X and near expected extents
        score += 5.0 if bb.xmax > 50 else 0.0
        score += 3.0 if bb.xmin > 10 else 0.0
        score += 4.0 if (bb.ymin < -14 and bb.ymax > -2) else 0.0
        score += 3.0 if bb.zmax > 25 else 0.0
        # Penalize too-tall z (avoid the tall right nozzle)
        score -= 5.0 if bb.zmax > 45 else 0.0
        # Prefer finned block volume range
        score += 2.0 if (bb.xlen > 20 and bb.ylen > 10 and bb.zlen > 20) else 0.0
        return score

    scored = [(i, score_heatsink(s), s) for i, s in enumerate(solids)]
    scored_sorted = sorted(scored, key=lambda t: t[1], reverse=True)

    for i, sc, s in scored_sorted:
        bb = s.BoundingBox()
        print(f"Solid {i}: score={sc:.2f} bbox=({bb.xmin:.2f},{bb.ymin:.2f},{bb.zmin:.2f}) -> ({bb.xmax:.2f},{bb.ymax:.2f},{bb.zmax:.2f})")

    if not scored_sorted or scored_sorted[0][1] <= 0:
        print("WARNING: Could not confidently identify heatsink solid; returning original shape")
        return shape_wp

    hs_idx, hs_score, hs_solid = scored_sorted[0]
    hs_bb = hs_solid.BoundingBox()
    print(f"Selected heatsink solid index: {hs_idx} (score={hs_score:.2f})")
    print(f"Heatsink bbox: xmin={hs_bb.xmin:.3f} xmax={hs_bb.xmax:.3f} ymin={hs_bb.ymin:.3f} ymax={hs_bb.ymax:.3f} zmin={hs_bb.zmin:.3f} zmax={hs_bb.zmax:.3f}")

    hs_wp = cq.Workplane(obj=hs_solid)

    # Identify back face as minimum Y face of heatsink
    back_face = hs_wp.faces('<Y').val()
    back_bb = back_face.BoundingBox()
    y_back = back_bb.ymin  # should be constant
    thickness_y = hs_bb.ymax - hs_bb.ymin
    print(f"Back face bbox: y=[{back_bb.ymin:.4f},{back_bb.ymax:.4f}] ; using y_back={y_back:.4f}")
    print(f"Estimated heatsink thickness along Y: {thickness_y:.3f}")

    # Attempt to detect existing circular holes on back face and plug them (remove legacy 3-point pattern)
    def wire_circle_data(w):
        edges = w.Edges()
        circ = [e for e in edges if hasattr(e, 'geomType') and e.geomType() == 'CIRCLE']
        if not circ:
            return None
        # Collect centers/radii; accept if consistent
        centers = []
        radii = []
        for e in circ:
            try:
                c = e.arcCenter()
                r = e.radius()
                centers.append(c)
                radii.append(r)
            except Exception:
                pass
        if not radii:
            return None
        # Use average
        cx = sum(v.x for v in centers) / len(centers)
        cy = sum(v.y for v in centers) / len(centers)
        cz = sum(v.z for v in centers) / len(centers)
        rmean = sum(radii) / len(radii)
        # Basic consistency check
        if max(radii) - min(radii) > 0.2:
            return None
        return (cq.Vector(cx, cy, cz), rmean)

    back_wires = list(back_face.Wires())
    print(f"Back face wire count: {len(back_wires)}")
    if back_wires:
        # Choose outer wire as the one with largest bbox area in XZ
        def wire_area_xz(w):
            bb = w.BoundingBox()
            return bb.xlen * bb.zlen
        outer = max(back_wires, key=wire_area_xz)
        inner = [w for w in back_wires if w is not outer]
    else:
        inner = []

    hole_candidates = []
    for w in inner:
        cd = wire_circle_data(w)
        if not cd:
            continue
        c3d, r = cd
        # Filter likely mounting holes (tune in later iterations): around M3/M4-ish
        if 1.0 <= r <= 3.5:
            hole_candidates.append((c3d, r))

    print(f"Detected circular hole candidates on heatsink back face: {len(hole_candidates)}")
    for j, (c3d, r) in enumerate(hole_candidates[:12]):
        print(f"  cand {j}: center=({c3d.x:.3f},{c3d.y:.3f},{c3d.z:.3f}) r={r:.3f}")

    hs_filled = hs_wp
    if hole_candidates:
        # Build plugs on the back face (extrude into part => negative extrude from face-normal workplane)
        # Use a slightly smaller radius to avoid accidental protrusion if there are edge blends.
        plug_solids = []
        # Create a stable back-face workplane
        bf_wp = cq.Workplane(obj=back_face)
        plane = bf_wp.plane
        for (c3d, r) in hole_candidates:
            loc = plane.toLocalCoords(c3d)
            rr = r * 0.98
            plug = bf_wp.center(loc.x, loc.y).circle(rr).extrude(-(thickness_y + 1.0), combine=False)
            plug_solids.append(plug.val())

        if plug_solids:
            plugs = plug_solids[0]
            for ps in plug_solids[1:]:
                plugs = plugs.fuse(ps)
            hs_filled = cq.Workplane(obj=hs_solid).union(plugs)
            print(f"Plugged {len(plug_solids)} hole(s) on the back face.")

    # Now add new 4-point mounting pattern (2x2), symmetric about heatsink X/Z midplanes
    hs_filled_solid = hs_filled.val() if hasattr(hs_filled, 'val') else hs_filled
    hs2_wp = cq.Workplane(obj=hs_filled_solid)

    # Re-acquire back face after plug union
    back_face2 = hs2_wp.faces('<Y').val()
    mount_wp = hs2_wp.faces('<Y').workplane(centerOption='CenterOfBoundBox')
    plane2 = mount_wp.plane

    x1 = hs_bb.xmin + 6.0
    x2 = hs_bb.xmax - 6.0
    z1 = hs_bb.zmin + 6.0
    z2 = hs_bb.zmax - 6.0

    # Four hole centers in global coords
    centers_global = [
        cq.Vector(x1, y_back, z1),
        cq.Vector(x2, y_back, z1),
        cq.Vector(x1, y_back, z2),
        cq.Vector(x2, y_back, z2),
    ]

    pts2d = []
    for p in centers_global:
        lp = plane2.toLocalCoords(p)
        pts2d.append((lp.x, lp.y))

    print("New 4-point pattern (global X,Z):")
    print(f"  x: {x1:.3f}, {x2:.3f} ; z: {z1:.3f}, {z2:.3f}")

    # Hole params (initial guess; will tune after seeing model):
    clear_d = 3.2        # M3 clearance
    cbore_d = 6.2        # SHCS head seat
    cbore_depth = 3.0

    # Cut 4 counterbored through holes from the back face
    hs_modified_wp = mount_wp.pushPoints(pts2d).cboreHole(clear_d, cbore_d, cbore_depth, depth=thickness_y + 2.0)

    hs_modified_solid = hs_modified_wp.val() if hasattr(hs_modified_wp, 'val') else hs_modified_wp

    # Rebuild compound with modified heatsink solid swapped in
    new_solids = []
    for i, s in enumerate(solids):
        if i == hs_idx:
            new_solids.append(hs_modified_solid)
        else:
            new_solids.append(s)

    result = cq.Compound.makeCompound(new_solids)
    print("Finished mounting update (iteration 1).")
    return result
