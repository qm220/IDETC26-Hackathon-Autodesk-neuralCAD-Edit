def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val() if hasattr(imported, "val") else imported

    solids = source.Solids()
    if len(solids) != 2:
        raise ValueError("Expected the original two-solid sprocket assembly, found %d solids" % len(solids))

    # Ground the two components using the inspected radial envelopes rather than
    # relying on an unverified STEP solid order.
    solids = sorted(solids, key=lambda s: s.BoundingBox().xlen)
    insert = solids[0]
    carrier = solids[1]

    ib = insert.BoundingBox()
    cb = carrier.BoundingBox()
    print("=== GROUNDED ORIGINAL COMPONENTS ===")
    print("Insert: faces=%d volume=%.6f bbox=(%.4f, %.4f) (%.4f, %.4f) (%.4f, %.4f)" % (
        len(insert.Faces()), insert.Volume(), ib.xmin, ib.xmax, ib.ymin, ib.ymax, ib.zmin, ib.zmax))
    print("Carrier: faces=%d volume=%.6f bbox=(%.4f, %.4f) (%.4f, %.4f) (%.4f, %.4f)" % (
        len(carrier.Faces()), carrier.Volume(), cb.xmin, cb.xmax, cb.ymin, cb.ymax, cb.zmin, cb.zmax))

    # Inspection of FACE 224 and FACE 233 establishes the axial extent of the
    # flower-profiled rear part of the insert as y=-4.625 to y=0.175 mm.
    y0 = -4.625019
    y1 = 0.174981
    overlap = 0.002

    # Preserve the original fine internal spline exactly. A cylindrical envelope
    # minus the original insert extracts the existing central void as a cutter.
    void_envelope = cq.Solid.makeCylinder(
        12.0,
        9.0,
        cq.Vector(0, -5.0, 0),
        cq.Vector(0, 1, 0)
    )
    original_center_void = void_envelope.cut(insert)

    # Replace the eight-lobed external flower interface with a regular hexagonal
    # prism at the same center and over the same axial extent. The 29.0 mm size is
    # vertex-to-vertex, matching the inspected 14.5 mm maximum flower radius.
    insert_hex_diameter = 29.0
    insert_hex = (
        cq.Workplane("XZ", origin=(0, y1 + overlap, 0))
        .polygon(6, insert_hex_diameter)
        .extrude((y1 - y0) + 2.0 * overlap)
        .val()
    )
    insert_hex = insert_hex.cut(original_center_void)

    # Retain all original insert geometry on the cylindrical/front side. A slight
    # overlap at y=0.175 makes the retained part and replacement hex prism robustly
    # fuse into one insert solid.
    front_keep_box = cq.Solid.makeBox(
        40.0, 10.0, 40.0,
        cq.Vector(-20.0, y1 - overlap, -20.0)
    )
    insert_front = insert.intersect(front_keep_box)
    edited_insert = insert_front.fuse(insert_hex)

    # Replace the matching flower-shaped carrier socket as well. First add back
    # material around the old lobed cavity, then cut a slightly larger concentric
    # hexagon to provide assembly clearance without joining the two components.
    carrier_hex_diameter = 29.4
    carrier_hex_cutter = (
        cq.Workplane("XZ", origin=(0, y1 - 0.0005, 0))
        .polygon(6, carrier_hex_diameter)
        .extrude((y1 - y0) + 0.01)
        .val()
    )

    repair_cylinder = cq.Solid.makeCylinder(
        15.82,
        y1 - y0,
        cq.Vector(0, y0, 0),
        cq.Vector(0, 1, 0)
    )
    carrier_repair_ring = repair_cylinder.cut(carrier_hex_cutter)
    edited_carrier = carrier.fuse(carrier_repair_ring).cut(carrier_hex_cutter)

    if not edited_insert.isValid():
        raise ValueError("Edited hexagonal insert is invalid")
    if not edited_carrier.isValid():
        raise ValueError("Edited carrier is invalid")

    result = cq.Compound.makeCompound([edited_insert, edited_carrier])
    rb = result.BoundingBox()
    print("=== EDIT RESULT ===")
    print("Valid: %s" % result.isValid())
    print("Solids: %d, Faces: %d, Volume: %.6f" % (
        len(result.Solids()), len(result.Faces()), result.Volume()))
    print("Result bbox: x=[%.4f,%.4f] y=[%.4f,%.4f] z=[%.4f,%.4f]" % (
        rb.xmin, rb.xmax, rb.ymin, rb.ymax, rb.zmin, rb.zmax))
    print("Flower interface replaced by centered regular hexagon: insert %.3f mm, socket %.3f mm vertex-to-vertex" % (
        insert_hex_diameter, carrier_hex_diameter))

    return cq.Workplane("XY").newObject([result])