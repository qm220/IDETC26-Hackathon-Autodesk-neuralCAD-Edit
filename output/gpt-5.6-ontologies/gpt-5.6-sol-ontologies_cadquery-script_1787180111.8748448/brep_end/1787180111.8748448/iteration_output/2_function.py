def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    source = cq.importers.importStep(input_file)
    source_shape = source.val() if hasattr(source, 'val') else source
    print('SOURCE VALID:', source_shape.isValid())
    print('SOURCE VOLUME:', source_shape.Volume())

    tol = 1.0e-4

    def as_single_solid(shape):
        if hasattr(shape, 'Solids'):
            solids = shape.Solids()
            if len(solids) == 1:
                return solids[0]
        return shape

    def fillet_edges(shape, edges, radius):
        if not edges:
            return shape
        wp = cq.Workplane(obj=shape)
        result_wp = wp.newObject(list(edges)).fillet(float(radius)).clean()
        result = as_single_solid(result_wp.val())
        if not result.isValid():
            raise RuntimeError('Invalid result from R{} fillet'.format(radius))
        return result

    def tangent_axis(edge):
        try:
            t = edge.tangentAt(0.5)
            values = [abs(t.x), abs(t.y), abs(t.z)]
            return values.index(max(values))
        except Exception:
            return -1

    def close_to_any(value, levels, epsilon=tol):
        return any(abs(value - level) < epsilon for level in levels)

    # Reconstruct the unchamfered and unfilleted design body.  The arm lower
    # face is moved to z=-450, level with the adjoining enlarged head.  The
    # common upper face is z=-340, so both portions now have equal 110 mm
    # thickness and are symmetric about z=-395.
    head = cq.Solid.makeBox(
        100.0, 120.0, 110.0,
        cq.Vector(0.0, 200.0, -450.0)
    )
    arm = cq.Solid.makeBox(
        200.0, 64.336015, 110.0,
        cq.Vector(100.0, 230.0, -450.0)
    )

    base_wp = cq.Workplane(obj=head).union(arm).clean()
    base = as_single_solid(base_wp.val())
    print('CLEAN BASE TYPE:', type(base).__name__)
    print('CLEAN BASE EDGES:', len(base.Edges()))

    # R20 applies to the four Y-directed shoulder edges on the top and bottom
    # at x=100, where the narrow arm meets the wider head.
    shoulder_edges = []
    for edge in base.Edges():
        c = edge.Center()
        if edge.geomType() != 'LINE' or tangent_axis(edge) != 1:
            continue
        if abs(c.x - 100.0) > tol:
            continue
        if not (abs(c.z + 450.0) < tol or abs(c.z + 340.0) < tol):
            continue
        # Exclude any residual internal/common edge and retain only the two
        # exposed shoulder spans at each thickness side.
        bb = edge.BoundingBox()
        if bb.ymax <= 230.0 + tol or bb.ymin >= 294.336015 - tol:
            shoulder_edges.append(edge)

    print('R20 SHOULDER EDGES:', len(shoulder_edges))
    try:
        outer = fillet_edges(base, shoulder_edges, 20.0)
        print('R20 shoulder fillets succeeded')
    except Exception as exc:
        print('R20 shoulder fillets failed:', exc)
        outer = base
        # A per-edge fallback is preferable to returning an entirely sharp
        # model if a particular OCC build cannot process all four together.
        for index in range(4):
            candidates = []
            for edge in outer.Edges():
                c = edge.Center()
                if edge.geomType() == 'LINE' and tangent_axis(edge) == 1:
                    if abs(c.x - 100.0) < tol and (
                        abs(c.z + 450.0) < tol or abs(c.z + 340.0) < tol
                    ):
                        bb = edge.BoundingBox()
                        if bb.ymax <= 230.0 + tol or bb.ymin >= 294.336015 - tol:
                            candidates.append(edge)
            if not candidates:
                break
            try:
                outer = fillet_edges(outer, [candidates[0]], 20.0)
            except Exception as edge_exc:
                print('Individual R20 fallback stopped:', edge_exc)
                break

    # Identify remaining original sharp exterior edges.  Requiring an edge to
    # lie on two planes of the original prismatic envelope prevents the tangent
    # boundary curves created by R20 from being selected for a second fillet.
    x_levels = [0.0, 100.0, 300.0]
    y_levels = [200.0, 230.0, 294.336015, 320.0]
    z_levels = [-450.0, -340.0]

    def remaining_original_edges(shape):
        selected = []
        for edge in shape.Edges():
            if edge.geomType() != 'LINE':
                continue
            bb = edge.BoundingBox()
            axis = tangent_axis(edge)
            if axis == 0:
                on_original_intersection = (
                    close_to_any(bb.ymin, y_levels) and
                    close_to_any(bb.ymax, y_levels) and
                    close_to_any(bb.zmin, z_levels) and
                    close_to_any(bb.zmax, z_levels)
                )
            elif axis == 1:
                on_original_intersection = (
                    close_to_any(bb.xmin, x_levels) and
                    close_to_any(bb.xmax, x_levels) and
                    close_to_any(bb.zmin, z_levels) and
                    close_to_any(bb.zmax, z_levels)
                )
            elif axis == 2:
                on_original_intersection = (
                    close_to_any(bb.xmin, x_levels) and
                    close_to_any(bb.xmax, x_levels) and
                    close_to_any(bb.ymin, y_levels) and
                    close_to_any(bb.ymax, y_levels)
                )
            else:
                on_original_intersection = False
            if on_original_intersection:
                selected.append(edge)
        return selected

    r5_edges = remaining_original_edges(outer)
    print('EXTERIOR R5 EDGES:', len(r5_edges))
    try:
        outer = fillet_edges(outer, r5_edges, 5.0)
        print('Grouped exterior R5 fillets succeeded')
    except Exception as exc:
        print('Grouped exterior R5 fallback:', exc)
        # Greedy fallback re-identifies surviving original edges after every
        # successful operation, avoiding stale topological edge references.
        for attempt in range(30):
            candidates = remaining_original_edges(outer)
            if not candidates:
                break
            candidates.sort(key=lambda e: e.Length(), reverse=True)
            success = False
            for edge in candidates:
                try:
                    outer = fillet_edges(outer, [edge], 5.0)
                    success = True
                    break
                except Exception:
                    pass
            if not success:
                print('No further exterior R5 edge could be processed')
                break

    # Preserve the axial blind bore: X-axis, radius 20 mm, center at
    # (y,z)=(270,-400), opening at x=300 and blind bottom at x=100.
    bore = cq.Solid.makeCylinder(
        20.0, 205.0,
        cq.Vector(100.0, 270.0, -400.0),
        cq.Vector(1.0, 0.0, 0.0)
    )
    blind_end_edges = [
        edge for edge in bore.Edges()
        if edge.geomType() == 'CIRCLE' and abs(edge.Center().x - 100.0) < tol
    ]
    try:
        bore = fillet_edges(bore, blind_end_edges, 5.0)
        print('Blind bore bottom R5 succeeded')
    except Exception as exc:
        print('Blind bore bottom R5 failed:', exc)

    result = as_single_solid(outer.cut(bore))

    # Preserve the side engagement pocket while replacing its old chamfers
    # with R5 internal edge radii.  The cutter begins outside the -Y wall.
    pocket = cq.Solid.makeBox(
        42.985413, 55.0, 30.949498,
        cq.Vector(125.350920, 225.0, -405.071245)
    )
    try:
        pocket = fillet_edges(pocket, pocket.Edges(), 5.0)
        print('Rounded pocket cutter R5 succeeded')
    except Exception as exc:
        print('Rounded pocket cutter R5 failed:', exc)

    result = as_single_solid(result.cut(pocket))

    # Round the exposed circular bore mouth to R5.  This edge is generated by
    # the subtraction and therefore must be treated after the boolean cut.
    mouth_edges = []
    for edge in result.Edges():
        if edge.geomType() != 'CIRCLE':
            continue
        c = edge.Center()
        bb = edge.BoundingBox()
        if c.x > 299.0 and bb.ymin > 245.0 and bb.ymax < 295.0:
            mouth_edges.append(edge)
    try:
        result = fillet_edges(result, mouth_edges, 5.0)
        print('Bore mouth R5 succeeded')
    except Exception as exc:
        print('Bore mouth R5 failed:', exc)

    result = as_single_solid(result)
    print('RESULT VALID:', result.isValid())
    print('RESULT VOLUME:', result.Volume())
    bb = result.BoundingBox()
    print('RESULT BBOX:', (bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax))
    print('RESULT FACES/EDGES:', len(result.Faces()), len(result.Edges()))

    return cq.Workplane(obj=result)
