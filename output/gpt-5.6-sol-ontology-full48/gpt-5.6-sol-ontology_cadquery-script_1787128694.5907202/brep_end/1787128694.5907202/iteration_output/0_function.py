def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = shape.Solids()
    all_faces = shape.Faces()

    print("=== STEP INSPECTION ===")
    print(f"valid={shape.isValid()} solids={len(solids)} faces={len(all_faces)} volume={shape.Volume():.6f}")

    # Bind the planning FACE N identifiers to the imported global face list.
    face_index = {f.hashCode(): i for i, f in enumerate(all_faces)}

    for si, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = bb.center
        print(
            f"SOLID {si}: faces={len(solid.Faces())} volume={solid.Volume():.6f} "
            f"bbox=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f}) to "
            f"({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f}) "
            f"center=({c.x:.3f},{c.y:.3f},{c.z:.3f})"
        )

    def global_id(face):
        h = face.hashCode()
        if h in face_index:
            return face_index[h]
        # Hash lookup normally succeeds; geometric equality is a fallback.
        for i, af in enumerate(all_faces):
            try:
                if face.isSame(af):
                    return i
            except Exception:
                pass
        return -1

    # Inspect the two principal housings. In particular, report all planar
    # rear-wall candidates and Y-directed cylindrical mounting-hole topology.
    for si in (0, 1):
        solid = solids[si]
        sbb = solid.BoundingBox()
        print(f"\n=== SOLID {si} REAR-INTERFACE CANDIDATES ===")
        for face in solid.Faces():
            gi = global_id(face)
            gt = face.geomType()
            bb = face.BoundingBox()
            cm = face.Center()
            area = face.Area()

            if gt == "PLANE":
                try:
                    n = face.normalAt(cm)
                except Exception:
                    try:
                        n = face.normalAt()
                    except Exception:
                        continue
                # Planes parallel to XZ and near either Y envelope are useful
                # for confirming FACE 145/FACE 466 and the -Y rear wall.
                near_y_envelope = (
                    abs(bb.ymin - sbb.ymin) < 0.6 or
                    abs(bb.ymax - sbb.ymax) < 0.6
                )
                if abs(n.y) > 0.90 and near_y_envelope:
                    print(
                        f"FACE {gi} PLANE area={area:.5f} "
                        f"center=({cm.x:.4f},{cm.y:.4f},{cm.z:.4f}) "
                        f"normal=({n.x:.4f},{n.y:.4f},{n.z:.4f}) "
                        f"bbox=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f})-"
                        f"({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f})"
                    )

            elif gt == "CYLINDER":
                radius = None
                axis = None
                origin = None
                try:
                    cyl = face._geomAdaptor().Cylinder()
                    radius = cyl.Radius()
                    ax = cyl.Axis()
                    d = ax.Direction()
                    p = ax.Location()
                    axis = (d.X(), d.Y(), d.Z())
                    origin = (p.X(), p.Y(), p.Z())
                except Exception as exc:
                    print(f"FACE {gi} CYLINDER adaptor_error={exc}")
                    continue

                # Mounting holes normal to the rear wall have Y-directed axes.
                if abs(axis[1]) > 0.90:
                    print(
                        f"FACE {gi} CYLINDER r={radius:.5f} area={area:.5f} "
                        f"axis=({axis[0]:.4f},{axis[1]:.4f},{axis[2]:.4f}) "
                        f"origin=({origin[0]:.4f},{origin[1]:.4f},{origin[2]:.4f}) "
                        f"center=({cm.x:.4f},{cm.y:.4f},{cm.z:.4f}) "
                        f"bbox=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f})-"
                        f"({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f})"
                    )

            elif gt == "CONE":
                # Rear-hole countersinks may be conical. Report those whose
                # extent reaches the minimum-Y side.
                if bb.ymin < sbb.ymin + 3.0:
                    print(
                        f"FACE {gi} CONE area={area:.5f} "
                        f"center=({cm.x:.4f},{cm.y:.4f},{cm.z:.4f}) "
                        f"bbox=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f})-"
                        f"({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f})"
                    )

    # Explicitly print the grounded datum faces to confirm that global STEP
    # indices agree with model.json after import.
    print("\n=== GROUNDED FACE CHECK ===")
    for gi in (145, 219, 221, 251, 462, 464, 466, 482, 484, 518):
        if gi >= len(all_faces):
            continue
        face = all_faces[gi]
        bb = face.BoundingBox()
        cm = face.Center()
        print(
            f"FACE {gi}: type={face.geomType()} area={face.Area():.5f} "
            f"center=({cm.x:.4f},{cm.y:.4f},{cm.z:.4f}) "
            f"bbox=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f})-"
            f"({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f})"
        )

    return model