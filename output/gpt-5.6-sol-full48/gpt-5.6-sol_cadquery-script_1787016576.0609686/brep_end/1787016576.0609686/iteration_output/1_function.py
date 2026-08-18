def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    root = model.val() if hasattr(model, "val") else model
    solids = list(root.Solids())

    if len(solids) != 9:
        raise ValueError(f"Expected 9 assembly solids, found {len(solids)}")

    # S03 is the heatbreak/interface-pin solid. Its largest cylindrical sleeve
    # has radius 3.45 mm and extends from z=7.5 to z=20.8 mm. The existing top
    # chamfer changes radius by 0.20 mm over 0.20 mm axially, so it is a 0.20 mm
    # equal-distance chamfer. Select the matching sharp lower circular edge.
    target = solids[3]

    class SleeveLowerEdgeSelector(cq.selectors.Selector):
        def filter(self, object_list):
            selected = []
            for edge in object_list:
                try:
                    bb = edge.BoundingBox()
                    if edge.geomType() != "CIRCLE":
                        continue
                    radius = edge.radius()
                    center = edge.Center()
                    if (
                        abs(radius - 3.45) < 1.0e-3
                        and abs(center.x) < 1.0e-3
                        and abs(center.y + 40.0) < 1.0e-3
                        and abs(center.z - 7.5) < 1.0e-3
                        and abs(bb.zmax - bb.zmin) < 1.0e-5
                        and edge.Length() > 20.0
                    ):
                        selected.append(edge)
                except Exception:
                    pass
            return selected

    selector = SleeveLowerEdgeSelector()
    selected_edges = selector.filter(target.Edges())
    if len(selected_edges) != 1:
        raise ValueError(
            "Could not uniquely identify the lower edge of the heatbreak's "
            f"largest cylindrical sleeve; selected {len(selected_edges)} edges"
        )

    chamfer_size = 0.20
    modified_target = (
        cq.Workplane(obj=target)
        .edges(selector)
        .chamfer(chamfer_size)
        .val()
    )

    if not modified_target.isValid():
        raise ValueError("Heatbreak solid became invalid after chamfering")

    # Restore the complete exploded assembly, replacing only S03.
    output_solids = [modified_target if i == 3 else solid for i, solid in enumerate(solids)]
    output = cq.Compound.makeCompound(output_solids)

    print(
        "Added a 0.20 mm equal-distance chamfer to the lower edge of the "
        "heatbreak's R3.45 mm main sleeve, matching its existing top chamfer."
    )
    print(f"Output valid: {output.isValid()}; solids: {len(output.Solids())}")
    print(
        f"Heatbreak volume: {target.Volume():.6f} -> "
        f"{modified_target.Volume():.6f} mm^3"
    )

    # Confirm that a new conical face exists at the lower sleeve edge.
    lower_cones = []
    for face in modified_target.Faces():
        if face.geomType() == "CONE":
            bb = face.BoundingBox()
            if bb.zmin >= 7.49 and bb.zmax <= 7.71:
                lower_cones.append(face)
    print(f"Lower sleeve chamfer cone faces found: {len(lower_cones)}")

    return cq.Workplane(obj=output)