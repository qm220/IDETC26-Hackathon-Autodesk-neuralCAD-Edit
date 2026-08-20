def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    result = model.val() if hasattr(model, "val") else model

    # The unique non-filleted end is the planar face at maximum X.
    bbox = result.BoundingBox()
    end_x = bbox.xmax
    axis_y = 0.5 * (11.0 + 23.0)
    axis_z = 0.5 * (2.0 + 6.0)

    # Eight equally spaced annular cylindrical bearing elements. Their axes
    # are parallel to the bearing axis (global X), and their centers revolve
    # around that axis on the non-filleted end face.
    instance_count = 8
    pattern_radius = 1.40
    bearing_outer_radius = 0.50
    bearing_inner_radius = 0.24
    bearing_length = 3.50
    axis_direction = cq.Vector(1.0, 0.0, 0.0)

    bearing_centers = []
    for index in range(instance_count):
        angle = 2.0 * math.pi * index / instance_count
        center_y = axis_y + pattern_radius * math.cos(angle)
        center_z = axis_z + pattern_radius * math.sin(angle)
        base = cq.Vector(end_x, center_y, center_z)

        outer = cq.Solid.makeCylinder(
            bearing_outer_radius,
            bearing_length,
            base,
            axis_direction
        )
        bore = cq.Solid.makeCylinder(
            bearing_inner_radius,
            bearing_length,
            base,
            axis_direction
        )
        bearing = outer.cut(bore)
        result = result.fuse(bearing)
        bearing_centers.append((center_y, center_z))

    try:
        result = result.clean()
    except Exception:
        pass

    print("=== BEARING PATTERN ===")
    print(f"Non-filleted end plane: X={end_x:.6f}")
    print(f"Bearing axis: origin=({end_x:.6f}, {axis_y:.6f}, {axis_z:.6f}), direction=(1,0,0)")
    print(f"Total cylindrical bearing instances: {instance_count}")
    print(f"Angular spacing: {360.0 / instance_count:.1f} degrees")
    print(f"Pattern radius: {pattern_radius:.3f}")
    print(f"Bearing OD/ID/length: {2*bearing_outer_radius:.3f}/{2*bearing_inner_radius:.3f}/{bearing_length:.3f}")
    for index, (center_y, center_z) in enumerate(bearing_centers):
        print(f"Instance {index + 1}: angle={index * 360.0 / instance_count:.1f} deg, center=({end_x:.3f},{center_y:.3f},{center_z:.3f})")
    print(f"Result valid: {result.isValid()}")
    print(f"Result solids: {len(result.Solids())}")

    return cq.Workplane("XY").newObject([result])