def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    original = model.val()
    bbox = original.BoundingBox()

    # Canonical +X view: +Y is right and +Z is top. The existing circular
    # interface bosses at these two corners provide suitable matching port
    # geometry but are capped. Bore them axially through the radiator tank to
    # create one functional outlet and one functional inlet while preserving
    # all other geometry.
    outlet_center = (152.4, 231.1)    # top-right: (Y, Z)
    inlet_center = (-152.4, -233.7)   # bottom-left: (Y, Z)

    bore_radius = 9.5
    cutter_x0 = bbox.xmin - 5.0
    cutter_length = bbox.xlen + 50.0

    cutters = []
    for y, z in (outlet_center, inlet_center):
        cutters.append(
            cq.Solid.makeCylinder(
                bore_radius,
                cutter_length,
                cq.Vector(cutter_x0, y, z),
                cq.Vector(1, 0, 0)
            )
        )

    edited = original
    for cutter in cutters:
        edited = edited.cut(cutter)

    result = cq.Workplane(obj=edited)

    eb = edited.BoundingBox()
    print("Created axial outlet bore at top-right (Y=%.1f, Z=%.1f), radius=%.1f" % (
        outlet_center[0], outlet_center[1], bore_radius))
    print("Created axial inlet bore at bottom-left (Y=%.1f, Z=%.1f), radius=%.1f" % (
        inlet_center[0], inlet_center[1], bore_radius))
    print("RESULT BBOX: x=[%.3f, %.3f], y=[%.3f, %.3f], z=[%.3f, %.3f]" % (
        eb.xmin, eb.xmax, eb.ymin, eb.ymax, eb.zmin, eb.zmax))
    print("RESULT: valid=%s solids=%d faces=%d volume=%.3f" % (
        edited.isValid(), len(edited.Solids()), len(edited.Faces()), edited.Volume()))

    return result