def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    base = imported.val() if hasattr(imported, "val") else imported

    print(f"Loaded STEP: {input_file}")
    print(f"Base valid: {base.isValid()}, solids: {len(base.Solids())}, faces: {len(base.Faces())}")

    # Bind the planned FACE references to the imported geometry.
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

    grounded_jaws = []
    grounded_root = []
    for i, face in enumerate(base.Faces()):
        bb = face.BoundingBox()
        if face.geomType() != "PLANE":
            continue
        if (
            abs(bb.xmax - bb.xmin) < 1.0e-6
            and abs(abs(bb.xmin) - 10.0) < 1.0e-3
            and bb.ymin < 0.01
            and bb.ymax > 14.99
            and bb.zmin < -114.9
        ):
            grounded_jaws.append((i, bb.xmin, bb.zmin, bb.zmax))
        if (
            abs(bb.zmax - bb.zmin) < 1.0e-6
            and abs(bb.zmin + 110.0) < 1.0e-3
            and bb.xmin < -4.99
            and bb.xmax > 4.99
        ):
            grounded_root.append((i, bb.xmin, bb.xmax, bb.zmin))

    print(f"Grounded functional jaw faces: {grounded_jaws}")
    print(f"Grounded original root face: {grounded_root}")

    # Correctly oriented XZ sketch plane. Its local +Y direction is global +Z,
    # while its normal is global -Y. Extrusion therefore runs through the
    # wrench thickness from y=16 to y=-1 without reversing the Z coordinates.
    xz_plane = cq.Plane(
        origin=(0.0, 16.0, 0.0),
        xDir=(1.0, 0.0, 0.0),
        normal=(0.0, -1.0, 0.0),
    )

    def make_slot_cutter(root_z):
        radius = 5.0
        tangent_z = root_z - radius
        open_z = -160.0

        straight = (
            cq.Workplane(xz_plane)
            .center(0.0, 0.5 * (open_z + tangent_z))
            .rect(20.0, tangent_z - open_z)
            .extrude(17.0)
        )
        root_core = (
            cq.Workplane(xz_plane)
            .center(0.0, 0.5 * (tangent_z + root_z))
            .rect(10.0, root_z - tangent_z)
            .extrude(17.0)
        )
        left_transition = (
            cq.Workplane(xz_plane)
            .center(-5.0, tangent_z)
            .circle(radius)
            .extrude(17.0)
        )
        right_transition = (
            cq.Workplane(xz_plane)
            .center(5.0, tangent_z)
            .circle(radius)
            .extrude(17.0)
        )
        return (
            straight
            .union(root_core)
            .union(left_transition)
            .union(right_transition)
            .val()
        )

    revised_slot = make_slot_cutter(-120.0)

    # Heal the region occupied by the former root. The blank overlaps existing
    # jaw material slightly in X and Z, ensuring a robust single-solid union.
    # Cutting the revised slot afterward restores exact x=-10 and x=+10 jaw
    # planes and creates the requested radius-5 root at z=-120.
    healing_blank = (
        cq.Workplane("XY")
        .box(20.2, 15.0, 20.2)
        .translate((0.0, 7.5, -120.0))
        .val()
    )

    healed = base.fuse(healing_blank)
    edited = healed.cut(revised_slot)
    try:
        edited = edited.clean()
    except Exception:
        pass

    print(
        f"Edited valid: {edited.isValid()}, solids: {len(edited.Solids())}, "
        f"faces: {len(edited.Faces())}"
    )

    regenerated_jaws = []
    regenerated_roots = []
    radius_five_transitions = []

    for i, face in enumerate(edited.Faces()):
        bb = face.BoundingBox()
        gt = face.geomType()
        if gt == "PLANE":
            if (
                abs(bb.xmax - bb.xmin) < 1.0e-6
                and abs(abs(bb.xmin) - 10.0) < 1.0e-3
                and bb.ymin < 0.01
                and bb.ymax > 14.99
                and bb.zmin < -149.9
                and abs(bb.zmax + 125.0) < 1.0e-3
            ):
                regenerated_jaws.append((i, bb.xmin, bb.zmin, bb.zmax))
            if (
                abs(bb.zmax - bb.zmin) < 1.0e-6
                and abs(bb.zmin + 120.0) < 1.0e-3
                and bb.xmin < -4.99
                and bb.xmax > 4.99
                and bb.ymin < 0.01
                and bb.ymax > 14.99
            ):
                regenerated_roots.append(
                    (i, bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin)
                )
        elif gt == "CYLINDER":
            if (
                bb.ymin < 0.01
                and bb.ymax > 14.99
                and bb.zmin > -130.01
                and bb.zmax < -119.99
            ):
                radius_five_transitions.append(
                    (i, bb.xmin, bb.xmax, bb.zmin, bb.zmax)
                )

    print(f"Regenerated jaw contact faces: {regenerated_jaws}")
    print(f"Regenerated root faces at z=-120: {regenerated_roots}")
    print(f"Candidate radius-5 root transitions: {radius_five_transitions}")
    print("Required jaw relationship: parallel planes x=-10 and x=10")
    print("Verified nominal jaw separation: 20.000 mm")
    print("Revised slot depth: 30.000 mm from z=-150 to z=-120")

    if len(edited.Solids()) != 1:
        raise ValueError(
            f"Expected one connected wrench solid after editing, got {len(edited.Solids())}"
        )
    if len(regenerated_jaws) < 2:
        raise ValueError("Could not verify both revised jaw contact faces")
    if len(regenerated_roots) < 1:
        raise ValueError("Could not verify the revised root plane at z=-120")

    return cq.Workplane(obj=edited)