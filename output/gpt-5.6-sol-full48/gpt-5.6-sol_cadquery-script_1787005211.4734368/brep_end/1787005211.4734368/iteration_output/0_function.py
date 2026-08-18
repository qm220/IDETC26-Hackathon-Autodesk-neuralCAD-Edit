def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val()

    print(f"Model valid: {root.isValid()}")
    print(f"Total solids: {len(root.Solids())}")
    print(f"Total faces: {len(root.Faces())}")

    overall_bb = root.BoundingBox()
    print(
        "Overall bbox: "
        f"min=({overall_bb.xmin:.4f}, {overall_bb.ymin:.4f}, {overall_bb.zmin:.4f}), "
        f"max=({overall_bb.xmax:.4f}, {overall_bb.ymax:.4f}, {overall_bb.zmax:.4f}), "
        f"size=({overall_bb.xlen:.4f}, {overall_bb.ylen:.4f}, {overall_bb.zlen:.4f})"
    )

    solids = list(root.Solids())
    solids.sort(key=lambda s: s.Volume(), reverse=True)
    for solid_index, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = solid.Center()
        print(
            f"Solid {solid_index}: volume={solid.Volume():.6f}, faces={len(solid.Faces())}, "
            f"center=({c.x:.4f}, {c.y:.4f}, {c.z:.4f}), "
            f"bbox=({bb.xmin:.4f}, {bb.ymin:.4f}, {bb.zmin:.4f}) to "
            f"({bb.xmax:.4f}, {bb.ymax:.4f}, {bb.zmax:.4f})"
        )

        for face_index, face in enumerate(solid.Faces()):
            fc = face.Center()
            fbb = face.BoundingBox()
            try:
                normal = face.normalAt()
                normal_text = f"({normal.x:.4f}, {normal.y:.4f}, {normal.z:.4f})"
            except Exception as exc:
                normal_text = f"unavailable: {exc}"
            try:
                geom_type = face.geomType()
            except Exception:
                geom_type = "unknown"
            print(
                f"  Face {face_index}: type={geom_type}, area={face.Area():.6f}, "
                f"center=({fc.x:.4f}, {fc.y:.4f}, {fc.z:.4f}), normal={normal_text}, "
                f"bbox=({fbb.xmin:.4f}, {fbb.ymin:.4f}, {fbb.zmin:.4f}) to "
                f"({fbb.xmax:.4f}, {fbb.ymax:.4f}, {fbb.zmax:.4f})"
            )

    print("Diagnostic pass complete; returning the unmodified source model for orientation review.")
    return model