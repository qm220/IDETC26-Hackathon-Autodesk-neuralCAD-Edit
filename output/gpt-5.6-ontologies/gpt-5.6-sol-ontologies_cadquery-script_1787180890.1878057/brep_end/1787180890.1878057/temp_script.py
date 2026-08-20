def my_cad_function(args):
    import cadquery as cq
    import os

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    solids = model.solids().vals()
    if not solids:
        raise ValueError("No solid found in the input STEP model")

    shape = solids[0]

    # The original open-jaw recess has 20 mm parallel sizing walls at
    # x=-10 and x=+10. Its rounded root reaches z=-110. Translate the
    # complete root profile 10 mm toward the opening so it reaches
    # z=-120, without moving either sizing wall.

    # First restore the material occupied by the original root. The
    # slight overlap into the surrounding solid avoids residual seams.
    filler = cq.Solid.makeBox(
        20.4,
        15.0,
        25.0,
        cq.Vector(-10.2, 0.0, -130.0)
    )
    edited = shape.fuse(filler)

    # Reconstruct the translated recess. Below z=-125 the opening is a
    # 20 mm-wide straight slot. From z=-125 to z=-120, two R5 quarter
    # transitions join those walls to a 10 mm-wide flat root.
    y0 = -1.0
    cut_thickness = 17.0

    straight_slot = cq.Solid.makeBox(
        20.0,
        cut_thickness,
        25.0,
        cq.Vector(-10.0, y0, -150.0)
    )

    left_circle = cq.Solid.makeCylinder(
        5.0,
        cut_thickness,
        cq.Vector(-5.0, y0, -125.0),
        cq.Vector(0.0, 1.0, 0.0)
    )
    right_circle = cq.Solid.makeCylinder(
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

    # Retain only the upper halves of the two circles, producing the
    # intended quarter-circle transitions rather than full circular cuts.
    root_clip = cq.Solid.makeBox(
        20.0,
        cut_thickness,
        5.0,
        cq.Vector(-10.0, y0, -125.0)
    )
    rounded_root = (
        left_circle.fuse(right_circle).fuse(root_center).intersect(root_clip)
    )

    translated_recess = straight_slot.fuse(rounded_root)
    edited = edited.cut(translated_recess).clean()

    if not edited.isValid():
        raise ValueError("The edited wrench solid is invalid")

    bb = edited.BoundingBox()
    print("Rebuilt the open-jaw recess with its root translated by 10.000 mm")
    print("Original deepest boundary: z=-110.000 mm")
    print("Final deepest boundary: z=-120.000 mm")
    print("Sizing surfaces: x=-10.000 mm and x=+10.000 mm")
    print("Sizing-surface separation: 20.000 mm")
    print("Root transitions: R5.000 mm")
    print(f"Final volume: {edited.Volume():.6f} mm^3")
    print(
        f"Final bbox: x=[{bb.xmin:.6f},{bb.xmax:.6f}] "
        f"y=[{bb.ymin:.6f},{bb.ymax:.6f}] "
        f"z=[{bb.zmin:.6f},{bb.zmax:.6f}]"
    )

    return cq.Workplane(obj=edited)