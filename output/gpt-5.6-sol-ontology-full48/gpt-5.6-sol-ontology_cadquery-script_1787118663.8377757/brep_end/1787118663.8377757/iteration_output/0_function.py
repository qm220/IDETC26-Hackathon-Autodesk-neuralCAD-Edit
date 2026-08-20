def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val() if hasattr(imported, "val") else imported

    print("SOURCE MODEL INSPECTION")
    print(f"Valid: {source.isValid()}")
    print(f"Solids: {len(source.Solids())}, Faces: {len(source.Faces())}, Edges: {len(source.Edges())}")
    bb = source.BoundingBox()
    print(f"BBox: x=({bb.xmin:.6f},{bb.xmax:.6f}), y=({bb.ymin:.6f},{bb.ymax:.6f}), z=({bb.zmin:.6f},{bb.zmax:.6f})")

    for i, face in enumerate(source.Faces()):
        fbb = face.BoundingBox()
        c = face.Center()
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        try:
            normal = face.normalAt(c)
            normal_text = f"({normal.x:.6f},{normal.y:.6f},{normal.z:.6f})"
        except Exception:
            normal_text = "unavailable"
        print(
            f"FACE {i}: type={geom_type}, center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"normal={normal_text}, area={face.Area():.6f}, "
            f"bbox=({fbb.xmin:.6f},{fbb.xmax:.6f}; {fbb.ymin:.6f},{fbb.ymax:.6f}; {fbb.zmin:.6f},{fbb.zmax:.6f}), "
            f"wires={len(face.Wires())}, edges={len(face.Edges())}"
        )

    # Apply the first grounded operation to the complete body. Scaling about
    # the existing origin preserves the x=0 and y=0 symmetry references.
    scaled = source.scale(10.0)
    sbb = scaled.BoundingBox()
    print("SCALED MODEL")
    print(f"Valid: {scaled.isValid()}")
    print(f"BBox: x=({sbb.xmin:.6f},{sbb.xmax:.6f}), y=({sbb.ymin:.6f},{sbb.ymax:.6f}), z=({sbb.zmin:.6f},{sbb.zmax:.6f})")
    print(f"Volume: {scaled.Volume():.6f} mm^3")

    return cq.Workplane("XY").newObject([scaled])