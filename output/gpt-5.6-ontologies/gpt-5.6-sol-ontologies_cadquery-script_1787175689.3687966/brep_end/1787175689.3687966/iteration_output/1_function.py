def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Plane

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()

    if not original.isValid():
        raise ValueError("The imported STEP shape is invalid")

    # Locate the large all-around profile fillet. Its straight portions are
    # cylindrical surfaces of radius 10 and its corner portions are toroidal
    # surfaces with minor radius 10. The other profile fillets have radius 2.
    large_fillet_faces = []
    planar_faces = []

    for face in original.Faces():
        surf = BRepAdaptor_Surface(face.wrapped, True)
        surface_type = surf.GetType()

        if surface_type == GeomAbs_Cylinder:
            if abs(surf.Cylinder().Radius() - 10.0) < 1.0e-5:
                large_fillet_faces.append(face)
        elif surface_type == GeomAbs_Torus:
            if abs(surf.Torus().MinorRadius() - 10.0) < 1.0e-5:
                large_fillet_faces.append(face)
        elif surface_type == GeomAbs_Plane:
            planar_faces.append(face)

    if len(large_fillet_faces) != 8:
        raise ValueError(
            "Expected 8 faces belonging to the radius-10 perimeter fillet, found %d"
            % len(large_fillet_faces)
        )

    # The seating face adjoining the radius-10 fillet is the smallest planar
    # face in the original model. Retain its plane definition so that the
    # corresponding extended face can be recovered after defeaturing.
    target_plane_face = min(planar_faces, key=lambda f: f.Area())
    target_plane_point = target_plane_face.Center()
    target_plane_normal = target_plane_face.normalAt().normalized()

    # Remove the complete radius-10 fillet and extend its neighboring seating
    # and outer-wall faces to their sharp intersection.
    defeater = BRepAlgoAPI_Defeaturing()
    defeater.SetShape(original.wrapped)
    for face in large_fillet_faces:
        defeater.AddFaceToRemove(face.wrapped)
    defeater.Build()

    if not defeater.IsDone():
        raise RuntimeError("OCC failed to remove the radius-10 perimeter fillet")

    sharp_shape = cq.Shape.cast(defeater.Shape())
    if not sharp_shape.isValid():
        raise RuntimeError("Shape became invalid after removing the large fillet")

    # Find the extended planar seating face on the same plane as the original
    # face. It contains an inner and outer rounded-rectangle wire.
    coplanar_faces = []
    for face in sharp_shape.Faces():
        surf = BRepAdaptor_Surface(face.wrapped, True)
        if surf.GetType() != GeomAbs_Plane:
            continue

        center = face.Center()
        plane_distance = abs((center - target_plane_point).dot(target_plane_normal))
        normal_alignment = abs(face.normalAt().normalized().dot(target_plane_normal))
        if plane_distance < 1.0e-4 and normal_alignment > 0.9999:
            coplanar_faces.append(face)

    if not coplanar_faces:
        raise RuntimeError("Could not locate the extended seating face after defeaturing")

    seating_face = max(coplanar_faces, key=lambda f: f.Area())
    seating_wires = seating_face.Wires()
    if len(seating_wires) < 2:
        raise RuntimeError(
            "Expected the extended seating face to contain inner and outer wires"
        )

    # The longer wire is the restored sharp outer perimeter. Replace the
    # removed radius-10 fillet with the common radius used by all other
    # cross-sectional profile fillets: 2 units.
    outer_wire = max(seating_wires, key=lambda w: w.Length())
    perimeter_edges = outer_wire.Edges()

    fillet_builder = BRepFilletAPI_MakeFillet(sharp_shape.wrapped)
    for edge in perimeter_edges:
        fillet_builder.Add(2.0, edge.wrapped)
    fillet_builder.Build()

    if not fillet_builder.IsDone():
        raise RuntimeError("OCC failed to create the replacement radius-2 fillet")

    edited = cq.Shape.cast(fillet_builder.Shape())
    if not edited.isValid():
        raise RuntimeError("Replacement fillet produced an invalid shape")

    # Validate that no radius-10 profile surfaces remain and report all
    # cylindrical/toroidal radii for review.
    radius_10_faces = 0
    profile_radii = []
    for face in edited.Faces():
        surf = BRepAdaptor_Surface(face.wrapped, True)
        surface_type = surf.GetType()
        if surface_type == GeomAbs_Cylinder:
            radius = surf.Cylinder().Radius()
            profile_radii.append(("cylinder", radius))
            if abs(radius - 10.0) < 1.0e-5:
                radius_10_faces += 1
        elif surface_type == GeomAbs_Torus:
            radius = surf.Torus().MinorRadius()
            profile_radii.append(("torus_minor", radius))
            if abs(radius - 10.0) < 1.0e-5:
                radius_10_faces += 1

    print("Removed large-fillet faces:", len(large_fillet_faces))
    print("Replacement perimeter edges:", len(perimeter_edges))
    print("Result valid=%s volume=%.6f faces=%d" % (
        edited.isValid(), edited.Volume(), len(edited.Faces())
    ))
    print("Remaining radius-10 fillet surfaces:", radius_10_faces)
    print("Curved surface radii:", profile_radii)

    if radius_10_faces != 0:
        raise RuntimeError("Radius-10 surfaces remain after the requested edit")

    return cq.Workplane(obj=edited)
