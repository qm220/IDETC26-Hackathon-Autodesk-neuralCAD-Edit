def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print(f"Model valid: {shape.isValid()}")
    bbox = shape.BoundingBox()
    print(f"Overall bbox: x=({bbox.xmin:.3f},{bbox.xmax:.3f}) y=({bbox.ymin:.3f},{bbox.ymax:.3f}) z=({bbox.zmin:.3f},{bbox.zmax:.3f})")

    solids = shape.Solids()
    print(f"Solid count: {len(solids)}")
    for i, solid in enumerate(solids):
        sb = solid.BoundingBox()
        print(
            f"SOLID {i}: volume={solid.Volume():.3f}, "
            f"bbox x=({sb.xmin:.3f},{sb.xmax:.3f}) "
            f"y=({sb.ymin:.3f},{sb.ymax:.3f}) "
            f"z=({sb.zmin:.3f},{sb.zmax:.3f}), "
            f"size=({sb.xlen:.3f},{sb.ylen:.3f},{sb.zlen:.3f})"
        )
        for j, face in enumerate(solid.Faces()):
            try:
                geom = face.geomType()
            except Exception:
                geom = "UNKNOWN"
            if geom == "CYLINDER":
                try:
                    radius = face._geomAdaptor().Cylinder().Radius()
                    center = face.Center()
                    print(
                        f"  cylinder face {j}: radius={radius:.4f}, "
                        f"center=({center.x:.3f},{center.y:.3f},{center.z:.3f}), "
                        f"area={face.Area():.3f}"
                    )
                except Exception as exc:
                    print(f"  cylinder face {j}: unable to inspect: {exc}")

    return model