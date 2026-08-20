def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.ShapeFix import ShapeFix_Shape

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()
    solids = list(source_shape.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    def heal(shape):
        """Apply conservative STEP topology repair without remodeling faces."""
        try:
            fixer = ShapeFix_Shape(shape.wrapped)
            fixer.SetPrecision(1.0e-6)
            fixer.Perform()
            repaired = cq.Shape.cast(fixer.Shape())
            repaired_solids = list(repaired.Solids())
            if repaired_solids:
                candidate = max(repaired_solids, key=lambda s: s.Volume())
                try:
                    candidate = candidate.clean()
                except Exception:
                    pass
                return candidate
        except Exception as exc:
            print("Shape healing warning:", exc)
        return shape

    primary_index = max(range(len(solids)), key=lambda i: solids[i].Volume())
    original_primary = solids[primary_index]
    primary = heal(original_primary)
    bb = primary.BoundingBox()

    # The fans face +X. In that view, screen-right is +Y and screen-up is +Z.
    # Determine the rear shroud/tank attachment plane from large X-normal faces.
    broad_x_faces = []
    for face in primary.Faces():
        try:
            if face.geomType() != "PLANE" or face.Area() < 10000.0:
                continue
            normal = face.normalAt()
            if abs(normal.x) > 0.90:
                broad_x_faces.append(face.Center().x)
        except Exception:
            pass

    front_x = max(broad_x_faces) if broad_x_faces else bb.xmax

    width_y = bb.ymax - bb.ymin
    height_z = bb.zmax - bb.zmin

    # Place the fittings diagonally while staying inward of the large corner
    # mounting bosses and clear of the cap, rails, and fan guard perimeter.
    outlet_y = bb.ymax - min(50.0, 0.15 * width_y)
    outlet_z = bb.zmax - min(30.0, 0.06 * height_z)
    inlet_y = bb.ymin + min(50.0, 0.15 * width_y)
    inlet_z = bb.zmin + min(30.0, 0.06 * height_z)

    axis = cq.Vector(1, 0, 0)
    root_x = front_x - 6.0
    collar_r = 13.0
    neck_r = 9.0
    barb_r = 11.0
    bore_r = 5.0

    def port_outer(y, z):
        collar = cq.Solid.makeCylinder(
            collar_r, 12.0, cq.Vector(root_x, y, z), axis
        )
        neck = cq.Solid.makeCylinder(
            neck_r, 29.0, cq.Vector(root_x + 5.0, y, z), axis
        )
        barb_rise = cq.Solid.makeCone(
            neck_r, barb_r, 5.0, cq.Vector(root_x + 25.0, y, z), axis
        )
        barb_fall = cq.Solid.makeCone(
            barb_r, neck_r, 5.0, cq.Vector(root_x + 30.0, y, z), axis
        )
        terminal = cq.Solid.makeCylinder(
            neck_r, 6.0, cq.Vector(root_x + 35.0, y, z), axis
        )
        return collar.fuse(neck).fuse(barb_rise).fuse(barb_fall).fuse(terminal)

    def passage(y, z):
        # Starts behind the attachment face and exits beyond the hose end.
        return cq.Solid.makeCylinder(
            bore_r,
            68.0,
            cq.Vector(front_x - 16.0, y, z),
            axis,
        )

    def hollow_port(y, z):
        shell = port_outer(y, z).cut(passage(y, z))
        if not shell.isValid():
            shell = heal(shell)
        if not shell.isValid():
            raise ValueError("Generated hose fitting is invalid")
        return shell

    outlet_bore = passage(outlet_y, outlet_z)
    inlet_bore = passage(inlet_y, inlet_z)
    outlet_port = hollow_port(outlet_y, outlet_z)
    inlet_port = hollow_port(inlet_y, inlet_z)

    # Open both local tank/frame walls. Healing the imported primary before the
    # Boolean addresses the invalid source child that prevented this operation
    # in the preceding iteration.
    edited_primary = primary
    passages_opened = False
    try:
        candidate = primary.cut(outlet_bore)
        candidate = candidate.cut(inlet_bore)
        candidate = heal(candidate)
        if candidate.isValid() and candidate.Volume() < primary.Volume() - 1.0:
            edited_primary = candidate
            passages_opened = True
    except Exception as exc:
        print("Tank passage Boolean warning:", exc)

    # Solids 15 and 16 are the redundant original adjacent coolant fittings.
    # Preserve the core, frame, both fan assemblies, blades, guards, mounts,
    # service cap, and every other source component.
    remove_indices = {15, 16}
    output_shapes = []
    for index, solid in enumerate(solids):
        if index in remove_indices:
            continue
        if index == primary_index:
            replacement = list(edited_primary.Solids())
            output_shapes.extend(replacement if replacement else [edited_primary])
        else:
            if solid.isValid():
                output_shapes.append(solid)
            else:
                output_shapes.append(heal(solid))

    # Keep the hollow fittings as separate manufactured components whose broad
    # collars overlap the locally opened wall. This avoids a fragile union with
    # the imported high-face-count fan/shroud B-rep.
    output_shapes.extend([outlet_port, inlet_port])
    result = cq.Compound.makeCompound(output_shapes)

    invalid_children = []
    for index, shape in enumerate(output_shapes):
        try:
            if not shape.isValid():
                invalid_children.append(index)
        except Exception:
            invalid_children.append(index)

    print("Primary solid index:", primary_index)
    print("Fan-facing attachment plane X:", round(front_x, 3))
    print("Removed original coolant fitting solids:", sorted(remove_indices))
    print("Outlet center Y,Z:", round(outlet_y, 3), round(outlet_z, 3))
    print("Inlet center Y,Z:", round(inlet_y, 3), round(inlet_z, 3))
    print("Port projection direction: +X")
    print("Neck OD / barb OD / bore ID:", 2 * neck_r, 2 * barb_r, 2 * bore_r)
    print("Tank-wall passages opened:", passages_opened)
    print("Invalid output children:", invalid_children)
    print("Result solid count:", len(result.Solids()))
    print("Result valid:", result.isValid())
    return result