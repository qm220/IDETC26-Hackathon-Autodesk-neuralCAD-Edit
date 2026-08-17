def my_cad_function(args):
    import os
    import cadquery as cq

    rib_thickness = 1.5  # mm

    if "input_file" not in args:
        print("No input_file provided; cannot edit model.")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shp = model.val() if hasattr(model, "val") else model

    bbox = shp.BoundingBox()
    cx, cy, cz = bbox.center.x, bbox.center.y, bbox.center.z
    xlen, ylen, zlen = bbox.xlen, bbox.ylen, bbox.zlen

    print("Loaded STEP:", input_file)
    print(f"Valid: {shp.isValid()}")
    print(f"BBOX center=({cx:.3f},{cy:.3f},{cz:.3f})")
    print(f"BBOX lens x={xlen:.3f} y={ylen:.3f} z={zlen:.3f}")

    lens = {"X": xlen, "Y": ylen, "Z": zlen}
    long_axis = max(lens, key=lens.get)
    thick_axis = min(lens, key=lens.get)
    height_axis = ({"X", "Y", "Z"} - {long_axis, thick_axis}).pop()

    print(f"Chosen axes: long={long_axis}, rib_thickness_axis={thick_axis}, height={height_axis}")

    # Sketch plane is perpendicular to long axis
    if long_axis == "X":
        plane = "YZ"
        origin = (cx, 0, 0)
        u_axis, v_axis = "Y", "Z"
        long_len = xlen
    elif long_axis == "Y":
        plane = "XZ"
        origin = (0, cy, 0)
        u_axis, v_axis = "X", "Z"
        long_len = ylen
    else:
        plane = "XY"
        origin = (0, 0, cz)
        u_axis, v_axis = "X", "Y"
        long_len = zlen

    # Height direction uses hmin -> hmax (positive along that axis)
    hmin = getattr(bbox, height_axis.lower() + "min")
    hmax = getattr(bbox, height_axis.lower() + "max")
    hlen = lens[height_axis]

    tmin = getattr(bbox, thick_axis.lower() + "min")
    tmax = getattr(bbox, thick_axis.lower() + "max")

    # Rib length along long axis (extrusion distance)
    rib_length = max(6.0, min(0.70 * long_len, long_len - 0.6))
    # Rib height in the height_axis direction
    rib_height = max(4.0, min(0.55 * hlen, hlen - 0.6))

    eps = 0.10  # small overlap to ensure a clean boolean union
    h0 = hmin - eps

    print(f"Rib params: thickness={rib_thickness}mm, height={rib_height:.3f}mm, length={rib_length:.3f}mm")

    def _tri_points(thick_side_value, thick_dir_sign):
        # Build coordinate dict for the sketch plane axes (u_axis, v_axis)
        coord0 = {u_axis: None, v_axis: None}
        coord0[thick_axis] = thick_side_value
        coord0[height_axis] = h0

        p0 = (coord0[u_axis], coord0[v_axis])

        coord_t = dict(coord0)
        coord_t[thick_axis] = thick_side_value + thick_dir_sign * rib_thickness
        p1 = (coord_t[u_axis], coord_t[v_axis])

        coord_h = dict(coord0)
        coord_h[height_axis] = h0 + rib_height
        p2 = (coord_h[u_axis], coord_h[v_axis])

        return p0, p1, p2

    ribs = []
    # Add ribs on both sides of the thin (thickness) axis for symmetric reinforcement
    for side_name, t0, sgn in (
        ("min", tmin - eps, +1.0),
        ("max", tmax + eps, -1.0),
    ):
        p0, p1, p2 = _tri_points(t0, sgn)
        print(f"Rib@{thick_axis}{side_name}: tri {p0} -> {p1} -> {p2} on {plane}, extrude along {long_axis}")

        rib = (
            cq.Workplane(plane, origin=origin)
            .polyline([p0, p1, p2])
            .close()
            .extrude(rib_length / 2.0, both=True)
        )
        ribs.append(rib)

    rib_solid = ribs[0]
    for r in ribs[1:]:
        rib_solid = rib_solid.union(r)

    try:
        result = cq.Workplane(obj=shp).union(rib_solid)
    except Exception as e:
        print("Union via Workplane(obj=shp) failed; trying model.union. Error:", e)
        result = model.union(rib_solid)

    print("Added 1.5mm ribs (rib thickness is the small leg of the triangular cross-section).")
    return result
