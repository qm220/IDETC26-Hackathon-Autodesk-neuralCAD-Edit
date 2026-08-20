def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val() if hasattr(model, "val") else model

    print("=== Imported STEP inspection ===")
    print(f"Valid: {root.isValid()}")
    print(f"Total solids: {len(root.Solids())}")
    print(f"Total faces: {len(root.Faces())}")

    solids = root.Solids()
    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = bb.center
        print(
            f"SOLID {i}: faces={len(solid.Faces())}, volume={solid.Volume():.6f}, "
            f"bbox=({bb.xmin:.4f},{bb.ymin:.4f},{bb.zmin:.4f})-"
            f"({bb.xmax:.4f},{bb.ymax:.4f},{bb.zmax:.4f}), "
            f"center=({c.x:.4f},{c.y:.4f},{c.z:.4f})"
        )

    # Ground R04/F004 by inspecting the planned global STEP face range.
    faces = root.Faces()
    start_id = 737
    end_id = min(775, len(faces) - 1)
    print(f"=== R04/F004 candidate faces: FACE {start_id}-{end_id} ===")

    for face_id in range(start_id, end_id + 1):
        face = faces[face_id]
        gt = face.geomType()
        center = face.Center()
        bb = face.BoundingBox()
        details = []
        try:
            adaptor = face._geomAdaptor()
            if gt == "CYLINDER":
                cyl = adaptor.Cylinder()
                details.append(f"radius={cyl.Radius():.6f}")
                d = cyl.Axis().Direction()
                details.append(f"axis=({d.X():.5f},{d.Y():.5f},{d.Z():.5f})")
            elif gt == "CONE":
                cone = adaptor.Cone()
                details.append(f"ref_radius={cone.RefRadius():.6f}")
                details.append(f"semi_angle={cone.SemiAngle():.8f}")
                d = cone.Axis().Direction()
                details.append(f"axis=({d.X():.5f},{d.Y():.5f},{d.Z():.5f})")
        except Exception as exc:
            details.append(f"surface_detail_error={exc}")

        circular_edges = []
        for edge in face.Edges():
            if edge.geomType() == "CIRCLE":
                ec = edge.Center()
                try:
                    er = edge.radius()
                except Exception:
                    er = -1.0
                circular_edges.append(
                    f"r={er:.6f}@({ec.x:.4f},{ec.y:.4f},{ec.z:.4f})"
                )

        print(
            f"FACE {face_id}: type={gt}, center=({center.x:.4f},{center.y:.4f},{center.z:.4f}), "
            f"bbox=({bb.xmin:.4f},{bb.ymin:.4f},{bb.zmin:.4f})-"
            f"({bb.xmax:.4f},{bb.ymax:.4f},{bb.zmax:.4f}), "
            f"details=[{'; '.join(details)}], circles=[{'; '.join(circular_edges)}]"
        )

    # Also inspect the topology directly owned by planned SOLID 3 so global face
    # indices can be checked against actual imported-solid ordering.
    if len(solids) > 3:
        target = solids[3]
        print("=== Direct SOLID 3 face inspection ===")
        for local_id, face in enumerate(target.Faces()):
            gt = face.geomType()
            fc = face.Center()
            extra = ""
            try:
                if gt == "CYLINDER":
                    extra = f", radius={face._geomAdaptor().Cylinder().Radius():.6f}"
                elif gt == "CONE":
                    cone = face._geomAdaptor().Cone()
                    extra = f", ref_radius={cone.RefRadius():.6f}, semi_angle={cone.SemiAngle():.8f}"
            except Exception as exc:
                extra = f", detail_error={exc}"

            circles = []
            for edge in face.Edges():
                if edge.geomType() == "CIRCLE":
                    ec = edge.Center()
                    try:
                        radius = edge.radius()
                    except Exception:
                        radius = -1.0
                    circles.append(f"r={radius:.6f}@({ec.x:.4f},{ec.y:.4f},{ec.z:.4f})")
            print(
                f"SOLID3_FACE {local_id}: type={gt}, center=({fc.x:.4f},{fc.y:.4f},{fc.z:.4f})"
                f"{extra}, circles=[{'; '.join(circles)}]"
            )

    # Inspection iteration: preserve and return the original model unchanged.
    return model