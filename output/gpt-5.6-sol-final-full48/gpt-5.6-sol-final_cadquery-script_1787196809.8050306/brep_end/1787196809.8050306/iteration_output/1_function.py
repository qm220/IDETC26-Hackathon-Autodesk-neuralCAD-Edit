def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()
    solids = list(source_shape.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    # Solid 0 is the integrated radiator, frame, shrouds, and fan guards.
    # Solids 15 and 16 are the redundant original coolant fittings described
    # by the source-model analysis. All fan blades, mounts, and the cap remain.
    primary_index = max(range(len(solids)), key=lambda i: solids[i].Volume())
    primary = solids[primary_index]
    bb = primary.BoundingBox()

    print("Imported solid count:", len(solids))
    print("Primary solid index:", primary_index)
    print("Primary bbox:", bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)

    for i, solid in enumerate(solids):
        sb = solid.BoundingBox()
        print(
            "solid", i,
            "center", round((sb.xmin + sb.xmax) / 2.0, 3),
            round((sb.ymin + sb.ymax) / 2.0, 3),
            round((sb.zmin + sb.zmax) / 2.0, 3),
            "size", round(sb.xmax - sb.xmin, 3),
            round(sb.ymax - sb.ymin, 3),
            round(sb.zmax - sb.zmin, 3),
        )

    # Find the fan-facing radiator plane from the broad X-normal planar faces.
    # This avoids using the fan grille's much larger +X projection as the port
    # attachment surface.
    broad_x_faces = []
    for face in primary.Faces():
        try:
            if face.geomType() != "PLANE" or face.Area() < 10000.0:
                continue
            n = face.normalAt()
            if abs(n.x) > 0.9:
                broad_x_faces.append((face.Center().x, face.Area()))
        except Exception:
            pass

    if broad_x_faces:
        # The largest X coordinate among the broad radiator panels is the
        # surface facing the fans (+X).
        front_x = max(item[0] for item in broad_x_faces)
    else:
        front_x = bb.xmin + 0.333 * (bb.xmax - bb.xmin)

    print("Broad X faces:", [(round(x, 3), round(a, 1)) for x, a in broad_x_faces])
    print("Selected radiator front X:", round(front_x, 3))

    # In the fan-facing +X view, +Y is screen-right and +Z is screen-top.
    # Keep the fittings slightly inboard from the extreme corners to preserve
    # the diagonal mounting bosses and rounded frame corners.
    y_margin = 37.0
    z_margin = 34.0
    inlet_y = bb.ymin + y_margin
    inlet_z = bb.zmin + z_margin
    outlet_y = bb.ymax - y_margin
    outlet_z = bb.zmax - z_margin

    # Hose-neck dimensions, selected to match the scale of the existing ports.
    neck_od = 16.0
    barb_od = 20.0
    collar_od = 23.0
    bore_d = 9.0
    projection = 34.0
    collar_length = 7.0
    lip_length = 6.0

    axis = cq.Vector(1, 0, 0)
    root_x = front_x - 4.0

    def make_hollow_port(center_y, center_z):
        root = cq.Vector(root_x, center_y, center_z)

        collar = cq.Solid.makeCylinder(
            collar_od / 2.0, collar_length, root, axis
        )
        neck = cq.Solid.makeCylinder(
            neck_od / 2.0,
            projection - collar_length - lip_length + 2.0,
            cq.Vector(root_x + collar_length - 1.0, center_y, center_z),
            axis,
        )
        barb = cq.Solid.makeCone(
            neck_od / 2.0,
            barb_od / 2.0,
            lip_length,
            cq.Vector(root_x + projection - lip_length, center_y, center_z),
            axis,
        )

        outer = collar.fuse(neck).fuse(barb)

        # The bore begins well inside the radiator wall and continues beyond
        # the fitting end, creating a continuous open hydraulic passage.
        bore = cq.Solid.makeCylinder(
            bore_d / 2.0,
            projection + 28.0,
            cq.Vector(root_x - 16.0, center_y, center_z),
            axis,
        )
        shell = outer.cut(bore)
        if not shell.isValid():
            raise ValueError("Generated hose-port shell is invalid")
        return shell, bore

    inlet_port, inlet_bore = make_hollow_port(inlet_y, inlet_z)
    outlet_port, outlet_bore = make_hollow_port(outlet_y, outlet_z)

    # Open the radiator wall at both locations. The port shells are retained as
    # separate touching solids because fusing into the very complex imported
    # fan/frame B-rep proved unreliable in the previous iteration.
    edited_primary = primary
    wall_opened = False
    try:
        candidate = primary.cut(inlet_bore).cut(outlet_bore)
        if candidate.isValid() and len(candidate.Solids()) > 0:
            edited_primary = candidate
            wall_opened = True
        else:
            print("Wall-cut result was invalid; preserving primary B-rep")
    except Exception as exc:
        print("Wall-cut fallback:", exc)

    # Remove exactly the two source coolant fittings. Their semantic solid IDs
    # are 15 and 16 in the original STEP analysis. No fan blade, mounting boss,
    # service cap, or other geometry is removed.
    remove_indices = {15, 16}
    output_shapes = []
    for i, solid in enumerate(solids):
        if i in remove_indices:
            continue
        if i == primary_index:
            output_shapes.extend(list(edited_primary.Solids()))
        else:
            output_shapes.append(solid)

    output_shapes.extend([inlet_port, outlet_port])
    result = cq.Compound.makeCompound(output_shapes)

    print("Removed original coolant fitting solids:", sorted(remove_indices))
    print("Bottom-left inlet center Y,Z:", round(inlet_y, 3), round(inlet_z, 3))
    print("Top-right outlet center Y,Z:", round(outlet_y, 3), round(outlet_z, 3))
    print("Port axis: +X (outward from fan-facing radiator surface)")
    print("Port neck/barb/bore/projection:", neck_od, barb_od, bore_d, projection)
    print("Radiator wall passages cut:", wall_opened)
    print("Inlet valid:", inlet_port.isValid(), "Outlet valid:", outlet_port.isValid())
    print("Result valid:", result.isValid(), "solid count:", len(result.Solids()))
    return result