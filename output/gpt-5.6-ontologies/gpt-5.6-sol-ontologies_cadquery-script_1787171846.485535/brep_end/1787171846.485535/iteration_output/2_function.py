def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()
    original_solids = list(original.Solids())

    if not original_solids:
        raise ValueError("The input STEP file contains no solids")

    # The largest solid is the integrated radiator body, tanks, shroud, and
    # corner interface bosses. The remaining solids are separate blades and
    # fittings and must not participate in the port booleans.
    body_index = max(
        range(len(original_solids)),
        key=lambda i: original_solids[i].Volume()
    )
    body = original_solids[body_index]
    bb = body.BoundingBox()

    # Canonical +X/front view: +Y is right and +Z is top. These centers match
    # the existing capped circular interface bosses at the requested corners.
    outlet_center = (152.4, 231.1)     # (Y, Z), top-right
    inlet_center = (-152.4, -233.7)    # (Y, Z), bottom-left
    bore_radius = 9.5

    # Extend beyond both X sides of the body so each bore opens reliably into
    # the corresponding tank. Only the main body solid is cut; this avoids the
    # invalid fragmented compound produced by cutting the entire assembly.
    cutter_x0 = bb.xmin - 5.0
    cutter_length = bb.xlen + 10.0

    edited_body = body
    for y, z in (outlet_center, inlet_center):
        cutter = cq.Solid.makeCylinder(
            bore_radius,
            cutter_length,
            cq.Vector(cutter_x0, y, z),
            cq.Vector(1, 0, 0)
        )
        edited_body = edited_body.cut(cutter)

    # Reassemble the edited body with every untouched original solid. Do not
    # fuse the assembly, since the source model intentionally contains
    # discrete fan blades and external fittings.
    result_shapes = []
    for i, solid in enumerate(original_solids):
        if i == body_index:
            result_shapes.extend(list(edited_body.Solids()))
        else:
            result_shapes.append(solid)

    result_shape = cq.Compound.makeCompound(result_shapes)
    result = cq.Workplane(obj=result_shape)

    valid_children = sum(1 for s in result_shapes if s.isValid())
    rb = result_shape.BoundingBox()
    print("INPUT: solids=%d main_body_index=%d main_body_volume=%.3f" % (
        len(original_solids), body_index, body.Volume()))
    print("Created outlet bore at top-right Y=%.1f Z=%.1f radius=%.1f" % (
        outlet_center[0], outlet_center[1], bore_radius))
    print("Created inlet bore at bottom-left Y=%.1f Z=%.1f radius=%.1f" % (
        inlet_center[0], inlet_center[1], bore_radius))
    print("RESULT BBOX: x=[%.3f, %.3f], y=[%.3f, %.3f], z=[%.3f, %.3f]" % (
        rb.xmin, rb.xmax, rb.ymin, rb.ymax, rb.zmin, rb.zmax))
    print("RESULT: compound_valid=%s valid_children=%d/%d solids=%d faces=%d volume=%.3f" % (
        result_shape.isValid(), valid_children, len(result_shapes),
        len(result_shape.Solids()), len(result_shape.Faces()), result_shape.Volume()))

    return result