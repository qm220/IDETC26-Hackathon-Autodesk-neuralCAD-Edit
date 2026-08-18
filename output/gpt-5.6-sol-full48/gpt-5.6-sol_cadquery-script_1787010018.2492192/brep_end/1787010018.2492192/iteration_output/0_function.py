def my_cad_function(args):
    import os
    import math

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val() if hasattr(model, "val") else model

    print(f"Loaded STEP: {input_file}")
    print(f"Root type: {root.ShapeType()}, valid: {root.isValid()}")
    print(f"Total solids: {len(root.Solids())}, faces: {len(root.Faces())}, edges: {len(root.Edges())}")

    solids = root.Solids()
    for si, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = bb.center
        print(
            f"SOLID {si}: volume={solid.Volume():.6f}, "
            f"bbox=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f}) to "
            f"({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f}), "
            f"size=({bb.xlen:.3f},{bb.ylen:.3f},{bb.zlen:.3f}), "
            f"center=({c.x:.3f},{c.y:.3f},{c.z:.3f}), "
            f"faces={len(solid.Faces())}, edges={len(solid.Edges())}"
        )

        # Report long linear edges. These are the candidates for the remaining
        # sharp longitudinal edge of either blade-like crossbar.
        candidates = []
        for ei, edge in enumerate(solid.Edges()):
            try:
                gt = edge.geomType()
                length = edge.Length()
                if gt == "LINE" and length > 20.0:
                    verts = edge.Vertices()
                    if len(verts) >= 2:
                        p0 = verts[0].Center()
                        p1 = verts[-1].Center()
                        dx, dy, dz = p1.x-p0.x, p1.y-p0.y, p1.z-p0.z
                        mag = math.sqrt(dx*dx + dy*dy + dz*dz)
                        direction = (dx/mag, dy/mag, dz/mag) if mag else (0,0,0)
                        mid = edge.Center()
                        candidates.append((length, ei, p0, p1, mid, direction))
            except Exception as exc:
                print(f"  Could not inspect edge {ei}: {exc}")

        candidates.sort(reverse=True, key=lambda item: item[0])
        for length, ei, p0, p1, mid, direction in candidates:
            print(
                f"  LONG LINE edge {ei}: L={length:.4f}, "
                f"p0=({p0.x:.3f},{p0.y:.3f},{p0.z:.3f}), "
                f"p1=({p1.x:.3f},{p1.y:.3f},{p1.z:.3f}), "
                f"mid=({mid.x:.3f},{mid.y:.3f},{mid.z:.3f}), "
                f"dir=({direction[0]:.4f},{direction[1]:.4f},{direction[2]:.4f})"
            )

        # Report planar faces so the broad underside and narrow longitudinal
        # side can be correlated with the candidate edge in the next pass.
        for fi, face in enumerate(solid.Faces()):
            try:
                if face.geomType() == "PLANE":
                    fc = face.Center()
                    area = face.Area()
                    normal = face.normalAt(fc)
                    print(
                        f"  PLANE face {fi}: area={area:.4f}, "
                        f"center=({fc.x:.3f},{fc.y:.3f},{fc.z:.3f}), "
                        f"normal=({normal.x:.4f},{normal.y:.4f},{normal.z:.4f})"
                    )
            except Exception:
                pass

    # Diagnostic first pass: preserve the source exactly while extracting the
    # topology needed for deterministic selection of the requested edge.
    return model