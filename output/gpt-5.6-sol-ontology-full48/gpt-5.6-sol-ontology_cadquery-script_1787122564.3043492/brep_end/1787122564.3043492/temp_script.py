def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported

    solids = list(model.Solids())
    faces = list(model.Faces())
    print("Loaded STEP: solids=%d faces=%d valid=%s" % (len(solids), len(faces), model.isValid()))

    # Inspect and bind the planned global B-rep faces before editing.
    for idx in range(526, 532):
        if idx < len(faces):
            f = faces[idx]
            bb = f.BoundingBox()
            c = f.Center()
            print(
                "FACE %d type=%s area=%.6f center=(%.6f, %.6f, %.6f) "
                "bbox=(%.6f, %.6f, %.6f)-(%.6f, %.6f, %.6f)" % (
                    idx, f.geomType(), f.Area(), c.x, c.y, c.z,
                    bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax
                )
            )

    # Prefer the grounded hand-grip wall and terminal face. If STEP ordering is
    # different, recover the same geometry from its dimensions and position.
    grip_face = faces[528] if len(faces) > 528 else None
    end_face = faces[529] if len(faces) > 529 else None

    grounded_ok = False
    if grip_face is not None and end_face is not None:
        gbb = grip_face.BoundingBox()
        ebb = end_face.BoundingBox()
        grounded_ok = (
            grip_face.geomType() == "CYLINDER" and
            end_face.geomType() == "PLANE" and
            gbb.zlen > 90.0 and
            abs(ebb.zlen) < 1.0e-4
        )

    if not grounded_ok:
        print("Grounded indices did not match expected topology; scanning actual geometry.")
        grip_face = None
        for i, f in enumerate(faces):
            if f.geomType() != "CYLINDER":
                continue
            bb = f.BoundingBox()
            if (100.0 <= bb.zlen <= 106.0 and
                    28.0 <= bb.xlen <= 31.0 and
                    28.0 <= bb.ylen <= 31.0 and
                    bb.zmax > 400.0):
                grip_face = f
                print("Recovered lever grip as FACE %d" % i)
                break
        if grip_face is None:
            raise ValueError("Could not localize the radius-14.62 mm vertical lever grip")

        gbb = grip_face.BoundingBox()
        gx = 0.5 * (gbb.xmin + gbb.xmax)
        gy = 0.5 * (gbb.ymin + gbb.ymax)
        end_face = None
        for i, f in enumerate(faces):
            if f.geomType() != "PLANE":
                continue
            bb = f.BoundingBox()
            c = f.Center()
            if (abs(bb.zmin - gbb.zmax) < 1.0e-3 and
                    abs(bb.zmax - gbb.zmax) < 1.0e-3 and
                    abs(c.x - gx) < 1.0e-2 and
                    abs(c.y - gy) < 1.0e-2 and
                    600.0 < f.Area() < 750.0):
                end_face = f
                print("Recovered lever terminal face as FACE %d" % i)
                break
        if end_face is None:
            raise ValueError("Could not localize the planar free end of the lever")

    grip_bb = grip_face.BoundingBox()
    end_bb = end_face.BoundingBox()
    end_center = end_face.Center()
    original_end_z = 0.5 * (end_bb.zmin + end_bb.zmax)

    math = __import__("math")
    radius = math.sqrt(end_face.Area() / math.pi)
    if not (14.0 <= radius <= 15.2):
        radius = 0.25 * (grip_bb.xlen + grip_bb.ylen)

    print(
        "Bound lever grip: center=(%.6f, %.6f), radius=%.6f, "
        "original end z=%.6f, requested end z=%.6f" % (
            end_center.x, end_center.y, radius,
            original_end_z, original_end_z + 50.0
        )
    )

    # Find the assembly solid that owns the grounded cylindrical grip face.
    target_solid_index = None
    best_score = None
    for si, solid in enumerate(solids):
        sbb = solid.BoundingBox()
        if not (sbb.zmin < original_end_z and abs(sbb.zmax - original_end_z) < 1.0e-2):
            continue
        for sf in solid.Faces():
            if sf.geomType() != "CYLINDER":
                continue
            bb = sf.BoundingBox()
            score = (
                abs(bb.xmin - grip_bb.xmin) + abs(bb.xmax - grip_bb.xmax) +
                abs(bb.ymin - grip_bb.ymin) + abs(bb.ymax - grip_bb.ymax) +
                abs(bb.zmin - grip_bb.zmin) + abs(bb.zmax - grip_bb.zmax)
            )
            if best_score is None or score < best_score:
                best_score = score
                target_solid_index = si

    if target_solid_index is None or best_score is None or best_score > 0.1:
        raise ValueError("Could not associate the grounded grip face with its lever solid")

    target_solid = solids[target_solid_index]
    print("Lever associated with SOLID %d; face match score=%.9f" % (target_solid_index, best_score))

    # Extend only the free cylindrical hand-grip portion. A tiny overlap makes
    # the Boolean robust while retaining the exact requested terminal z value.
    overlap = 0.02
    extension = cq.Solid.makeCylinder(
        radius,
        50.0 + overlap,
        cq.Vector(end_center.x, end_center.y, original_end_z - overlap),
        cq.Vector(0, 0, 1)
    )
    edited_lever = target_solid.fuse(extension).clean()

    if not edited_lever.isValid():
        raise ValueError("Extended lever Boolean result is invalid")

    edited_bb = edited_lever.BoundingBox()
    expected_zmax = original_end_z + 50.0
    print(
        "Edited lever bbox z=(%.6f, %.6f); extension=%.6f mm; valid=%s" % (
            edited_bb.zmin, edited_bb.zmax,
            edited_bb.zmax - original_end_z, edited_lever.isValid()
        )
    )
    if abs(edited_bb.zmax - expected_zmax) > 1.0e-3:
        raise ValueError("Lever extension did not terminate at the requested z coordinate")

    # Replace SOLID 55 in the imported assembly-like compound, preserving every
    # other independent component and the lever's unchanged mounting geometry.
    output_solids = []
    for si, solid in enumerate(solids):
        output_solids.append(edited_lever if si == target_solid_index else solid)

    result = cq.Compound.makeCompound(output_solids)
    print("Output: solids=%d valid=%s" % (len(result.Solids()), result.isValid()))
    return result