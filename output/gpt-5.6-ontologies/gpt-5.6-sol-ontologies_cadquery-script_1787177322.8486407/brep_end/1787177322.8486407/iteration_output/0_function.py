def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    solids = shape.Solids()
    faces = shape.Faces()
    print(f"Model valid: {shape.isValid()}")
    print(f"Solids: {len(solids)}, faces: {len(faces)}")

    # Inspect all solids to bind planned SOLID 55 to the imported geometry.
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = solid.Center()
        print(
            f"SOLID {i}: center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), "
            f"bbox=({bb.xmin:.4f},{bb.ymin:.4f},{bb.zmin:.4f})-"
            f"({bb.xmax:.4f},{bb.ymax:.4f},{bb.zmax:.4f}), "
            f"size=({bb.xlen:.4f},{bb.ylen:.4f},{bb.zlen:.4f}), "
            f"volume={solid.Volume():.4f}"
        )

    # Inspect the planned F008 face range and nearby faces. FACE N corresponds
    # to shape.Faces()[N] in the STEP analysis, but coordinates are checked here.
    for i in range(max(0, len(faces) - 20), len(faces)):
        face = faces[i]
        bb = face.BoundingBox()
        c = face.Center()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        try:
            n = face.normalAt()
            normal_text = f"({n.x:.5f},{n.y:.5f},{n.z:.5f})"
        except Exception as exc:
            normal_text = f"unavailable:{exc}"
        print(
            f"FACE {i}: type={geom_type}, center=({c.x:.4f},{c.y:.4f},{c.z:.4f}), "
            f"normal={normal_text}, area={face.Area():.4f}, "
            f"bbox=({bb.xmin:.4f},{bb.ymin:.4f},{bb.zmin:.4f})-"
            f"({bb.xmax:.4f},{bb.ymax:.4f},{bb.zmax:.4f})"
        )

    return model