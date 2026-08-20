def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported

    solids = list(root.Solids())
    faces = list(root.Faces())
    print("Loaded STEP: solids=%d faces=%d valid=%s" % (len(solids), len(faces), root.isValid()))

    # Inspect and bind the planned STEP face indices before changing topology.
    for idx in (22, 46):
        if idx < len(faces):
            f = faces[idx]
            bb = f.BoundingBox()
            c = f.Center()
            try:
                gt = f.geomType()
            except Exception:
                gt = "UNKNOWN"
            print(
                "FACE %d: type=%s center=(%.4f, %.4f, %.4f) "
                "bbox=[x %.4f..%.4f, y %.4f..%.4f, z %.4f..%.4f] area=%.4f"
                % (idx, gt, c.x, c.y, c.z, bb.xmin, bb.xmax,
                   bb.ymin, bb.ymax, bb.zmin, bb.zmax, f.Area())
            )

    if not solids:
        raise ValueError("The imported STEP contains no solids")

    # SOLID 0 is the highly detailed principal frame. Select it geometrically
    # as the solid having the largest number of faces, avoiding dependence on
    # compound ordering alone.
    main_index = max(range(len(solids)), key=lambda i: len(solids[i].Faces()))
    main = solids[main_index]
    print("Principal frame solid index=%d faces=%d volume=%.4f" %
          (main_index, len(main.Faces()), main.Volume()))

    # Reconfirm FACE 46 and FACE 22 using their planned geometric signatures:
    # planar, nearly constant Y, broad in X, and long in Z.
    rail_candidates = []
    for f in main.Faces():
        try:
            if f.geomType() != "PLANE":
                continue
        except Exception:
            continue
        bb = f.BoundingBox()
        if bb.ylen < 0.05 and bb.zlen > 400.0 and bb.xlen > 20.0:
            rail_candidates.append(f)

    if len(rail_candidates) < 2:
        raise ValueError("Could not geometrically identify both long planar rail faces")

    top_face = max(rail_candidates, key=lambda f: f.Center().y)
    bottom_face = min(rail_candidates, key=lambda f: f.Center().y)
    top_bb = top_face.BoundingBox()
    bottom_bb = bottom_face.BoundingBox()

    print("Selected top rail: y=%.4f x=[%.4f,%.4f] z=[%.4f,%.4f]" %
          (top_face.Center().y, top_bb.xmin, top_bb.xmax,
           top_bb.zmin, top_bb.zmax))
    print("Selected bottom rail: y=%.4f x=[%.4f,%.4f] z=[%.4f,%.4f]" %
          (bottom_face.Center().y, bottom_bb.xmin, bottom_bb.xmax,
           bottom_bb.zmin, bottom_bb.zmax))

    # Parameterized straight slots. The slots run across the narrow X width of
    # each rail and are patterned along the assembly's long CAD-Z direction.
    slot_width = 6.0
    nominal_slot_length = 24.0
    cut_depth = 3.0
    pitch = 24.0
    edge_clearance_z = 14.0
    keepout_clearance_z = 9.0
    boolean_overlap = 0.25

    def keepout_bbox(index):
        if 0 <= index < len(solids):
            bb = solids[index].BoundingBox()
            print("Keep-out SOLID %d bbox z=[%.4f, %.4f] y=[%.4f, %.4f]" %
                  (index, bb.zmin, bb.zmax, bb.ymin, bb.ymax))
            return bb
        return None

    # Planned exclusions: top mounting pad SOLID 17 and service cap SOLID 19;
    # bottom mounting pad SOLID 18.
    top_keepouts = [b for b in (keepout_bbox(17), keepout_bbox(19)) if b is not None]
    bottom_keepouts = [b for b in (keepout_bbox(18),) if b is not None]

    def pattern_stations(bb, exclusions):
        z_start = bb.zmin + edge_clearance_z
        z_end = bb.zmax - edge_clearance_z
        stations = []
        z = z_start
        half_w = slot_width * 0.5
        while z <= z_end + 1.0e-7:
            blocked = False
            for ex in exclusions:
                if (z + half_w + keepout_clearance_z >= ex.zmin and
                        z - half_w - keepout_clearance_z <= ex.zmax):
                    blocked = True
                    break
            if not blocked:
                stations.append(z)
            z += pitch
        return stations

    top_stations = pattern_stations(top_bb, top_keepouts)
    bottom_stations = pattern_stations(bottom_bb, bottom_keepouts)
    print("Top slot stations (%d): %s" %
          (len(top_stations), ", ".join("%.2f" % z for z in top_stations)))
    print("Bottom slot stations (%d): %s" %
          (len(bottom_stations), ", ".join("%.2f" % z for z in bottom_stations)))

    def make_capsule_cutter(face_bb, face_y, zc, inward_sign):
        # Maintain at least 6 mm of structure at each X edge.
        available_x = face_bb.xlen - 12.0
        overall_length = min(nominal_slot_length, available_x)
        if overall_length <= slot_width:
            raise ValueError("Rail face is too narrow for the selected slot")

        radius = slot_width * 0.5
        straight_length = overall_length - slot_width
        xc = 0.5 * (face_bb.xmin + face_bb.xmax)
        x0 = xc - straight_length * 0.5
        z0 = zc - radius

        if inward_sign < 0:
            # Top: enter material along -Y.
            y0 = face_y - cut_depth
            box = cq.Solid.makeBox(
                straight_length, cut_depth + boolean_overlap, slot_width,
                cq.Vector(x0, y0, z0)
            )
            cyl_start_y = face_y + boolean_overlap
            cyl_dir = cq.Vector(0, -1, 0)
        else:
            # Bottom: enter material along +Y.
            y0 = face_y - boolean_overlap
            box = cq.Solid.makeBox(
                straight_length, cut_depth + boolean_overlap, slot_width,
                cq.Vector(x0, y0, z0)
            )
            cyl_start_y = face_y - boolean_overlap
            cyl_dir = cq.Vector(0, 1, 0)

        c1 = cq.Solid.makeCylinder(
            radius, cut_depth + 2.0 * boolean_overlap,
            cq.Vector(xc - straight_length * 0.5, cyl_start_y, zc), cyl_dir
        )
        c2 = cq.Solid.makeCylinder(
            radius, cut_depth + 2.0 * boolean_overlap,
            cq.Vector(xc + straight_length * 0.5, cyl_start_y, zc), cyl_dir
        )
        return box.fuse(c1, c2)

    cutters = []
    top_y = top_face.Center().y
    bottom_y = bottom_face.Center().y
    for zc in top_stations:
        cutters.append(make_capsule_cutter(top_bb, top_y, zc, -1))
    for zc in bottom_stations:
        cutters.append(make_capsule_cutter(bottom_bb, bottom_y, zc, 1))

    if not cutters:
        raise ValueError("No valid slot cutters were generated")

    cutter_compound = cq.Compound.makeCompound(cutters)
    before_volume = main.Volume()
    edited_main = main.cut(cutter_compound)
    after_volume = edited_main.Volume()
    print("Frame volume before=%.4f after=%.4f removed=%.4f" %
          (before_volume, after_volume, before_volume - after_volume))

    if before_volume - after_volume <= 1.0:
        raise ValueError("Slot Boolean did not remove a meaningful volume")

    # Restore every disconnected component unchanged around the edited frame.
    output_shapes = []
    for i, solid in enumerate(solids):
        output_shapes.append(edited_main if i == main_index else solid)

    result = cq.Compound.makeCompound(output_shapes)
    print("Result: solids=%d faces=%d valid=%s" %
          (len(result.Solids()), len(result.Faces()), result.isValid()))
    return result