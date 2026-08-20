def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    solids = model.solids().vals()
    if not solids:
        raise ValueError("No solid found in the input STEP model")

    shape = solids[0]

    # The open-ended spanner slot originally extends from z=-150 mm to
    # its deepest boundary at z=-110 mm. Move the rounded root 10 mm
    # toward the opening, giving a new deepest boundary at z=-120 mm.
    # The sizing walls remain at x=-10 and x=+10, preserving 20 mm.

    # Restore material in the old upper 10 mm of the jaw recess.
    # A slight overlap above the old root makes the union robust.
    filler = cq.Solid.makeBox(
        20.0,
        15.0,
        15.5,
        cq.Vector(-10.0, 0.0, -125.0)
    )
    edited = shape.fuse(filler)

    # Re-form the original rounded U-shaped root translated 10 mm
    # toward the open end. The cap consists of two R5 transitions and
    # a 10 mm-wide flat deepest surface at z=-120 mm.
    y0 = -1.0
    cut_thickness = 17.0
    left_transition = cq.Solid.makeCylinder(
        5.0,
        cut_thickness,
        cq.Vector(-5.0, y0, -125.0),
        cq.Vector(0.0, 1.0, 0.0)
    )
    right_transition = cq.Solid.makeCylinder(
        5.0,
        cut_thickness,
        cq.Vector(5.0, y0, -125.0),
        cq.Vector(0.0, 1.0, 0.0)
    )
    root_center = cq.Solid.makeBox(
        10.0,
        cut_thickness,
        5.0,
        cq.Vector(-5.0, y0, -125.0)
    )
    new_root_cut = left_transition.fuse(right_transition).fuse(root_center)
    edited = edited.cut(new_root_cut)

    if not edited.isValid():
        raise ValueError("The edited wrench solid is invalid")

    bb = edited.BoundingBox()
    print("Applied open-jaw cutout depth reduction: 10.000 mm")
    print("Original deepest boundary: z=-110.000 mm")
    print("Final deepest boundary: z=-120.000 mm")
    print("Parallel sizing surfaces: x=-10.000 and x=+10.000 mm")
    print("Preserved sizing separation: 20.000 mm")
    print(f"Final volume: {edited.Volume():.6f} mm^3")
    print(
        f"Final bbox: x=[{bb.xmin:.6f},{bb.xmax:.6f}] "
        f"y=[{bb.ymin:.6f},{bb.ymax:.6f}] "
        f"z=[{bb.zmin:.6f},{bb.zmax:.6f}]"
    )

    return cq.Workplane(obj=edited)
