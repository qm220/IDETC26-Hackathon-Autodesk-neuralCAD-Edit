def my_cad_function(args):
    import os
    import math
    import statistics
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source = imported.val() if hasattr(imported, "val") else imported
    source_bb = source.BoundingBox()

    # Find an axial level passing through the unchanged inner and outer walls.
    wall_intervals = []
    for face in source.Faces():
        try:
            if face.geomType() != "PLANE":
                continue
            bb = face.BoundingBox()
            if bb.zlen <= 1.0e-5:
                continue
            wall_intervals.append((bb.zmin, bb.zmax))
        except Exception:
            pass

    if wall_intervals:
        section_min = max(v[0] for v in wall_intervals)
        section_max = min(v[1] for v in wall_intervals)
    else:
        section_min = source_bb.zmin
        section_max = source_bb.zmax

    if section_max > section_min + 1.0e-4:
        section_z = 0.5 * (section_min + section_max)
    else:
        section_z = source_bb.zmin + 0.5 * source_bb.zlen

    section = cq.Workplane("XY").newObject([source]).section(height=section_z)
    wires = [w for w in section.wires().vals() if w.IsClosed()]
    if len(wires) < 2:
        raise ValueError("Could not recover the inner and outer frame footprints")

    wires.sort(
        key=lambda w: w.BoundingBox().xlen * w.BoundingBox().ylen,
        reverse=True,
    )
    outer_wire = wires[0]
    inner_wire = wires[1]
    obb = outer_wire.BoundingBox()
    ibb = inner_wire.BoundingBox()

    outer_w = obb.xlen
    outer_h = obb.ylen
    inner_w = ibb.xlen
    inner_h = ibb.ylen
    cx = 0.5 * (obb.xmin + obb.xmax)
    cy = 0.5 * (obb.ymin + obb.ymax)
    zmin = source_bb.zmin
    zmax = source_bb.zmax
    depth = zmax - zmin

    def loop_radius(wire, fallback):
        radii = []
        for edge in wire.Edges():
            try:
                if edge.geomType() == "CIRCLE":
                    r = float(edge.radius())
                    if r > 1.0e-4:
                        radii.append(r)
            except Exception:
                pass
        return float(statistics.median(radii)) if radii else float(fallback)

    # These are plan-view corner radii and must remain unchanged.
    outer_r = min(loop_radius(outer_wire, 63.0), 0.499 * outer_w, 0.499 * outer_h)
    inner_r = min(loop_radius(inner_wire, 50.0), 0.499 * inner_w, 0.499 * inner_h)

    def rounded_rectangle(width, height, radius, z):
        hw = 0.5 * width
        hh = 0.5 * height
        s = radius / math.sqrt(2.0)
        return (
            cq.Workplane("XY", origin=(cx, cy, z))
            .moveTo(-hw + radius, -hh)
            .lineTo(hw - radius, -hh)
            .threePointArc(
                (hw - radius + s, -hh + radius - s),
                (hw, -hh + radius),
            )
            .lineTo(hw, hh - radius)
            .threePointArc(
                (hw - radius + s, hh - radius + s),
                (hw - radius, hh),
            )
            .lineTo(-hw + radius, hh)
            .threePointArc(
                (-hw + radius - s, hh - radius + s),
                (-hw, hh - radius),
            )
            .lineTo(-hw, -hh + radius)
            .threePointArc(
                (-hw + radius - s, -hh + radius - s),
                (-hw + radius, -hh),
            )
            .close()
        )

    outer = rounded_rectangle(outer_w, outer_h, outer_r, zmin).extrude(depth).val()
    cutter_margin = max(1.0, 0.1 * depth)
    inner = (
        rounded_rectangle(inner_w, inner_h, inner_r, zmin - cutter_margin)
        .extrude(depth + 2.0 * cutter_margin)
        .val()
    )
    sharp_frame = outer.cut(inner).clean()
    if not sharp_frame.isValid():
        raise ValueError("Reconstructed sharp annular frame is invalid")

    target_radius = 2.0

    # Boundary edges of an extrusion are exactly planar in Z. Selecting them
    # by their bounding boxes avoids dependence on face-normal API behavior.
    def axial_end_edges(solid, side=None):
        bb = solid.BoundingBox()
        scale = max(bb.xlen, bb.ylen, bb.zlen, 1.0)
        tol = max(1.0e-5, scale * 1.0e-7)
        selected = []
        for edge in solid.Edges():
            ebb = edge.BoundingBox()
            if ebb.zlen > tol:
                continue
            ez = 0.5 * (ebb.zmin + ebb.zmax)
            if side == "top" and abs(ez - bb.zmax) > tol:
                continue
            if side == "bottom" and abs(ez - bb.zmin) > tol:
                continue
            if side is None and min(abs(ez - bb.zmin), abs(ez - bb.zmax)) > tol:
                continue
            selected.append(edge)
        return selected

    errors = []
    result = None

    # Prefer one operation so all four cross-sectional corners receive exactly
    # the same R2 treatment and all transitions are solved together.
    all_end_edges = axial_end_edges(sharp_frame)
    try:
        if not all_end_edges:
            raise ValueError("No axial end boundary edges were detected")
        candidate = sharp_frame.fillet(target_radius, all_end_edges).clean()
        if not candidate.isValid():
            raise ValueError("The simultaneous R2 fillet result is invalid")
        result = candidate
    except Exception as exc:
        errors.append("simultaneous: " + str(exc))

    # OCC fallback: process the two axial ends separately, reselecting edges
    # from the current solid after the first operation.
    if result is None:
        for order in (("top", "bottom"), ("bottom", "top")):
            try:
                candidate = sharp_frame
                counts = []
                for side in order:
                    edges = axial_end_edges(candidate, side)
                    counts.append(len(edges))
                    if not edges:
                        raise ValueError("No %s boundary edges were detected" % side)
                    candidate = candidate.fillet(target_radius, edges).clean()
                if not candidate.isValid():
                    raise ValueError("The sequential R2 fillet result is invalid")
                result = candidate
                print("Sequential end-edge counts:", counts)
                break
            except Exception as exc:
                errors.append("%s: %s" % (" then ".join(order), str(exc)))

    if result is None:
        raise ValueError("Uniform R2 profile reconstruction failed: " + " | ".join(errors))

    print("Source envelope:", source_bb.xlen, source_bb.ylen, source_bb.zlen)
    print("Recovered footprints:", outer_w, outer_h, inner_w, inner_h)
    print("Preserved plan-view radii:", outer_r, inner_r)
    print("Detected axial end edges:", len(all_end_edges))
    print("All four cross-sectional edge radii set to R2")
    print("Result valid:", result.isValid())

    return cq.Workplane("XY").newObject([result])