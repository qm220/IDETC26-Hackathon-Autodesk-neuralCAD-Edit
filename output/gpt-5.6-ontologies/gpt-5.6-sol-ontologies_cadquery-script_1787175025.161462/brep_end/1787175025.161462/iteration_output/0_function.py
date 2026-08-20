def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bbox = shape.BoundingBox()
    print(f"Model valid: {shape.isValid()}")
    print(f"Solids: {len(shape.Solids())}, Faces: {len(shape.Faces())}")
    print(f"Volume: {shape.Volume():.6f} mm^3")
    print(
        f"Model bbox: x=({bbox.xmin:.6f},{bbox.xmax:.6f}) "
        f"y=({bbox.ymin:.6f},{bbox.ymax:.6f}) "
        f"z=({bbox.zmin:.6f},{bbox.zmax:.6f}); "
        f"size=({bbox.xlen:.6f},{bbox.ylen:.6f},{bbox.zlen:.6f})"
    )

    faces = shape.Faces()
    for index, face in enumerate(faces):
        center = face.Center()
        fb = face.BoundingBox()
        try:
            geometry_type = face.geomType()
        except Exception:
            geometry_type = "UNKNOWN"
        normal_text = ""
        if geometry_type == "PLANE":
            try:
                normal = face.normalAt(center)
                normal_text = f" normal=({normal.x:.6f},{normal.y:.6f},{normal.z:.6f})"
            except Exception as exc:
                normal_text = f" normal_error={exc}"
        print(
            f"FACE {index}: type={geometry_type} area={face.Area():.6f} "
            f"center=({center.x:.6f},{center.y:.6f},{center.z:.6f}) "
            f"bbox=({fb.xmin:.6f},{fb.xmax:.6f}; "
            f"{fb.ymin:.6f},{fb.ymax:.6f}; "
            f"{fb.zmin:.6f},{fb.zmax:.6f}){normal_text}"
        )

    print("Inspection pass complete; returning the unchanged source model.")
    return model