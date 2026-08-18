def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bb = shape.BoundingBox()
    print("MODEL valid=", shape.isValid())
    print("MODEL solids=", len(shape.Solids()), "faces=", len(shape.Faces()))
    print("MODEL bbox min/max:", (bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax))
    print("MODEL size:", (bb.xlen, bb.ylen, bb.zlen), "center:", (bb.center.x, bb.center.y, bb.center.z))

    records = []
    for i, solid in enumerate(shape.Solids()):
        sb = solid.BoundingBox()
        c = sb.center
        records.append((solid.Volume(), i, sb, c, len(solid.Faces())))

    records.sort(reverse=True, key=lambda r: r[0])
    for rank, (vol, i, sb, c, nf) in enumerate(records):
        print("SOLID", i, "rank", rank, "vol", round(vol, 3), "faces", nf,
              "bbox", tuple(round(v, 3) for v in (sb.xmin, sb.ymin, sb.zmin, sb.xmax, sb.ymax, sb.zmax)),
              "size", tuple(round(v, 3) for v in (sb.xlen, sb.ylen, sb.zlen)),
              "center", tuple(round(v, 3) for v in (c.x, c.y, c.z)))

    return model