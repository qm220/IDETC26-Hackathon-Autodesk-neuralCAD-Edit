def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bbox = shape.BoundingBox()
    print(f"Valid: {shape.isValid()}")
    print(f"Volume: {shape.Volume():.6f} mm^3")
    print(f"Faces: {len(shape.Faces())}")
    print(f"BBox: x=({bbox.xmin:.6f}, {bbox.xmax:.6f}) dx={bbox.xlen:.6f}; "
          f"y=({bbox.ymin:.6f}, {bbox.ymax:.6f}) dy={bbox.ylen:.6f}; "
          f"z=({bbox.zmin:.6f}, {bbox.zmax:.6f}) dz={bbox.zlen:.6f}")

    planar = []
    for index, face in enumerate(shape.Faces()):
        try:
            geom_type = face.geomType()
        except Exception:
            geom_type = "UNKNOWN"
        if geom_type == "PLANE":
            center = face.Center()
            try:
                normal = face.normalAt(center)
            except Exception:
                normal = face.normalAt()
            planar.append((face.Area(), index, center, normal))

    planar.sort(key=lambda item: item[0], reverse=True)
    print(f"Planar faces: {len(planar)}")
    for area, index, center, normal in planar[:30]:
        print(
            f"PLANAR face={index} area={area:.6f} "
            f"center=({center.x:.6f},{center.y:.6f},{center.z:.6f}) "
            f"normal=({normal.x:.6f},{normal.y:.6f},{normal.z:.6f})"
        )

    return model