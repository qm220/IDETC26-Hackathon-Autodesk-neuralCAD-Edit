def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()
    solids = list(source_shape.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    primary_index = max(range(len(solids)), key=lambda i: solids[i].Volume())
    primary = solids[primary_index]
    bb = primary.BoundingBox()

    # Identify the broad fan-facing +X radiator/shroud surface. The fan guards
    # extend farther in +X, so only large planar X-normal faces are considered.
    broad_x_faces = []
    for face in primary.Faces():
        try:
            if face.geomType() == "PLANE" and face.Area() > 10000.0:
                normal = face.normalAt()
                if abs(normal.x) > 0.9:
                    broad_x_faces.append(face.Center().x)
        except Exception:
            pass

    if broad_x_faces:
        front_x = max(broad_x_faces)
    else:
        front_x = bb.xmin + 0.36 * (bb.xmax - bb.xmin)

    # In the fan-facing +X view, +Y is screen-right and +Z is screen-top.
    # These locations remain visibly diagonal while moving farther away from
    # the two preserved corner mounting bosses than in the prior iteration.
    right_y = min(115.0, bb.ymax - 50.0)
    left_y = max(-115.0, bb.ymin + 50.0)
    top_z = min(235.0, bb.zmax - 30.0)
    bottom_z = max(-235.0, bb.zmin + 30.0)

    axis = cq.Vector(1, 0, 0)
    root_x = front_x - 8.0

    collar_radius = 13.0
    neck_radius = 9.0
    barb_radius = 11.0
    bore_radius = 5.0
    projection = 38.0

    def make_port_outer(y, z):
        # Overlapping primitive stages make one manufacturable hose fitting:
        # a tank-side flange, straight neck, retention barb, and end land.
        collar = cq.Solid.makeCylinder(
            collar_radius, 11.0, cq.Vector(root_x, y, z), axis
        )
        neck = cq.Solid.makeCylinder(
            neck_radius, 29.0, cq.Vector(root_x + 7.0, y, z), axis
        )
        barb_rise = cq.Solid.makeCone(
            neck_radius, barb_radius, 5.0,
            cq.Vector(root_x + 24.0, y, z), axis
        )
        barb_fall = cq.Solid.makeCone(
            barb_radius, neck_radius, 5.0,
            cq.Vector(root_x + 29.0, y, z), axis
        )
        end_land = cq.Solid.makeCylinder(
            neck_radius, 5.0, cq.Vector(root_x + 33.0, y, z), axis
        )
        return collar.fuse(neck).fuse(barb_rise).fuse(barb_fall).fuse(end_land)

    def make_bore(y, z):
        # Starts inside the radiator-side wall and exits beyond the hose end,
        # producing a continuous open passage after the union operation.
        return cq.Solid.makeCylinder(
            bore_radius,
            projection + 15.0,
            cq.Vector(root_x - 10.0, y, z),
            axis,
        )

    inlet_outer = make_port_outer(left_y, bottom_z)
    outlet_outer = make_port_outer(right_y, top_z)
    inlet_bore = make_bore(left_y, bottom_z)
    outlet_bore = make_bore(right_y, top_z)

    # Integrate both fittings into the main radiator solid before drilling the
    # passages. This avoids the intersecting loose-shell compound produced by
    # the previous implementation and gives each port a sealed tank interface.
    integrated = False
    edited_primary = primary
    loose_ports = []
    try:
        candidate = primary.fuse(inlet_outer)
        candidate = candidate.fuse(outlet_outer)
        candidate = candidate.cut(inlet_bore)
        candidate = candidate.cut(outlet_bore)
        candidate_solids = list(candidate.Solids())
        if candidate_solids and candidate.Volume() > primary.Volume():
            edited_primary = candidate
            integrated = True
        else:
            raise ValueError("Integrated port boolean produced no usable solid")
    except Exception as exc:
        print("Integrated port boolean fallback:", exc)

        # Fallback still supplies genuinely hollow fittings. Their roots end on
        # the selected radiator face rather than deeply overlapping the source
        # B-rep, reducing compound self-intersection if the imported solid does
        # not support reliable boolean modification.
        fallback_root = front_x - 0.05

        def make_fallback_shell(y, z):
            flange = cq.Solid.makeCylinder(
                collar_radius, 7.0, cq.Vector(fallback_root, y, z), axis
            )
            tube = cq.Solid.makeCylinder(
                neck_radius, projection - 3.0,
                cq.Vector(fallback_root + 3.0, y, z), axis
            )
            barb1 = cq.Solid.makeCone(
                neck_radius, barb_radius, 5.0,
                cq.Vector(fallback_root + 25.0, y, z), axis
            )
            barb2 = cq.Solid.makeCone(
                barb_radius, neck_radius, 5.0,
                cq.Vector(fallback_root + 30.0, y, z), axis
            )
            outer = flange.fuse(tube).fuse(barb1).fuse(barb2)
            bore = cq.Solid.makeCylinder(
                bore_radius, projection + 2.0,
                cq.Vector(fallback_root - 1.0, y, z), axis
            )
            return outer.cut(bore)

        loose_ports = [
            make_fallback_shell(left_y, bottom_z),
            make_fallback_shell(right_y, top_z),
        ]

    # Remove the redundant original adjacent coolant fittings only. Preserve
    # all fan blades, grilles, mounts, frame geometry, service cap, and core.
    remove_indices = {15, 16}
    output_shapes = []
    for index, solid in enumerate(solids):
        if index in remove_indices:
            continue
        if index == primary_index:
            output_shapes.extend(list(edited_primary.Solids()))
        else:
            output_shapes.append(solid)

    output_shapes.extend(loose_ports)
    result = cq.Compound.makeCompound(output_shapes)

    print("Primary solid index:", primary_index)
    print("Selected fan-facing radiator X:", round(front_x, 3))
    print("Removed original fitting solids:", sorted(remove_indices))
    print("Inlet center Y,Z:", round(left_y, 3), round(bottom_z, 3))
    print("Outlet center Y,Z:", round(right_y, 3), round(top_z, 3))
    print("Port axis: +X")
    print("Port OD/barb OD/bore/projection:", 2 * neck_radius, 2 * barb_radius, 2 * bore_radius, projection)
    print("Ports integrated and wall passages opened:", integrated)
    print("Result solid count:", len(result.Solids()))
    print("Result valid:", result.isValid())
    return result