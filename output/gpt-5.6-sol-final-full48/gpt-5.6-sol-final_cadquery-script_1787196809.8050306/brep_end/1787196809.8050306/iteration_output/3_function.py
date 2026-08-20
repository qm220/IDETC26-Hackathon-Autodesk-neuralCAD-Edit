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

    # Find the broad fan-facing (+X-view) radiator/frame plane. Guard and hub
    # faces are excluded by requiring a large planar area.
    broad_x_faces = []
    for face in primary.Faces():
        try:
            if face.geomType() != "PLANE" or face.Area() < 10000.0:
                continue
            n = face.normalAt()
            if abs(n.x) > 0.9:
                broad_x_faces.append(face.Center().x)
        except Exception:
            pass

    front_x = max(broad_x_faces) if broad_x_faces else bb.xmin + 0.36 * (bb.xmax - bb.xmin)

    # In the fan-facing +X view, +Y is right and +Z is up. Keep the ports
    # inward from the extreme corners so the original diagonal mounts, cap,
    # perimeter transitions, and fan guards retain clearance.
    outlet_y = min(115.0, bb.ymax - 50.0)
    outlet_z = min(235.0, bb.zmax - 30.0)
    inlet_y = max(-115.0, bb.ymin + 50.0)
    inlet_z = max(-235.0, bb.zmin + 30.0)

    axis = cq.Vector(1, 0, 0)
    root_x = front_x - 4.0
    collar_r = 13.0
    neck_r = 9.0
    barb_r = 11.0
    bore_r = 5.0

    def port_outer(y, z):
        # A single fused hose-neck body with a tank-side collar, straight neck,
        # retention barb, and short terminal land.
        collar = cq.Solid.makeCylinder(
            collar_r, 10.0, cq.Vector(root_x, y, z), axis
        )
        neck = cq.Solid.makeCylinder(
            neck_r, 31.0, cq.Vector(root_x + 4.0, y, z), axis
        )
        barb_up = cq.Solid.makeCone(
            neck_r, barb_r, 5.0, cq.Vector(root_x + 25.0, y, z), axis
        )
        barb_down = cq.Solid.makeCone(
            barb_r, neck_r, 5.0, cq.Vector(root_x + 30.0, y, z), axis
        )
        end_land = cq.Solid.makeCylinder(
            neck_r, 5.0, cq.Vector(root_x + 35.0, y, z), axis
        )
        return collar.fuse(neck).fuse(barb_up).fuse(barb_down).fuse(end_land)

    def passage(y, z):
        # Begin behind the selected tank wall and continue beyond the hose end,
        # leaving an unobstructed hydraulic passage through the fitting.
        return cq.Solid.makeCylinder(
            bore_r, 64.0, cq.Vector(root_x - 10.0, y, z), axis
        )

    outlet_bore = passage(outlet_y, outlet_z)
    inlet_bore = passage(inlet_y, inlet_z)

    # Cut the local wall passages without fusing complex new topology into the
    # imported fan/shroud B-rep. This avoids the invalid fused primary solid
    # produced in the preceding iteration while retaining actual openings.
    edited_primary = primary
    passages_opened = False
    try:
        cut_primary = primary.cut(outlet_bore).cut(inlet_bore)
        cut_solids = list(cut_primary.Solids())
        if cut_solids and cut_primary.isValid() and cut_primary.Volume() < primary.Volume():
            edited_primary = cut_primary
            passages_opened = True
    except Exception as exc:
        print("Primary passage cut fallback:", exc)

    # Keep each fitting as a valid hollow manufactured component whose collar
    # overlaps the local tank wall. The assembly therefore remains connected
    # geometrically while avoiding a fragile union with the imported B-rep.
    def hollow_port(y, z):
        outer = port_outer(y, z)
        shell = outer.cut(passage(y, z))
        if not shell.isValid():
            raise ValueError("Generated hose fitting is invalid")
        return shell

    inlet_port = hollow_port(inlet_y, inlet_z)
    outlet_port = hollow_port(outlet_y, outlet_z)

    # The source model identifies solids 15 and 16 as the redundant adjacent
    # coolant fittings. Remove only those; retain both fans, all blades and
    # guards, frame/core, service cap, and diagonal mounting bosses.
    remove_indices = {15, 16}
    output_shapes = []
    for index, solid in enumerate(solids):
        if index in remove_indices:
            continue
        if index == primary_index:
            output_shapes.extend(list(edited_primary.Solids()))
        else:
            output_shapes.append(solid)

    output_shapes.extend([inlet_port, outlet_port])
    result = cq.Compound.makeCompound(output_shapes)

    invalid_children = []
    for i, shape in enumerate(output_shapes):
        try:
            if not shape.isValid():
                invalid_children.append(i)
        except Exception:
            invalid_children.append(i)

    print("Primary solid index:", primary_index)
    print("Fan-facing attachment plane X:", round(front_x, 3))
    print("Removed original coolant fitting solids:", sorted(remove_indices))
    print("Inlet center Y,Z:", round(inlet_y, 3), round(inlet_z, 3))
    print("Outlet center Y,Z:", round(outlet_y, 3), round(outlet_z, 3))
    print("Port projection direction: +X")
    print("Neck OD / barb OD / bore ID:", 2 * neck_r, 2 * barb_r, 2 * bore_r)
    print("Tank-wall passages opened:", passages_opened)
    print("Invalid output children:", invalid_children)
    print("Result solid count:", len(result.Solids()))
    print("Result valid:", result.isValid())
    return result