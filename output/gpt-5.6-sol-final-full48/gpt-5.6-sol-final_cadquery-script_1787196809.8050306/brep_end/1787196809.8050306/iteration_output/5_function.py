def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.ShapeFix import ShapeFix_Shape
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    source_shape = imported.val()
    solids = list(source_shape.Solids())
    if not solids:
        raise ValueError("The input STEP file contains no solids")

    def conservative_fix(shape):
        try:
            fixer = ShapeFix_Shape(shape.wrapped)
            fixer.SetPrecision(1.0e-6)
            fixer.SetMinTolerance(1.0e-7)
            fixer.SetMaxTolerance(1.0e-3)
            fixer.Perform()
            repaired = cq.Shape.cast(fixer.Shape())
            if repaired.Solids():
                return repaired
        except Exception as exc:
            print("Shape repair warning:", exc)
        return shape

    def fuzzy_cut(base, tool):
        """Perform a tolerant OCC cut and retain it whenever material was removed."""
        original_volume = base.Volume()

        # Try CadQuery's standard Boolean first.
        try:
            candidate = base.cut(tool)
            if candidate.Solids() and candidate.Volume() < original_volume - 0.1:
                return candidate, "CadQuery"
        except Exception as exc:
            print("Standard cut warning:", exc)

        # Imported fan/shroud topology is imperfect, so retry using OCC's
        # non-destructive fuzzy Boolean without requiring the source to pass a
        # strict validity test before accepting a genuine volume reduction.
        for tolerance in (1.0e-5, 1.0e-4, 1.0e-3, 5.0e-3):
            try:
                operation = BRepAlgoAPI_Cut(base.wrapped, tool.wrapped)
                operation.SetNonDestructive(True)
                operation.SetFuzzyValue(tolerance)
                operation.Build()
                if not operation.IsDone():
                    continue
                candidate = cq.Shape.cast(operation.Shape())
                if candidate.Solids() and candidate.Volume() < original_volume - 0.1:
                    return candidate, "OCC fuzzy %.6g" % tolerance
            except Exception as exc:
                print("Fuzzy cut warning at", tolerance, ":", exc)

        return base, "failed"

    primary_index = max(range(len(solids)), key=lambda i: solids[i].Volume())
    primary = solids[primary_index]
    bb = primary.BoundingBox()

    # The requested locations are interpreted in the fan-facing +X view:
    # screen-right is +Y and screen-up is +Z.
    broad_x_faces = []
    for face in primary.Faces():
        try:
            if face.geomType() == "PLANE" and face.Area() > 10000.0:
                normal = face.normalAt()
                if abs(normal.x) > 0.90:
                    broad_x_faces.append(face.Center().x)
        except Exception:
            pass

    fan_side_x = max(broad_x_faces) if broad_x_faces else bb.xmax
    width_y = bb.ymax - bb.ymin
    height_z = bb.zmax - bb.zmin

    # Keep the ports inward from the diagonal mounting bosses and sufficiently
    # outside the fan-guard circles.
    outlet_y = bb.ymax - min(50.0, 0.15 * width_y)
    outlet_z = bb.zmax - min(30.0, 0.06 * height_z)
    inlet_y = bb.ymin + min(50.0, 0.15 * width_y)
    inlet_z = bb.zmin + min(30.0, 0.06 * height_z)

    axis = cq.Vector(1, 0, 0)
    collar_r = 13.0
    neck_r = 9.0
    barb_r = 11.0
    bore_r = 5.0
    root_x = fan_side_x - 9.0

    def make_outer_port(y, z):
        # A buried root and broad collar provide a visibly integrated tank
        # connection. Two tapered beads form a practical hose-retention end.
        root = cq.Solid.makeCylinder(
            10.5, 14.0, cq.Vector(root_x, y, z), axis
        )
        collar = cq.Solid.makeCylinder(
            collar_r, 7.0, cq.Vector(fan_side_x - 2.0, y, z), axis
        )
        neck = cq.Solid.makeCylinder(
            neck_r, 23.0, cq.Vector(fan_side_x + 5.0, y, z), axis
        )
        bead1_up = cq.Solid.makeCone(
            neck_r, barb_r, 4.0, cq.Vector(fan_side_x + 23.0, y, z), axis
        )
        bead1_down = cq.Solid.makeCone(
            barb_r, neck_r, 4.0, cq.Vector(fan_side_x + 27.0, y, z), axis
        )
        tip = cq.Solid.makeCylinder(
            neck_r, 8.0, cq.Vector(fan_side_x + 31.0, y, z), axis
        )
        return root.fuse(collar).fuse(neck).fuse(bead1_up).fuse(bead1_down).fuse(tip)

    def make_passage(y, z):
        # The bore begins well behind the fan-side tank wall and exits beyond
        # the hose tip, thereby opening both the tank wall and fitting end.
        return cq.Solid.makeCylinder(
            bore_r,
            76.0,
            cq.Vector(fan_side_x - 22.0, y, z),
            axis,
        )

    def make_hollow_port(y, z):
        outer = make_outer_port(y, z)
        bore = make_passage(y, z)
        port = outer.cut(bore)
        if not port.Solids() or port.Volume() >= outer.Volume() - 0.1:
            raise ValueError("Failed to form the internal port bore")
        return port, bore

    outlet_port, outlet_bore = make_hollow_port(outlet_y, outlet_z)
    inlet_port, inlet_bore = make_hollow_port(inlet_y, inlet_z)

    # Cut the two passages independently so that one difficult local region
    # cannot prevent the other requested opening from being made.
    edited_primary, outlet_cut_method = fuzzy_cut(primary, outlet_bore)
    edited_primary, inlet_cut_method = fuzzy_cut(edited_primary, inlet_bore)

    outlet_open = outlet_cut_method != "failed"
    inlet_open = inlet_cut_method != "failed"

    # Solids 15 and 16 are the redundant adjacent source fittings. Replace
    # them with one lower-left inlet and one upper-right outlet while retaining
    # the core, frame, fans, grilles, blades, mounts, and service cap.
    remove_indices = {15, 16}
    output_shapes = []
    for index, solid in enumerate(solids):
        if index in remove_indices:
            continue
        if index == primary_index:
            replacement_solids = list(edited_primary.Solids())
            output_shapes.extend(replacement_solids if replacement_solids else [edited_primary])
        else:
            output_shapes.append(solid)

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
    print("Fan-facing tank plane X:", round(fan_side_x, 3))
    print("Removed original fitting solids:", sorted(remove_indices))
    print("Outlet upper-right Y,Z:", round(outlet_y, 3), round(outlet_z, 3))
    print("Inlet lower-left Y,Z:", round(inlet_y, 3), round(inlet_z, 3))
    print("Port projection direction: +X")
    print("Neck OD / barb OD / bore ID:", 2 * neck_r, 2 * barb_r, 2 * bore_r)
    print("Outlet passage method:", outlet_cut_method)
    print("Inlet passage method:", inlet_cut_method)
    print("Outlet wall opened:", outlet_open)
    print("Inlet wall opened:", inlet_open)
    print("Invalid output children:", invalid_children)
    print("Result solid count:", len(result.Solids()))
    print("Result valid:", result.isValid())
    return result