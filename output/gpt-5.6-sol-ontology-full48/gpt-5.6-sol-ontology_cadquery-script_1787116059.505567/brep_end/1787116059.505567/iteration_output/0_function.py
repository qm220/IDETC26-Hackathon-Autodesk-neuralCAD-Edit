def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    print("Loaded STEP:", input_file)
    print("Model valid:", model.isValid())
    print("Face count:", len(model.Faces()))
    print("Solid count:", len(model.Solids()))
    mb = model.BoundingBox()
    print("Model bbox: x=(%.3f, %.3f), y=(%.3f, %.3f), z=(%.3f, %.3f)" %
          (mb.xmin, mb.xmax, mb.ymin, mb.ymax, mb.zmin, mb.zmax))

    faces = list(model.Faces())

    # Bind the planning FACE indices to the actual imported geometry.
    for face_index in (38, 46, 56, 798):
        if 0 <= face_index < len(faces):
            f = faces[face_index]
            bb = f.BoundingBox()
            c = f.Center()
            try:
                gt = f.geomType()
            except Exception:
                gt = "unknown"
            print("FACE %d: type=%s area=%.3f center=(%.3f, %.3f, %.3f) bbox=[x %.3f..%.3f, y %.3f..%.3f, z %.3f..%.3f]" %
                  (face_index, gt, f.Area(), c.x, c.y, c.z,
                   bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))

    # Confirm FACE 46 against nearby broad, horizontal upper-header faces.
    upper_candidates = []
    for i, f in enumerate(faces):
        bb = f.BoundingBox()
        c = f.Center()
        if bb.ylen < 0.05 and 165.0 < c.y < 180.0 and f.Area() > 5000.0:
            upper_candidates.append((i, f.Area(), c.x, c.y, c.z, bb.zlen))
    print("Upper-header planar-face candidates:", upper_candidates)

    solids = list(model.Solids())
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        c = bb.center
        print("SOLID %d: volume=%.3f center=(%.3f, %.3f, %.3f) size=(%.3f, %.3f, %.3f)" %
              (i, s.Volume(), c.x, c.y, c.z, bb.xlen, bb.ylen, bb.zlen))

    # Locate the existing F012 cap solid by its reported upper-header position.
    cap_candidates = []
    for i, s in enumerate(solids):
        bb = s.BoundingBox()
        c = bb.center
        if c.y > 174.0 and abs(c.z) < 30.0 and bb.ylen < 35.0 and max(bb.xlen, bb.zlen) < 80.0:
            score = abs(c.z) + abs(c.y - 181.0) + 0.05 * abs(bb.xlen - bb.zlen)
            cap_candidates.append((score, i, s))

    old_cap_index = None
    old_cap = None
    if cap_candidates:
        cap_candidates.sort(key=lambda item: item[0])
        old_cap_index = cap_candidates[0][1]
        old_cap = cap_candidates[0][2]
        print("Bound F012/FACE 798 to SOLID", old_cap_index)
    else:
        print("Warning: existing F012 cap solid was not isolated; using FACE 46 fallback coordinates")

    # Establish the filler axis from the existing cap envelope, with FACE 46 as
    # the upper-header attachment reference.
    if old_cap is not None:
        cb = old_cap.BoundingBox()
        axis_x = cb.center.x
        axis_z = cb.center.z
        measured_cap_diameter = max(cb.xlen, cb.zlen)
    else:
        axis_x = -88.9
        axis_z = 0.0
        measured_cap_diameter = 40.0

    header_y = 174.851756
    if 46 < len(faces):
        f46 = faces[46]
        b46 = f46.BoundingBox()
        c46 = f46.Center()
        if b46.ylen < 0.1 and 165.0 < c46.y < 180.0:
            header_y = c46.y

    # If FACE 46 ordering differs, use the largest matching upper face.
    if upper_candidates and not (165.0 < header_y < 180.0):
        upper_candidates.sort(key=lambda item: item[1], reverse=True)
        header_y = upper_candidates[0][3]

    cap_od = max(36.0, min(48.0, measured_cap_diameter))
    neck_od = max(28.0, min(36.0, cap_od - 7.0))
    bore_d = max(20.0, neck_od - 8.0)
    flange_od = min(cap_od - 2.0, neck_od + 7.0)
    neck_height = 18.0
    flange_height = 4.0
    cap_height = 15.0
    cap_clearance = 0.6

    print("Filler axis: (x=%.3f, z=%.3f), header y=%.3f" % (axis_x, axis_z, header_y))
    print("Filling-system dimensions: bore=%.2f, neck OD=%.2f, flange OD=%.2f, cap OD=%.2f" %
          (bore_d, neck_od, flange_od, cap_od))

    def axis_plane(y_value):
        return cq.Plane(origin=(axis_x, y_value, axis_z),
                        xDir=(1, 0, 0), normal=(0, 1, 0))

    def annulus(y_value, height, outer_d, inner_d):
        return (cq.Workplane(axis_plane(y_value))
                .circle(outer_d / 2.0)
                .circle(inner_d / 2.0)
                .extrude(height)
                .val())

    def cylinder(y_value, height, diameter):
        return (cq.Workplane(axis_plane(y_value))
                .circle(diameter / 2.0)
                .extrude(height)
                .val())

    # Suppress the old single-face cap so it is replaced rather than duplicated.
    kept_solids = [s for i, s in enumerate(solids) if i != old_cap_index]

    # Cut a true pouring passage into the largest connected radiator/frame body.
    # If the known-invalid imported body rejects the boolean, preserve it and
    # retain the neck as a separate watertight solid on the exact header plane.
    if kept_solids:
        main_index = max(range(len(kept_solids)), key=lambda i: kept_solids[i].Volume())
        main_body = kept_solids[main_index]
        bore_cutter = cylinder(header_y - 22.0, 26.0, bore_d)
        try:
            cut_body = main_body.cut(bore_cutter)
            if cut_body is not None and len(cut_body.Solids()) > 0 and cut_body.Volume() > 0.5 * main_body.Volume():
                kept_solids[main_index] = cut_body
                print("Created pouring bore through the upper header")
            else:
                print("Header bore boolean returned an implausible result; original radiator retained")
        except Exception as exc:
            print("Header bore boolean failed on imported invalid B-rep; using separate neck fallback:", exc)

    # Pressure-containing pouring neck: main annular tube, reinforced root, and
    # an upper retention/sealing flange. All pieces share a continuous bore.
    neck = annulus(header_y, neck_height, neck_od, bore_d)
    root = annulus(header_y, 3.0, neck_od + 5.0, bore_d)
    flange_y = header_y + neck_height - flange_height
    flange = annulus(flange_y, flange_height, flange_od, bore_d)
    neck_shape = neck.fuse(root).fuse(flange)

    # Add a conical lead-in at the pouring lip to protect the seal and aid filling.
    try:
        lead_in = cq.Solid.makeCone(
            bore_d / 2.0,
            bore_d / 2.0 + 1.25,
            2.0,
            cq.Vector(axis_x, header_y + neck_height - 2.0, axis_z),
            cq.Vector(0, 1, 0)
        )
        neck_shape = neck_shape.cut(lead_in)
    except Exception as exc:
        print("Lip lead-in construction skipped:", exc)

    # Build a separate removable cup-shaped cap. Its cavity clears the flange,
    # while the crown closes the bore and the internal annular pad forms a seal.
    cap_bottom_y = flange_y - 0.8
    skirt_height = cap_height - 4.0
    outer_skirt = cylinder(cap_bottom_y, skirt_height, cap_od)
    crown_frustum = cq.Solid.makeCone(
        cap_od / 2.0,
        cap_od / 2.0 - 2.3,
        3.0,
        cq.Vector(axis_x, cap_bottom_y + skirt_height, axis_z),
        cq.Vector(0, 1, 0)
    )
    crown_top = cylinder(cap_bottom_y + skirt_height + 3.0, 1.0, cap_od - 4.6)
    cap_shape = outer_skirt.fuse(crown_frustum).fuse(crown_top)

    cavity_d = flange_od + 2.0 * cap_clearance
    cavity_depth = cap_height - 3.2
    cavity = cylinder(cap_bottom_y - 0.5, cavity_depth + 0.5, cavity_d)
    cap_shape = cap_shape.cut(cavity)

    # Annular sealing pad attached beneath the crown and bearing on the neck land.
    seal_y = cap_bottom_y + cavity_depth - 1.2
    seal_outer_d = neck_od - 1.0
    seal_inner_d = bore_d + 2.0
    if seal_outer_d > seal_inner_d:
        seal_ring = annulus(seal_y, 1.2, seal_outer_d, seal_inner_d)
        cap_shape = cap_shape.fuse(seal_ring)

    # Eight external grip ribs recreate a manually grippable flared cap crown.
    rib_radial = 3.0
    rib_tangent = 5.0
    rib_height = 8.0
    rib_center_y = cap_bottom_y + 0.55 * skirt_height
    for angle in range(0, 360, 45):
        rib = (cq.Workplane("XY")
               .box(rib_radial, rib_height, rib_tangent)
               .translate((axis_x + cap_od / 2.0 + rib_radial / 2.0 - 0.8,
                           rib_center_y,
                           axis_z))
               .rotate((axis_x, 0, axis_z), (axis_x, 1, axis_z), angle)
               .val())
        try:
            cap_shape = cap_shape.fuse(rib)
        except Exception:
            pass

    print("Neck valid:", neck_shape.isValid(), "volume:", neck_shape.Volume())
    print("Replacement cap valid:", cap_shape.isValid(), "volume:", cap_shape.Volume())

    # Preserve all radiator, fan, blade, hose-fitting, and corner-mount solids.
    # Neck and cap remain distinct solids so the cap is functionally removable.
    final_shapes = kept_solids + [neck_shape, cap_shape]
    result = cq.Compound.makeCompound(final_shapes)
    print("Final compound solids:", len(result.Solids()))
    print("Final compound valid:", result.isValid())
    return result