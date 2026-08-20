def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, "val") else imported
    solids = list(root.Solids())
    faces = list(root.Faces())

    print("Loaded STEP: solids=%d faces=%d valid=%s" % (len(solids), len(faces), root.isValid()))
    for idx in (22, 46):
        if idx < len(faces):
            face = faces[idx]
            bb = face.BoundingBox()
            center = face.Center()
            print("FACE %d: type=%s center=(%.4f, %.4f, %.4f) bbox=[x %.4f..%.4f, y %.4f..%.4f, z %.4f..%.4f] area=%.4f" % (idx, face.geomType(), center.x, center.y, center.z, bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax, face.Area()))

    if not solids:
        raise ValueError("The imported STEP contains no solids")

    main_index = max(range(len(solids)), key=lambda i: len(solids[i].Faces()))
    main = solids[main_index]

    rail_faces = []
    for face in main.Faces():
        bb = face.BoundingBox()
        if face.geomType() == "PLANE" and bb.ylen < 0.05 and bb.zlen > 400.0 and bb.xlen > 20.0:
            rail_faces.append(face)

    if len(rail_faces) < 2:
        raise ValueError("Could not identify the top and bottom rail surfaces")

    top_face = max(rail_faces, key=lambda f: f.Center().y)
    bottom_face = min(rail_faces, key=lambda f: f.Center().y)

    slot_width = 6.0
    slot_length = 24.0
    cut_depth = 3.0
    pitch = 24.0
    edge_clearance = 14.0
    keepout_clearance = 9.0
    overlap = 0.25

    top_keepouts = [solids[i].BoundingBox() for i in (17, 19) if i < len(solids)]
    bottom_keepouts = [solids[i].BoundingBox() for i in (18,) if i < len(solids)]

    def stations(face_bb, exclusions):
        result = []
        z = face_bb.zmin + edge_clearance
        zmax = face_bb.zmax - edge_clearance
        while z <= zmax + 1.0e-7:
            blocked = any(z + slot_width / 2.0 + keepout_clearance >= ex.zmin and z - slot_width / 2.0 - keepout_clearance <= ex.zmax for ex in exclusions)
            if not blocked:
                result.append(z)
            z += pitch
        return result

    def capsule(face, zc, top):
        bb = face.BoundingBox()
        length = min(slot_length, bb.xlen - 12.0)
        radius = slot_width / 2.0
        straight = length - slot_width
        xc = (bb.xmin + bb.xmax) / 2.0
        face_y = face.Center().y
        x0 = xc - straight / 2.0
        z0 = zc - radius

        if top:
            y0 = face_y - cut_depth
            start_y = face_y + overlap
            direction = cq.Vector(0, -1, 0)
        else:
            y0 = face_y - overlap
            start_y = face_y - overlap
            direction = cq.Vector(0, 1, 0)

        center_box = cq.Solid.makeBox(straight, cut_depth + overlap, slot_width, cq.Vector(x0, y0, z0))
        end1 = cq.Solid.makeCylinder(radius, cut_depth + 2.0 * overlap, cq.Vector(xc - straight / 2.0, start_y, zc), direction)
        end2 = cq.Solid.makeCylinder(radius, cut_depth + 2.0 * overlap, cq.Vector(xc + straight / 2.0, start_y, zc), direction)
        return center_box.fuse(end1, end2)

    cutters = []
    for zc in stations(top_face.BoundingBox(), top_keepouts):
        cutters.append(capsule(top_face, zc, True))
    for zc in stations(bottom_face.BoundingBox(), bottom_keepouts):
        cutters.append(capsule(bottom_face, zc, False))

    edited_main = main.cut(cq.Compound.makeCompound(cutters))
    output = [edited_main if i == main_index else solid for i, solid in enumerate(solids)]
    return cq.Compound.makeCompound(output)