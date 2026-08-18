def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    print(f"Imported STEP: {input_file}")
    print(f"Model valid: {shape.isValid()}")
    print(f"Model volume: {shape.Volume():.6f} mm^3")
    print(f"Face count: {len(shape.Faces())}")

    bb = shape.BoundingBox()
    print(
        f"Overall bbox: x=({bb.xmin:.6f},{bb.xmax:.6f}) "
        f"y=({bb.ymin:.6f},{bb.ymax:.6f}) "
        f"z=({bb.zmin:.6f},{bb.zmax:.6f}); "
        f"size=({bb.xlen:.6f},{bb.ylen:.6f},{bb.zlen:.6f})"
    )

    solids = shape.Solids()
    print(f"Solid count: {len(solids)}")
    for i, solid in enumerate(solids):
        sb = solid.BoundingBox()
        c = solid.Center()
        print(
            f"SOLID {i}: volume={solid.Volume():.6f}, faces={len(solid.Faces())}, "
            f"center=({c.x:.6f},{c.y:.6f},{c.z:.6f}), "
            f"bbox=x({sb.xmin:.6f},{sb.xmax:.6f}) "
            f"y({sb.ymin:.6f},{sb.ymax:.6f}) "
            f"z({sb.zmin:.6f},{sb.zmax:.6f}), "
            f"size=({sb.xlen:.6f},{sb.ylen:.6f},{sb.zlen:.6f})"
        )

        # Report planar face locations and normals to establish the axial direction
        # and engagement limits of the central insert and hub seat.
        planar = []
        for j, face in enumerate(solid.Faces()):
            try:
                if face.geomType() == "PLANE":
                    fc = face.Center()
                    n = face.normalAt(fc)
                    planar.append((face.Area(), j, fc, n))
            except Exception:
                pass
        planar.sort(key=lambda item: item[0], reverse=True)
        print(f"SOLID {i} largest planar faces:")
        for area, j, fc, n in planar[:20]:
            print(
                f"  face[{j}] area={area:.6f}, "
                f"center=({fc.x:.6f},{fc.y:.6f},{fc.z:.6f}), "
                f"normal=({n.x:.6f},{n.y:.6f},{n.z:.6f})"
            )

    return model