def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    bb = original.BoundingBox()
    print("Original valid:", original.isValid())
    print("Original solids:", len(original.Solids()))
    print("Original volume:", round(original.Volume(), 6))
    print("Bounding box:",
          "xmin", round(bb.xmin, 4), "xmax", round(bb.xmax, 4),
          "ymin", round(bb.ymin, 4), "ymax", round(bb.ymax, 4),
          "zmin", round(bb.zmin, 4), "zmax", round(bb.zmax, 4))

    # Diagnose the native topology of the enlarged head so the next revision
    # can select its actual sharp edges for kernel filleting instead of using
    # the invalid mirror/intersection approximation from the prior iteration.
    print("HEAD EDGE TOPOLOGY")
    for i, edge in enumerate(original.Edges()):
        eb = edge.BoundingBox()
        c = edge.Center()
        # The enlarged head is the end region x <= 100. Include boundary edges
        # at the arm junction but exclude edges wholly in the long arm.
        if eb.xmin <= 100.1 and c.x <= 105.0:
            verts = edge.Vertices()
            pts = []
            for v in verts:
                p = v.Center()
                pts.append((round(p.x, 4), round(p.y, 4), round(p.z, 4)))
            try:
                gt = edge.geomType()
            except Exception:
                gt = "UNKNOWN"
            print("EDGE", i,
                  "type", gt,
                  "len", round(edge.Length(), 4),
                  "center", (round(c.x, 4), round(c.y, 4), round(c.z, 4)),
                  "bbox", (round(eb.xmin, 4), round(eb.xmax, 4),
                            round(eb.ymin, 4), round(eb.ymax, 4),
                            round(eb.zmin, 4), round(eb.zmax, 4)),
                  "vertices", pts)

    print("HEAD FACE TOPOLOGY")
    for i, face in enumerate(original.Faces()):
        fb = face.BoundingBox()
        c = face.Center()
        if fb.xmin <= 100.1 and c.x <= 105.0:
            try:
                gt = face.geomType()
            except Exception:
                gt = "UNKNOWN"
            try:
                n = face.normalAt(c)
                normal = (round(n.x, 4), round(n.y, 4), round(n.z, 4))
            except Exception:
                normal = None
            print("FACE", i,
                  "type", gt,
                  "area", round(face.Area(), 4),
                  "center", (round(c.x, 4), round(c.y, 4), round(c.z, 4)),
                  "normal", normal,
                  "bbox", (round(fb.xmin, 4), round(fb.xmax, 4),
                            round(fb.ymin, 4), round(fb.ymax, 4),
                            round(fb.zmin, 4), round(fb.zmax, 4)))

    # Return the untouched, valid source during this diagnostic iteration.
    return model