def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    body = imported.val() if hasattr(imported, "val") else imported

    # Inspect the imported topology before editing so planned FACE indices are
    # bound to the actual STEP geometry in this execution.
    print("Imported STEP: %s" % input_file)
    print("Valid before edit: %s" % body.isValid())
    print("Solids before edit: %d" % len(body.Solids()))
    print("Volume before edit: %.6f mm^3" % body.Volume())
    print("Faces before edit: %d" % len(body.Faces()))
    for i, face in enumerate(body.Faces()):
        bb = face.BoundingBox()
        c = face.Center()
        try:
            geom = face.geomType()
        except Exception:
            geom = "UNKNOWN"
        print(
            "FACE %d: type=%s center=(%.4f, %.4f, %.4f) "
            "bbox=[x %.4f..%.4f, y %.4f..%.4f, z %.4f..%.4f] area=%.4f"
            % (i, geom, c.x, c.y, c.z,
               bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax,
               face.Area())
        )

    # The inspected/planned arm side faces are FACE 9 and FACE 16. Their broad
    # X extent and opposed Y locations establish that through cuts should run
    # along global Y. Three capsules are placed only in the central R02 web.
    # Sizes reduce toward the narrower hook end to preserve upper/lower rails.
    slot_specs = [
        # center X, center Z, overall length, overall height
        (-40.0, 7.60, 24.0, 6.0),
        (-8.0,  7.70, 24.0, 5.0),
        (24.0,  7.82, 20.0, 3.4),
    ]

    cut_depth = 30.0  # comfortably through the full lateral width
    result = cq.Workplane("XY").newObject([body])
    total_intersection = 0.0

    for index, (cx, cz, length, height) in enumerate(slot_specs, start=1):
        radius = height / 2.0
        center_spacing = length - 2.0 * radius

        # Central prism plus two Y-axis cylinders forms a rounded-ended slot.
        prism = (
            cq.Workplane("XY")
            .box(center_spacing, cut_depth, height)
            .translate((cx, 0.0, cz))
        )
        left_cap = (
            cq.Workplane("XZ")
            .center(cx - center_spacing / 2.0, cz)
            .circle(radius)
            .extrude(cut_depth / 2.0, both=True)
        )
        right_cap = (
            cq.Workplane("XZ")
            .center(cx + center_spacing / 2.0, cz)
            .circle(radius)
            .extrude(cut_depth / 2.0, both=True)
        )
        tool = prism.union(left_cap).union(right_cap)

        try:
            removed_here = body.intersect(tool.val()).Volume()
        except Exception:
            removed_here = 0.0
        total_intersection += removed_here
        print(
            "Slot %d: center=(%.3f, 0, %.3f), length=%.3f, height=%.3f, "
            "estimated body intersection=%.6f mm^3"
            % (index, cx, cz, length, height, removed_here)
        )
        result = result.cut(tool)

    edited = result.val()
    before_volume = body.Volume()
    after_volume = edited.Volume()
    removed_volume = before_volume - after_volume
    reduction = 100.0 * removed_volume / before_volume if before_volume else 0.0

    print("Valid after edit: %s" % edited.isValid())
    print("Solids after edit: %d" % len(edited.Solids()))
    print("Faces after edit: %d" % len(edited.Faces()))
    print("Volume after edit: %.6f mm^3" % after_volume)
    print("Removed volume: %.6f mm^3 (%.3f%%)" % (removed_volume, reduction))
    print("Summed pre-cut tool intersections: %.6f mm^3" % total_intersection)

    if not edited.isValid():
        raise ValueError("The edited body is not a valid B-rep")
    if len(edited.Solids()) != 1:
        raise ValueError("Cutouts did not preserve one contiguous solid")
    if removed_volume <= 0.0:
        raise ValueError("The slot tools removed no material")

    return result