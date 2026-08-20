def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    imported_shape = imported.val()

    solids = imported_shape.Solids()
    if not solids:
        raise ValueError("The input STEP file contains no solids")
    base = solids[0]
    original_bbox = base.BoundingBox()

    nominal_radius = 10.0
    hole_edges = []
    for edge in base.Edges():
        try:
            if edge.geomType() == "CIRCLE" and abs(edge.radius() - nominal_radius) < 0.05:
                hole_edges.append(edge)
        except Exception:
            pass

    if not hole_edges:
        raise ValueError("Could not locate the original ring-end cylindrical hole")

    center_x = sum(edge.Center().x for edge in hole_edges) / len(hole_edges)
    center_z = sum(edge.Center().z for edge in hole_edges) / len(hole_edges)
    hole_radius = sum(edge.radius() for edge in hole_edges) / len(hole_edges)

    y_min = original_bbox.ymin
    y_max = original_bbox.ymax
    part_thickness = y_max - y_min

    fill_overlap = 0.02
    fill_cylinder = cq.Solid.makeCylinder(
        hole_radius + fill_overlap,
        part_thickness,
        cq.Vector(center_x, y_min, center_z),
        cq.Vector(0, 1, 0),
    )
    restored = base.fuse(fill_cylinder)

    cut_margin = 1.0
    cut_y = y_min - cut_margin
    cut_length = part_thickness + 2.0 * cut_margin
    vertices = []
    for i in range(6):
        angle = math.radians(90.0 + 60.0 * i)
        vertices.append(cq.Vector(
            center_x + hole_radius * math.cos(angle),
            cut_y,
            center_z + hole_radius * math.sin(angle),
        ))
    vertices.append(vertices[0])

    hex_wire = cq.Wire.makePolygon(vertices)
    hex_face = cq.Face.makeFromWires(hex_wire)
    hex_tool = cq.Solid.extrudeLinear(hex_face, cq.Vector(0, cut_length, 0))
    result = restored.cut(hex_tool)

    if not result.isValid():
        raise ValueError("The edited wrench is not a valid solid")

    result_solids = result.Solids()
    if len(result_solids) != 1:
        raise ValueError("Expected one monolithic solid, found {}".format(len(result_solids)))

    result_bbox = result.BoundingBox()
    bbox_values = (
        (original_bbox.xmin, result_bbox.xmin),
        (original_bbox.xmax, result_bbox.xmax),
        (original_bbox.ymin, result_bbox.ymin),
        (original_bbox.ymax, result_bbox.ymax),
        (original_bbox.zmin, result_bbox.zmin),
        (original_bbox.zmax, result_bbox.zmax),
    )
    if any(abs(a - b) > 1.0e-5 for a, b in bbox_values):
        raise ValueError("The operation unexpectedly changed the exterior envelope")

    return cq.Workplane("XY").newObject([result_solids[0]])