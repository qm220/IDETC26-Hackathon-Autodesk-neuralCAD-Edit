def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val()

    solids = list(original.Solids())
    if len(solids) < 3:
        raise ValueError("Expected the source model to contain at least three solids")

    # The central hub is the compact solid; both arm solids have a much larger span.
    def maximum_span(shape):
        bb = shape.BoundingBox()
        return max(bb.xlen, bb.ylen, bb.zlen)

    hub = min(solids, key=maximum_span)
    hub_bb = hub.BoundingBox()
    z_min = hub_bb.zmin
    z_max = hub_bb.zmax

    # Find the largest rounded-square outer loop on a face normal to Z. This is
    # the hub skirt's complete outer contour rather than the smaller inset cap.
    candidates = []
    for face in hub.Faces():
        if face.geomType() != "PLANE":
            continue
        try:
            normal = face.normalAt()
        except Exception:
            continue
        if abs(normal.z) < 0.95:
            continue

        outer_wire = face.outerWire()
        wire_bb = outer_wire.BoundingBox()
        footprint = wire_bb.xlen * wire_bb.ylen
        candidates.append((footprint, face.Area(), face, outer_wire))

    if not candidates:
        raise ValueError("Could not find a Z-normal planar hub face for the cover contour")

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, reference_face, reference_wire = candidates[0]

    wire_bb = reference_wire.BoundingBox()
    reference_z = 0.5 * (wire_bb.zmin + wire_bb.zmax)
    thickness = 2.54  # 0.254 cm in millimetres

    positive_wire = reference_wire.translate(cq.Vector(0, 0, z_max - reference_z))
    negative_wire = reference_wire.translate(cq.Vector(0, 0, z_min - reference_z))

    positive_cover = cq.Solid.extrudeLinear(
        positive_wire, [], cq.Vector(0, 0, thickness)
    )
    negative_cover = cq.Solid.extrudeLinear(
        negative_wire, [], cq.Vector(0, 0, -thickness)
    )

    if not positive_cover.isValid() or not negative_cover.isValid():
        raise ValueError("One or both generated cover solids are invalid")

    # A compound preserves the original three bodies and keeps both new covers
    # as independent parts despite their coincident seating faces.
    result = cq.Compound.makeCompound([original, positive_cover, negative_cover])

    print("Original solid count:", len(solids))
    print("Selected hub bounds:", hub_bb.xlen, hub_bb.ylen, hub_bb.zlen)
    print("Cover contour bounds:", wire_bb.xlen, wire_bb.ylen)
    print("Cover seating Z positions:", z_min, z_max)
    print("Created two separate covers, each 2.54 mm thick")
    print("Result solid count:", len(result.Solids()))

    return cq.Workplane(obj=result)