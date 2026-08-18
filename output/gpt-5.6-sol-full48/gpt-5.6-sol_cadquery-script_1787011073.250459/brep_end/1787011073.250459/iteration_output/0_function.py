def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    print(f"Model valid: {shape.isValid()}")
    print(f"Assembly bbox: {shape.BoundingBox()}")
    solids = shape.Solids()
    print(f"Solid count: {len(solids)}")
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        print(
            f"SOLID {i:02d}: volume={solid.Volume():.3f}, faces={len(solid.Faces())}, "
            f"bbox=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f}) to "
            f"({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f}), "
            f"size=({bb.xlen:.3f},{bb.ylen:.3f},{bb.zlen:.3f})"
        )
    return model