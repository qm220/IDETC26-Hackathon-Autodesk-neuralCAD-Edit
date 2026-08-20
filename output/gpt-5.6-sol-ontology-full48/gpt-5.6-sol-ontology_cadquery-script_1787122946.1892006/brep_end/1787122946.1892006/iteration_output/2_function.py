def my_cad_function(args):
    import os
    import cadquery as cq

    model = cq.importers.importStep(os.path.expanduser(args["input_file"])).val()
    faces = model.Faces()
    solids = model.Solids()

    rear_face = faces[14]
    rear_bounds = rear_face.BoundingBox()
    width, height, radius, depth = 200.0, 100.0, 10.0, 30.0
    x_center = (rear_bounds.xmin + rear_bounds.xmax) / 2.0
    clearance = (rear_bounds.xlen - width) / 2.0
    z_center = rear_bounds.zmin + clearance + height / 2.0
    rear_y = (rear_bounds.ymin + rear_bounds.ymax) / 2.0

    plane = cq.Plane(
        origin=(x_center, rear_y - 0.1, z_center),
        xDir=(1, 0, 0),
        normal=(0, 1, 0)
    )
    extrusion = depth + 0.1
    tools = [
        cq.Workplane(plane).rect(width - 2 * radius, height).extrude(extrusion).val(),
        cq.Workplane(plane).rect(width, height - 2 * radius).extrude(extrusion).val()
    ]

    cx = width / 2.0 - radius
    cz = height / 2.0 - radius
    for x in (-cx, cx):
        for z in (-cz, cz):
            tools.append(
                cq.Workplane(plane).center(x, z).circle(radius).extrude(extrusion).val()
            )

    output = []
    for index, solid in enumerate(solids):
        edited = solid
        if index < 9:
            for tool in tools:
                edited = edited.cut(tool)
        resulting_solids = edited.Solids()
        output.extend(resulting_solids if resulting_solids else [edited])

    return cq.Compound.makeCompound(output)
