def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Common

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    solids = list(model.val().Solids())

    if len(solids) < 18:
        raise ValueError("Expected at least 18 solids, found %d" % len(solids))

    # Identified from the source model and semantic plan:
    # SOLID 0  is the main appliance/coffeepot housing.
    # SOLID 17 is the external U-shaped handle/cradle.
    pot = solids[0]
    handle_original = solids[17]

    def common_volume(a, b):
        op = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
        op.SetFuzzyValue(1.0e-7)
        op.SetNonDestructive(True)
        op.Build()
        if not op.IsDone() or op.Shape().IsNull():
            return 0.0
        common_shape = cq.Shape.cast(op.Shape())
        return common_shape.Volume()

    def robust_cut(a, b):
        op = BRepAlgoAPI_Cut(a.wrapped, b.wrapped)
        op.SetFuzzyValue(1.0e-7)
        op.SetNonDestructive(True)
        op.Build()
        if not op.IsDone() or op.Shape().IsNull():
            raise ValueError("OCC failed to cut the handle with the clearance envelope")
        return cq.Shape.cast(op.Shape())

    initial_interference = common_volume(handle_original, pot)

    # Create a slightly enlarged copy of the pot solely as a cutting tool.
    # Uniform scaling about its bounding-box center gives a positive clearance
    # and avoids the unstable sequence of translated Boolean cuts used in the
    # previous iteration.
    clearance = max(0.0, float(args.get("clearance", 0.25)))
    bb = pot.BoundingBox()
    cx = 0.5 * (bb.xmin + bb.xmax)
    cy = 0.5 * (bb.ymin + bb.ymax)
    cz = 0.5 * (bb.zmin + bb.zmax)
    characteristic_radius = max(0.5 * bb.xlen, 0.5 * bb.ylen, 0.5 * bb.zlen)

    if characteristic_radius <= 0.0:
        raise ValueError("The coffeepot has an invalid bounding box")

    scale_factor = 1.0 + clearance / characteristic_radius
    clearance_tool = (
        pot.translate((-cx, -cy, -cz))
           .scale(scale_factor)
           .translate((cx, cy, cz))
    )

    envelope_overlap = common_volume(handle_original, clearance_tool)
    if envelope_overlap > 1.0e-9:
        handle_result = robust_cut(handle_original, clearance_tool)
    else:
        handle_result = handle_original

    handle_solids = list(handle_result.Solids())
    if not handle_solids:
        raise ValueError("The clearance operation removed the entire handle")

    remaining_interference = sum(common_volume(s, pot) for s in handle_solids)
    if remaining_interference > 1.0e-6:
        raise ValueError(
            "Handle-to-coffeepot interference remains: %.12f"
            % remaining_interference
        )

    # Replace only SOLID 17; all unrelated source solids are preserved.
    output_solids = solids[:17] + handle_solids + solids[18:]
    result = cq.Compound.makeCompound(output_solids)

    if not result.isValid():
        raise ValueError("The edited assembly is not a valid shape")

    removed_volume = handle_original.Volume() - sum(s.Volume() for s in handle_solids)
    print("SOURCE_SOLIDS=%d" % len(solids))
    print("HANDLE_POT_INITIAL_COMMON_VOLUME=%.12f" % initial_interference)
    print("CLEARANCE_REQUESTED=%.6f" % clearance)
    print("CLEARANCE_SCALE_FACTOR=%.12f" % scale_factor)
    print("HANDLE_ENVELOPE_OVERLAP=%.12f" % envelope_overlap)
    print("HANDLE_REMOVED_VOLUME=%.12f" % removed_volume)
    print("HANDLE_POT_FINAL_COMMON_VOLUME=%.12f" % remaining_interference)
    print("RESULT_VALID=%s RESULT_SOLIDS=%d" % (
        result.isValid(), len(result.Solids())
    ))

    return cq.Workplane("XY").newObject([result])