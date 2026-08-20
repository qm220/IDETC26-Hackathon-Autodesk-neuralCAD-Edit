def my_cad_function(args):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    import math
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    model = imported.val() if hasattr(imported, "val") else imported
    faces = model.Faces()

    print(f"Loaded STEP: {input_file}")
    print(f"Valid: {model.isValid()}, solids: {len(model.Solids())}, faces: {len(faces)}")

    cylindrical = {}
    for i, face in enumerate(faces):
        center = face.Center()
        bbox = face.BoundingBox()
        geom_type = face.geomType()
        message = (
            f"FACE {i}: type={geom_type}, "
            f"center=({center.x:.6f}, {center.y:.6f}, {center.z:.6f}), "
            f"bbox=({bbox.xmin:.6f},{bbox.ymin:.6f},{bbox.zmin:.6f})-"
            f"({bbox.xmax:.6f},{bbox.ymax:.6f},{bbox.zmax:.6f}), area={face.Area():.6f}"
        )

        if geom_type == "CYLINDER":
            adaptor = BRepAdaptor_Surface(face.wrapped)
            cylinder = adaptor.Cylinder()
            radius = float(cylinder.Radius())
            direction = cylinder.Axis().Direction()
            location = cylinder.Axis().Location()
            axis = cq.Vector(direction.X(), direction.Y(), direction.Z()).normalized()
            point = cq.Vector(location.X(), location.Y(), location.Z())
            cylindrical[i] = {
                "face": face,
                "radius": radius,
                "axis": axis,
                "point": point,
            }
            message += (
                f", radius={radius:.6f}, "
                f"axis=({axis.x:.6f},{axis.y:.6f},{axis.z:.6f}), "
                f"axis_point=({point.x:.6f},{point.y:.6f},{point.z:.6f})"
            )
        print(message)

    def dot(a, b):
        return a.x * b.x + a.y * b.y + a.z * b.z

    def coaxial(a, b):
        alignment = abs(dot(a["axis"], b["axis"]))
        delta = b["point"] - a["point"]
        along = dot(delta, a["axis"])
        radial = delta - a["axis"] * along
        radius_tolerance = max(1.0e-4, 1.0e-3 * max(a["radius"], b["radius"]))
        line_tolerance = max(1.0e-4, 1.0e-3 * max(a["radius"], b["radius"]))
        return (
            alignment > 0.9999
            and radial.Length < line_tolerance
            and abs(a["radius"] - b["radius"]) < radius_tolerance
        )

    # Bind the planned FACE 0 and FACE 1 references to their inspected STEP faces.
    selected_ids = None
    if 0 in cylindrical and 1 in cylindrical and coaxial(cylindrical[0], cylindrical[1]):
        selected_ids = (0, 1)
    else:
        # Defensive fallback: locate the smallest-radius coaxial cylindrical pair,
        # which corresponds to the two aligned bearing bores rather than outer lugs.
        pairs = []
        ids = sorted(cylindrical.keys())
        for n, first_id in enumerate(ids):
            for second_id in ids[n + 1:]:
                first = cylindrical[first_id]
                second = cylindrical[second_id]
                if coaxial(first, second):
                    pairs.append((0.5 * (first["radius"] + second["radius"]), first_id, second_id))
        if not pairs:
            raise ValueError("Could not identify a coaxial pair of cylindrical bearing faces")
        pairs.sort()
        _, first_id, second_id = pairs[0]
        selected_ids = (first_id, second_id)

    bore_a = cylindrical[selected_ids[0]]
    bore_b = cylindrical[selected_ids[1]]
    hole_radius = 0.5 * (bore_a["radius"] + bore_b["radius"])
    axis = bore_a["axis"]
    axis_point = bore_a["point"]

    # Use a practical running clearance derived from the existing bore size.
    radial_clearance = max(0.05, min(0.20, hole_radius * 0.02))
    pin_radius = hole_radius - radial_clearance
    if pin_radius <= 0:
        raise ValueError("Resolved pin radius is not positive")

    # Resolve pin length from the complete transverse extent of the unchanged part.
    # Projection is used instead of assuming a global X/Y/Z orientation.
    vertices = model.Vertices()
    projections = [dot(vertex.Center(), axis) for vertex in vertices]
    if not projections:
        bbox = model.BoundingBox()
        corners = [
            cq.Vector(x, y, z)
            for x in (bbox.xmin, bbox.xmax)
            for y in (bbox.ymin, bbox.ymax)
            for z in (bbox.zmin, bbox.zmax)
        ]
        projections = [dot(corner, axis) for corner in corners]

    extent_min = min(projections)
    extent_max = max(projections)
    protrusion = max(0.5, pin_radius * 0.30)
    pin_start_projection = extent_min - protrusion
    pin_length = (extent_max - extent_min) + 2.0 * protrusion
    axis_point_projection = dot(axis_point, axis)
    pin_start = axis_point + axis * (pin_start_projection - axis_point_projection)

    pin = cq.Solid.makeCylinder(pin_radius, pin_length, pin_start, axis)
    if not pin.isValid():
        raise ValueError("Generated clevis pin is invalid")

    print(
        f"Selected bearing faces: FACE {selected_ids[0]} and FACE {selected_ids[1]}"
    )
    print(
        f"Bearing radius={hole_radius:.6f} mm; radial clearance={radial_clearance:.6f} mm; "
        f"pin diameter={2.0 * pin_radius:.6f} mm; pin length={pin_length:.6f} mm"
    )
    print(
        f"Pin start=({pin_start.x:.6f},{pin_start.y:.6f},{pin_start.z:.6f}); "
        f"axis=({axis.x:.6f},{axis.y:.6f},{axis.z:.6f})"
    )

    # Keep the pin as a separate assembly component so the original part is
    # geometrically unchanged and can rotate around the clearance-fit pin.
    result = cq.Assembly(name="hooked_clevis_with_pin")
    result.add(model, name="original_hooked_clevis", color=cq.Color(0.72, 0.72, 0.76))
    result.add(pin, name="clevis_pin", color=cq.Color(0.88, 0.62, 0.16))
    return result
