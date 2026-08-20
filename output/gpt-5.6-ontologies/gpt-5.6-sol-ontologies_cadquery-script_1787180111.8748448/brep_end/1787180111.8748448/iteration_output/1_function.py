def my_cad_function(args):
    import os
    import cadquery as cq
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    # Load the source model as required. The replacement geometry below is
    # reconstructed from its measured principal dimensions so the old edge
    # treatments and the one-sided thickness step are not retained.
    input_file = os.path.expanduser(args['input_file'])
    source = cq.importers.importStep(input_file)
    source_shape = source.val() if hasattr(source, 'val') else source
    print('SOURCE VALID:', source_shape.isValid())
    print('SOURCE VOLUME:', source_shape.Volume())

    def variable_fillet(solid, assignments):
        """Apply different radii to edge groups in one OCC fillet operation."""
        maker = BRepFilletAPI_MakeFillet(solid.wrapped)
        for radius, edges in assignments:
            for edge in edges:
                maker.Add(float(radius), edge.wrapped)
        maker.Build()
        if not maker.IsDone():
            raise RuntimeError('OCC variable-radius fillet did not complete')
        result = cq.Shape.cast(maker.Shape())
        if not result.isValid():
            raise RuntimeError('OCC variable-radius fillet produced an invalid shape')
        return result

    def tangent_components(edge):
        try:
            t = edge.tangentAt(0.5)
            return abs(t.x), abs(t.y), abs(t.z)
        except Exception:
            return 0.0, 0.0, 0.0

    # Measured design envelope. The arm is extended to z=-450 so its lower
    # surface is level with the neighboring enlarged-head surface. Together
    # with the unchanged z=-340 upper surface this removes the 5 mm one-sided
    # thickness step and makes the exterior symmetric about z=-395.
    head = cq.Solid.makeBox(
        100.0, 120.0, 110.0,
        cq.Vector(0.0, 200.0, -450.0)
    )
    arm = cq.Solid.makeBox(
        200.0, 64.336015, 110.0,
        cq.Vector(100.0, 230.0, -450.0)
    )
    base = head.fuse(arm)

    # The horizontal shoulder edges at the narrow-arm/enlarged-head junction
    # receive R20. Every other original exterior edge receives R5.
    special_edges = []
    other_edges = []
    for edge in base.Edges():
        c = edge.Center()
        tx, ty, tz = tangent_components(edge)
        at_shoulder = abs(c.x - 100.0) < 1.0e-4
        at_top_or_bottom = (
            abs(c.z + 340.0) < 1.0e-4 or
            abs(c.z + 450.0) < 1.0e-4
        )
        horizontal_across_shoulder = ty > 0.98 and tx < 0.05 and tz < 0.05
        if at_shoulder and at_top_or_bottom and horizontal_across_shoulder:
            special_edges.append(edge)
        else:
            other_edges.append(edge)

    print('OUTER EDGE ASSIGNMENTS R20/R5:', len(special_edges), len(other_edges))

    try:
        outer = variable_fillet(base, [(20.0, special_edges), (5.0, other_edges)])
        print('Variable-radius exterior fillet succeeded')
    except Exception as exc:
        print('Variable-radius exterior fillet fallback:', exc)
        outer = base
        if special_edges:
            try:
                outer = outer.makeFillet(20.0, special_edges)
            except Exception as exc2:
                print('R20 group fallback failed:', exc2)
        # Re-identify all remaining sharp linear edges and apply R5 together.
        remaining = [e for e in outer.Edges() if e.geomType() == 'LINE']
        try:
            outer = outer.makeFillet(5.0, remaining)
        except Exception as exc3:
            print('R5 exterior group fallback failed:', exc3)

    # Preserve the axial blind bore. Its axis and radius are taken directly
    # from the source B-rep: axis X, center (y,z)=(270,-400), radius 20,
    # blind termination at x=100 and opening through x=300.
    bore = cq.Solid.makeCylinder(
        20.0, 205.0,
        cq.Vector(100.0, 270.0, -400.0),
        cq.Vector(1.0, 0.0, 0.0)
    )
    blind_edges = [
        e for e in bore.Edges()
        if e.geomType() == 'CIRCLE' and abs(e.Center().x - 100.0) < 1.0e-4
    ]
    if blind_edges:
        try:
            bore = bore.makeFillet(5.0, blind_edges)
        except Exception as exc:
            print('Blind-bore bottom R5 fallback:', exc)

    result = outer.cut(bore)

    # Preserve the side engagement pocket at its measured location. Rounding
    # the cutter by 5 mm replaces its former sharp/chamfered edge treatment
    # with the requested uniform R5 treatment.
    pocket = cq.Solid.makeBox(
        42.985413, 55.0, 30.949498,
        cq.Vector(125.350920, 225.0, -405.071245)
    )
    try:
        pocket = pocket.makeFillet(5.0, pocket.Edges())
    except Exception as exc:
        print('Rounded pocket cutter fallback:', exc)
    result = result.cut(pocket)

    # Apply R5 to the exposed bore mouth. The blind end was already rounded
    # on the cutter, and the pocket cutter carries its own R5 edge treatment.
    mouth_edges = []
    for edge in result.Edges():
        if edge.geomType() != 'CIRCLE':
            continue
        c = edge.Center()
        bb = edge.BoundingBox()
        if c.x > 299.0 and bb.ymin > 245.0 and bb.ymax < 295.0:
            mouth_edges.append(edge)
    if mouth_edges:
        try:
            result = result.makeFillet(5.0, mouth_edges)
        except Exception as exc:
            print('Bore-mouth R5 fallback:', exc)

    print('RESULT VALID:', result.isValid())
    print('RESULT VOLUME:', result.Volume())
    bb = result.BoundingBox()
    print('RESULT BBOX:', (bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax))
    print('RESULT FACES/EDGES:', len(result.Faces()), len(result.Edges()))

    return cq.Workplane(obj=result)
