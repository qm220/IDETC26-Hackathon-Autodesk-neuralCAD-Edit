def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)

    solids = imported.solids().vals()
    if not solids:
        raise ValueError("The input STEP file contains no solid bodies")

    original = solids[0]
    for extra_solid in solids[1:]:
        original = original.fuse(extra_solid)
    original = original.clean()

    bbox = original.BoundingBox()

    end_faces = []
    tolerance = max(1.0e-5, bbox.xlen * 1.0e-7)
    for face in original.Faces():
        face_bbox = face.BoundingBox()
        if (face.geomType() == "PLANE" and
                face_bbox.xlen <= tolerance and
                abs(face_bbox.xmax - bbox.xmax) <= tolerance):
            end_faces.append(face)

    if not end_faces:
        raise ValueError("Could not identify the planar non-rounded terminal face")

    terminal_face = max(end_faces, key=lambda f: f.Area())
    mirror_x = terminal_face.Center().x

    mirrored = original.mirror(
        mirrorPlane="YZ",
        basePointVector=(mirror_x, 0.0, 0.0)
    )

    result = original.fuse(mirrored).clean()

    if not result.isValid():
        raise ValueError("The mirrored Boolean union produced an invalid shape")
    if len(result.Solids()) != 1:
        raise ValueError(
            f"Expected one unified solid after mirroring, found {len(result.Solids())}"
        )

    return cq.Workplane(obj=result)