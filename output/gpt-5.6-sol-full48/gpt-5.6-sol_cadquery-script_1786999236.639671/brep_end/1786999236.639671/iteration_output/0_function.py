def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print(f"Valid: {shape.isValid()}")
    print(f"Solids: {len(shape.Solids())}, Faces: {len(shape.Faces())}, Edges: {len(shape.Edges())}")
    bb = shape.BoundingBox()
    print(f"Bounding box: x=({bb.xmin:.6f},{bb.xmax:.6f}) y=({bb.ymin:.6f},{bb.ymax:.6f}) z=({bb.zmin:.6f},{bb.zmax:.6f})")

    print("--- Cylindrical faces ---")
    for i, face in enumerate(shape.Faces()):
        try:
            if face.geomType() == "CYLINDER":
                c = face.Center()
                fb = face.BoundingBox()
                adaptor = face._geomAdaptor()
                radius = adaptor.Cylinder().Radius()
                axis = adaptor.Cylinder().Axis().Direction()
                print(
                    f"face[{i}] CYLINDER radius={radius:.6f} area={face.Area():.6f} "
                    f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) "
                    f"axis=({axis.X():.6f},{axis.Y():.6f},{axis.Z():.6f}) "
                    f"bbox=({fb.xmin:.4f},{fb.xmax:.4f};{fb.ymin:.4f},{fb.ymax:.4f};{fb.zmin:.4f},{fb.zmax:.4f})"
                )
        except Exception as exc:
            print(f"face[{i}] cylinder inspection error: {exc}")

    print("--- Circular edges near likely hole sizes ---")
    for i, edge in enumerate(shape.Edges()):
        try:
            if edge.geomType() == "CIRCLE":
                r = edge.radius()
                c = edge.Center()
                eb = edge.BoundingBox()
                if r < 2.0:
                    print(
                        f"edge[{i}] CIRCLE radius={r:.6f} length={edge.Length():.6f} "
                        f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}) "
                        f"bbox=({eb.xmin:.4f},{eb.xmax:.4f};{eb.ymin:.4f},{eb.ymax:.4f};{eb.zmin:.4f},{eb.zmax:.4f})"
                    )
        except Exception as exc:
            print(f"edge[{i}] circle inspection error: {exc}")

    return model