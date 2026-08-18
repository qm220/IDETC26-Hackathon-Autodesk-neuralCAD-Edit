def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val() if hasattr(model, "val") else model

    solids = root.Solids()
    print(f"Model valid: {root.isValid()}; solids: {len(solids)}")

    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = bb.center
        print(
            f"SOLID {i}: volume={solid.Volume():.5f}, "
            f"bbox=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f}) to "
            f"({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f}), "
            f"center=({c.x:.3f},{c.y:.3f},{c.z:.3f}), faces={len(solid.Faces())}"
        )

    # The planning data identifies S03 as STEP solid 3. Inspect its analytic
    # faces and circular edges to recover the actual axis, sleeve radius,
    # shoulder elevations, and existing upper chamfer dimensions.
    if len(solids) > 3:
        target = solids[3]
        print("--- Detailed inspection of candidate S03 / solid 3 ---")
        for fi, face in enumerate(target.Faces()):
            ft = face.geomType()
            fc = face.Center()
            bb = face.BoundingBox()
            extra = ""
            try:
                adaptor = face._geomAdaptor()
                if ft == "CYLINDER":
                    cyl = adaptor.Cylinder()
                    axis = cyl.Axis().Direction()
                    loc = cyl.Location()
                    extra = (f", radius={cyl.Radius():.6f}, "
                             f"axis=({axis.X():.4f},{axis.Y():.4f},{axis.Z():.4f}), "
                             f"axis_loc=({loc.X():.4f},{loc.Y():.4f},{loc.Z():.4f})")
                elif ft == "CONE":
                    cone = adaptor.Cone()
                    axis = cone.Axis().Direction()
                    loc = cone.Location()
                    extra = (f", ref_radius={cone.RefRadius():.6f}, "
                             f"semi_angle={cone.SemiAngle():.8f}, "
                             f"axis=({axis.X():.4f},{axis.Y():.4f},{axis.Z():.4f}), "
                             f"axis_loc=({loc.X():.4f},{loc.Y():.4f},{loc.Z():.4f})")
            except Exception as exc:
                extra = f", adaptor_error={exc}"
            print(
                f"FACE {fi}: type={ft}, area={face.Area():.6f}, "
                f"center=({fc.x:.4f},{fc.y:.4f},{fc.z:.4f}), "
                f"bbox=({bb.xmin:.4f},{bb.ymin:.4f},{bb.zmin:.4f}) to "
                f"({bb.xmax:.4f},{bb.ymax:.4f},{bb.zmax:.4f}){extra}"
            )

        print("--- Circular edges of candidate S03 / solid 3 ---")
        for ei, edge in enumerate(target.Edges()):
            if edge.geomType() == "CIRCLE":
                ec = edge.Center()
                bb = edge.BoundingBox()
                try:
                    r = edge.radius()
                except Exception:
                    r = -1.0
                print(
                    f"EDGE {ei}: circle radius={r:.6f}, length={edge.Length():.6f}, "
                    f"center=({ec.x:.4f},{ec.y:.4f},{ec.z:.4f}), "
                    f"bbox=({bb.xmin:.4f},{bb.ymin:.4f},{bb.zmin:.4f}) to "
                    f"({bb.xmax:.4f},{bb.ymax:.4f},{bb.zmax:.4f})"
                )

    return model