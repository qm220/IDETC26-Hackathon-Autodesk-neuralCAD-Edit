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

    # Locate the original cylindrical ring-end opening from its circular edges.
    target_radius = 10.0
    circular_edges = []
    for edge in base.Edges():
        try:
            if edge.geomType() == "CIRCLE":
                radius = edge.radius()
                if abs(radius - target_radius) < 0.05:
                    circular_edges.append(edge)
        except Exception:
            pass

    if not circular_edges:
        raise ValueError("Could not locate the original 10 mm radius ring-end hole")

    # The hole axis is the wrench thickness direction (global Y). Average the
    # matching top and bottom circular edge centers to recover its X/Z center.
    centers = [edge.Center() for edge in circular_edges]
    center_x = sum(c.x for c in centers) / len(centers)
    center_z = sum(c.z for c in centers) / len(centers)

    bbox = base.BoundingBox()
    y_start = bbox.ymin - 1.0
    through_length = (bbox.ymax - bbox.ymin) + 2.0

    print("Located original ring hole:")
    print("  center X/Z: ({:.6f}, {:.6f}) mm".format(center_x, center_z))
    print("  original radius: {:.6f} mm".format(target_radius))
    print("  wrench Y thickness: {:.6f} mm".format(bbox.ymax - bbox.ymin))

    # Restore the material removed by the old circular cut. A tiny radial
    # overlap avoids a coincident-face boolean while leaving the exterior
    # geometry untouched because this cylinder remains inside the ring boss.
    fill_cylinder = cq.Solid.makeCylinder(
        target_radius + 0.01,
        through_length,
        cq.Vector(center_x, y_start, center_z),
        cq.Vector(0, 1, 0),
    )
    restored = base.fuse(fill_cylinder)

    # Create a regular hexagon inscribed in the original R10 circle. The
    # custom vertex sequence places one opposite vertex pair on the wrench's
    # longitudinal Z centerline, as specified in the operation plan.
    vertices = []
    for i in range(6):
        angle = math.radians(90.0 + 60.0 * i)
        vertices.append(
            (
                center_x + target_radius * math.cos(angle),
                y_start,
                center_z + target_radius * math.sin(angle),
            )
        )
    vertices.append(vertices[0])

    hex_wire = cq.Wire.makePolygon([cq.Vector(*p) for p in vertices])
    hex_face = cq.Face.makeFromWires(hex_wire)
    hex_cut = cq.Solid.extrudeLinear(
        hex_face,
        cq.Vector(0, through_length, 0),
    )

    result = restored.cut(hex_cut)

    if not result.isValid():
        raise ValueError("The edited wrench is not a valid solid")

    result_solids = result.Solids()
    if len(result_solids) != 1:
        raise ValueError("Expected one monolithic solid, found {}".format(len(result_solids)))

    print("Replaced the cylindrical ring opening with an inscribed regular hexagonal through-cut.")
    print("Hexagon circumradius: 10.000000 mm")
    print("Hexagon across flats: {:.6f} mm".format(target_radius * math.sqrt(3.0)))
    print("Result valid: {}".format(result.isValid()))

    return cq.Workplane("XY").newObject([result_solids[0]])