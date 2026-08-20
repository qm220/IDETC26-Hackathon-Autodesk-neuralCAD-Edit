def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    # Inspect and bind the planned FACE indices to the actual STEP geometry.
    faces = model.Faces()
    print("Loaded STEP: {}".format(input_file))
    print("Model valid: {}, solids: {}, faces: {}".format(
        model.isValid(), len(model.Solids()), len(faces)))
    for i, face in enumerate(faces):
        c = face.Center()
        b = face.BoundingBox()
        try:
            geom = face.geomType()
        except Exception:
            geom = "UNKNOWN"
        print(
            "FACE {}: type={} area={:.6f} center=({:.6f},{:.6f},{:.6f}) "
            "bbox=({:.6f},{:.6f})x({:.6f},{:.6f})x({:.6f},{:.6f}) wires={}".format(
                i, geom, face.Area(), c.x, c.y, c.z,
                b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax,
                len(face.Wires())
            )
        )

    def is_target_exterior(face, target_y):
        b = face.BoundingBox()
        try:
            planar = face.geomType() == "PLANE"
        except Exception:
            planar = False
        return (
            planar
            and abs(b.ymin - target_y) < 0.02
            and abs(b.ymax - target_y) < 0.02
            and b.xmin < -25.35 and b.xmax > 25.35
            and b.zmin < -25.35 and b.zmax > 25.35
        )

    def bind_face(planned_index, target_y, label):
        # Prefer the grounded STEP face index, but validate it against geometry.
        if planned_index < len(faces) and is_target_exterior(faces[planned_index], target_y):
            selected = faces[planned_index]
            print("Bound {} to grounded FACE {}".format(label, planned_index))
            return selected

        candidates = [f for f in faces if is_target_exterior(f, target_y)]
        if not candidates:
            raise ValueError("Could not locate {} exterior face at y={}".format(label, target_y))
        selected = max(candidates, key=lambda f: f.Area())
        actual_index = next(i for i, f in enumerate(faces) if f.isSame(selected))
        print("Grounded index mismatch; bound {} geometrically to FACE {}".format(
            label, actual_index))
        return selected

    positive_face = bind_face(53, 27.94, "positive-Y cover mating face")
    negative_face = bind_face(72, -15.24, "negative-Y cover mating face")

    thickness = 2.54

    # Use only each mating face's exact outer boundary. Internal wires are
    # intentionally omitted, as the requested covers match the outer contour.
    positive_outer = positive_face.outerWire()
    negative_outer = negative_face.outerWire()

    positive_cover = cq.Solid.extrudeLinear(
        positive_outer, [], cq.Vector(0.0, thickness, 0.0)
    )
    negative_cover = cq.Solid.extrudeLinear(
        negative_outer, [], cq.Vector(0.0, -thickness, 0.0)
    )

    print("Positive cover: volume={:.6f}, y=({:.6f},{:.6f}), valid={}".format(
        positive_cover.Volume(), positive_cover.BoundingBox().ymin,
        positive_cover.BoundingBox().ymax, positive_cover.isValid()))
    print("Negative cover: volume={:.6f}, y=({:.6f},{:.6f}), valid={}".format(
        negative_cover.Volume(), negative_cover.BoundingBox().ymin,
        negative_cover.BoundingBox().ymax, negative_cover.isValid()))

    # Build a non-fused compound so the original three components and the two
    # new covers remain five independent solids.
    result = cq.Compound.makeCompound(
        list(model.Solids()) + [positive_cover, negative_cover]
    )
    print("Final compound: solids={}, valid={}".format(
        len(result.Solids()), result.isValid()))
    return result