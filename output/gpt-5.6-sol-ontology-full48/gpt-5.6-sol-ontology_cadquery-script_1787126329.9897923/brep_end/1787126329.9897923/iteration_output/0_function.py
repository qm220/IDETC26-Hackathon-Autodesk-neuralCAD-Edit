def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base = imported.val() if hasattr(imported, "val") else imported

    # Inspect the imported topology before editing so planned FACE indices are
    # bound to actual geometry rather than assumed to remain stable.
    print(f"Loaded STEP: {input_file}")
    print(f"Base valid: {base.isValid()}, solids: {len(base.Solids())}, faces: {len(base.Faces())}")
    for i, face in enumerate(base.Faces()):
        bb = face.BoundingBox()
        c = face.Center()
        try:
            gt = face.geomType()
        except Exception:
            gt = "UNKNOWN"
        print(
            f"FACE {i}: type={gt}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), "
            f"bbox=({bb.xmin:.4f},{bb.xmax:.4f}) x "
            f"({bb.ymin:.4f},{bb.ymax:.4f}) x "
            f"({bb.zmin:.4f},{bb.zmax:.4f})"
        )

    # Confirm the grounded functional faces geometrically. These are the two
    # opposed jaw planes at x=-10 and x=+10, spanning the complete thickness.
    jaw_faces = []
    for i, face in enumerate(base.Faces()):
        bb = face.BoundingBox()
        if face.geomType() == "PLANE" and bb.ymin < 0.01 and bb.ymax > 14.99:
            if abs(bb.xmin - bb.xmax) < 1.0e-5 and abs(abs(bb.xmin) - 10.0) < 1.0e-3:
                jaw_faces.append((i, bb.xmin, bb.zmin, bb.zmax))
    print(f"Grounded jaw contact faces: {jaw_faces}")

    # Build an exact model of a U-shaped through-slot. The slot consists of a
    # 20 mm-wide straight opening and a radius-5 rounded closed root. Building
    # both old and revised cutters lets us add only the material lying between
    # their roots, while leaving the imported exterior untouched.
    plane = cq.Plane(origin=(0, 0, 0), xDir=(1, 0, 0), normal=(0, 1, 0))

    def slot_cutter(root_z):
        tangent_z = root_z - 5.0

        # Open-ended straight portion, deliberately extending past z=-150.
        straight = (
            cq.Workplane(plane)
            .center(0, (-160.0 + tangent_z) / 2.0)
            .rect(20.0, tangent_z - (-160.0))
            .extrude(15.0)
        )

        # Central portion up to the horizontal 10 mm root segment.
        root_core = (
            cq.Workplane(plane)
            .center(0, (tangent_z + root_z) / 2.0)
            .rect(10.0, root_z - tangent_z)
            .extrude(15.0)
        )

        # Radius-5 transitions tangent to x=-10, x=10 and to the root line.
        left_round = (
            cq.Workplane(plane)
            .center(-5.0, tangent_z)
            .circle(5.0)
            .extrude(15.0)
        )
        right_round = (
            cq.Workplane(plane)
            .center(5.0, tangent_z)
            .circle(5.0)
            .extrude(15.0)
        )

        return straight.union(root_core).union(left_round).union(right_round).val()

    old_slot = slot_cutter(-110.0)
    revised_slot = slot_cutter(-120.0)

    # The revised slot is a subset of the old void. Add back their difference:
    # this moves the root 10 mm toward -Z without moving either jaw plane.
    repair = old_slot.cut(revised_slot)
    edited = base.fuse(repair)
    try:
        edited = edited.clean()
    except Exception:
        pass

    print(f"Repair volume: {repair.Volume():.6f} mm^3")
    print(f"Edited valid: {edited.isValid()}, solids: {len(edited.Solids())}, faces: {len(edited.Faces())}")

    # Inspect regenerated topology and verify that the functional jaw planes
    # remain parallel at x=-10 and x=+10, hence exactly 20 mm apart.
    regenerated_jaws = []
    root_faces = []
    for i, face in enumerate(edited.Faces()):
        bb = face.BoundingBox()
        if face.geomType() == "PLANE":
            if abs(bb.xmax - bb.xmin) < 1.0e-5 and abs(abs(bb.xmin) - 10.0) < 1.0e-3 and bb.ymin < 0.01 and bb.ymax > 14.99:
                regenerated_jaws.append((i, bb.xmin, bb.zmin, bb.zmax))
            if abs(bb.zmax - bb.zmin) < 1.0e-5 and abs(bb.zmin + 120.0) < 1.0e-3:
                root_faces.append((i, bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin))

    print(f"Regenerated jaw faces: {regenerated_jaws}")
    print(f"Regenerated root faces at z=-120: {root_faces}")
    print("Required jaw separation: 20.000 mm (planes x=-10.000 and x=10.000)")
    print("Revised slot depth: 30.000 mm from open tip z=-150 to root z=-120")

    return cq.Workplane(obj=edited)
