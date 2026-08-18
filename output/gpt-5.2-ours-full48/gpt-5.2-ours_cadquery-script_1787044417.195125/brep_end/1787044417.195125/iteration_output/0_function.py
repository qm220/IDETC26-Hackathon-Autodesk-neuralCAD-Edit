def my_cad_function(args):
    import cadquery as cq
    import os

    thickness = 2.54  # mm (0.254 cm)

    if "input_file" not in args:
        raise ValueError("Missing args['input_file'] for STEP import")

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)

    # Get underlying OCC shape
    if hasattr(model, "val"):
        base_shape = model.val()
    elif isinstance(model, cq.Assembly):
        base_shape = model.toCompound()
    else:
        base_shape = model

    if not hasattr(base_shape, "Faces"):
        raise ValueError("Imported shape does not expose Faces(); cannot proceed")

    faces = list(base_shape.Faces())
    planar_faces = [f for f in faces if getattr(f, "geomType", lambda: None)() == "PLANE"]

    print(f"Imported faces: {len(faces)}; planar faces: {len(planar_faces)}")
    bbox = base_shape.BoundingBox()
    print(f"BBox y-range: {bbox.ymin:.3f} .. {bbox.ymax:.3f}")

    if len(planar_faces) == 0:
        raise ValueError("No planar faces found; cannot identify clamp top/bottom faces")

    # Identify clamp block top/bottom outer faces by extreme center Y among planar faces
    def cy(face):
        return face.Center().y

    top_face = max(planar_faces, key=cy)
    bottom_face = min(planar_faces, key=cy)

    print(f"Top face center y: {top_face.Center().y:.3f}")
    print(f"Bottom face center y: {bottom_face.Center().y:.3f}")

    # Build cover faces by reusing outer + inner loops of the clamp's top/bottom faces
    def make_cover_solid_from_face(src_face, extrude_vec):
        outer = src_face.outerWire()
        inners = list(src_face.innerWires())
        cover_face = cq.Face.makeFromWires(outer, inners)
        # Extrude outward from the clamp face
        return cq.Solid.extrudeLinear(cover_face, extrude_vec)

    cover_upper = make_cover_solid_from_face(top_face, cq.Vector(0, thickness, 0))
    cover_lower = make_cover_solid_from_face(bottom_face, cq.Vector(0, -thickness, 0))

    # Return as an assembly so the two covers remain separate parts from the base
    assy = cq.Assembly(name="Cross_strut_clamp_with_covers")
    assy.add(base_shape, name="Base")
    assy.add(cover_upper, name="Cover_Upper", color=cq.Color(0.8, 0.8, 0.85))
    assy.add(cover_lower, name="Cover_Lower", color=cq.Color(0.8, 0.8, 0.85))

    return assy
