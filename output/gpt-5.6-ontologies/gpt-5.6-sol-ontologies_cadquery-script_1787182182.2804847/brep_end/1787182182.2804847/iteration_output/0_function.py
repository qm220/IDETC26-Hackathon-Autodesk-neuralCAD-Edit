def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val() if hasattr(model, "val") else model

    bbox = shape.BoundingBox()
    center = bbox.center
    print("=== MODEL INSPECTION ===")
    print(f"Valid: {shape.isValid()}")
    print(f"Volume: {shape.Volume():.6f}")
    print(f"Bounding box: x=({bbox.xmin:.6f}, {bbox.xmax:.6f}), y=({bbox.ymin:.6f}, {bbox.ymax:.6f}), z=({bbox.zmin:.6f}, {bbox.zmax:.6f})")
    print(f"Bounding-box center: ({center.x:.6f}, {center.y:.6f}, {center.z:.6f})")

    faces = shape.Faces()
    print(f"Face count: {len(faces)}")
    for i, face in enumerate(faces):
        c = face.Center()
        fb = face.BoundingBox()
        geom_type = face.geomType()
        msg = (
            f"FACE {i}: type={geom_type}, area={face.Area():.6f}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=({fb.xmin:.6f},{fb.xmax:.6f}; "
            f"{fb.ymin:.6f},{fb.ymax:.6f}; {fb.zmin:.6f},{fb.zmax:.6f})"
        )
        try:
            n = face.normalAt()
            msg += f", normal=({n.x:.6f},{n.y:.6f},{n.z:.6f})"
        except Exception as exc:
            msg += f", normal_error={exc}"
        try:
            if geom_type in ("CYLINDER", "CONE"):
                axis = face.normalAt(c)
                msg += f", axis_hint=({axis.x:.6f},{axis.y:.6f},{axis.z:.6f})"
        except Exception:
            pass
        print(msg)

        vertices = face.Vertices()
        coords = []
        for vertex in vertices:
            p = vertex.Center()
            coords.append(f"({p.x:.4f},{p.y:.4f},{p.z:.4f})")
        print(f"  vertices[{len(vertices)}]: " + ", ".join(coords))

    print("=== FACE 7 REFERENCE ===")
    if len(faces) > 7:
        target = faces[7]
        tc = target.Center()
        tn = target.normalAt()
        print(f"FACE 7 center=({tc.x:.6f},{tc.y:.6f},{tc.z:.6f})")
        print(f"FACE 7 normal=({tn.x:.6f},{tn.y:.6f},{tn.z:.6f})")
        print(f"FACE 7 area={target.Area():.6f}, type={target.geomType()}")
        print(f"FACE 7 edge count={len(target.Edges())}")
        for j, edge in enumerate(target.Edges()):
            ec = edge.Center()
            eb = edge.BoundingBox()
            try:
                length = edge.Length()
            except Exception:
                length = -1.0
            print(
                f"  EDGE {j}: type={edge.geomType()}, length={length:.6f}, "
                f"center=({ec.x:.6f},{ec.y:.6f},{ec.z:.6f}), "
                f"bbox=({eb.xmin:.6f},{eb.xmax:.6f};{eb.ymin:.6f},{eb.ymax:.6f};{eb.zmin:.6f},{eb.zmax:.6f})"
            )

    return model