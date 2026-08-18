def my_cad_function(args):
    import cadquery as cq
    import os

    # Load the source model as required and use its bounds as the dimensional datum.
    source = cq.importers.importStep(os.path.expanduser(args['input_file']))
    src = source.val()
    bb = src.BoundingBox()
    print('SOURCE_VALID', src.isValid())
    print('SOURCE_BBOX', bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)

    # Principal dimensions recovered from the supplied model.
    x0, x1 = bb.xmin, bb.xmax
    y0, y1 = bb.ymin, bb.ymax
    z0, z1 = bb.zmin, bb.zmax

    junction_x = 100.0
    spine_y0 = 230.0
    spine_y1 = 295.0
    spine_z0 = -445.0

    # Reconstruct the unblended parent geometry. This removes every legacy
    # chamfer and radius, including the asymmetric front-side transition.
    housing = cq.Workplane('XY', origin=(0, 0, z0)).box(
        junction_x - x0, y1 - y0, z1 - z0,
        centered=(False, False, False)
    ).translate((x0, y0, 0))

    spine = cq.Workplane('XY', origin=(0, 0, spine_z0)).box(
        x1 - junction_x, spine_y1 - spine_y0, z1 - spine_z0,
        centered=(False, False, False)
    ).translate((junction_x, spine_y0, 0))

    body = housing.union(spine).combine().clean()
    solid = body.val()
    print('SHARP_PARENT_VALID', solid.isValid(), 'FACES', len(solid.Faces()))

    def edge_data(edge):
        c = edge.Center()
        eb = edge.BoundingBox()
        return c, eb

    # R20 is assigned first to straight transverse edges at the large-body to
    # narrow-spine shoulder. These are the edges perpendicular to the X socket axis.
    r20_edges = []
    for edge in solid.Edges():
        try:
            if edge.geomType() != 'LINE':
                continue
        except Exception:
            continue
        c, eb = edge_data(edge)
        transverse = eb.ylen > 1.0 and eb.xlen < 1e-4 and eb.zlen < 1e-4
        at_junction = abs(c.x - junction_x) < 1e-3
        # Top shoulder edges and the lower horizontal transition edge are the
        # intended narrow-to-large meeting-area set.
        top_shoulder = abs(c.z - z1) < 1e-3
        lower_transition = abs(c.z - spine_z0) < 1e-3
        if transverse and at_junction and (top_shoulder or lower_transition):
            r20_edges.append(edge)

    print('R20_CANDIDATES', len(r20_edges))
    r20_success = 0
    # Apply separately so one geometrically constrained edge does not prevent
    # the other valid shoulder edges from receiving the required radius.
    for original_edge in r20_edges:
        target_center = original_edge.Center()
        current_candidates = []
        for edge in solid.Edges():
            try:
                if edge.geomType() != 'LINE':
                    continue
            except Exception:
                continue
            c, eb = edge_data(edge)
            if (abs(c.x - target_center.x) < 0.05 and
                abs(c.y - target_center.y) < 0.05 and
                abs(c.z - target_center.z) < 0.05 and
                eb.ylen > 1.0):
                current_candidates.append(edge)
        if not current_candidates:
            continue
        try:
            trial = cq.Workplane(obj=solid).newObject(current_candidates).fillet(20.0).val()
            if trial.isValid():
                solid = trial
                r20_success += 1
        except Exception as exc:
            print('R20_EDGE_CONFLICT', tuple(round(v, 3) for v in (
                target_center.x, target_center.y, target_center.z)), str(exc)[:160])

    print('R20_SUCCEEDED', r20_success)

    # Apply R5 to the remaining external sharp edges. A greedy per-edge pass is
    # used because mixed-radius vertices are more reliable when completed after R20.
    attempted = set()
    r5_success = 0
    for pass_no in range(5):
        changed = False
        candidates = []
        for edge in solid.Edges():
            try:
                if edge.geomType() != 'LINE':
                    continue
            except Exception:
                continue
            c = edge.Center()
            key = (round(c.x, 2), round(c.y, 2), round(c.z, 2), round(edge.Length(), 2))
            if key not in attempted:
                candidates.append((edge.Length(), key, edge))
        candidates.sort(reverse=True, key=lambda item: item[0])

        for _, key, edge in candidates:
            attempted.add(key)
            c0 = edge.Center()
            current = None
            best = 1e100
            for candidate in solid.Edges():
                try:
                    if candidate.geomType() != 'LINE':
                        continue
                except Exception:
                    continue
                c = candidate.Center()
                d2 = (c.x-c0.x)**2 + (c.y-c0.y)**2 + (c.z-c0.z)**2
                if d2 < best:
                    best = d2
                    current = candidate
            if current is None or best > 0.05:
                continue
            try:
                trial = cq.Workplane(obj=solid).newObject([current]).fillet(5.0).val()
                if trial.isValid():
                    solid = trial
                    r5_success += 1
                    changed = True
            except Exception:
                pass
        if not changed:
            break

    print('EXTERNAL_R5_SUCCEEDED', r5_success)

    # Restore the functional blind axial socket. Its axis and nominal diameter
    # match the original model; only the entrance edge receives the new R5 treatment.
    socket_axis_y = 270.0
    socket_axis_z = -400.0
    socket_radius = 20.0
    socket_depth = x1 - junction_x
    socket_tool = cq.Solid.makeCylinder(
        socket_radius,
        socket_depth,
        cq.Vector(x1, socket_axis_y, socket_axis_z),
        cq.Vector(-1, 0, 0)
    )
    solid = solid.cut(socket_tool)

    # Restore the one-sided functional latch pocket. The cutting tool is rounded
    # R5 before subtraction, giving its internal end and corner edges the new radius.
    pocket_tool = cq.Workplane('XY', origin=(0, 0, -407.5)).box(
        45.0, 62.0, 35.0, centered=(False, False, False)
    ).translate((125.0, 220.0, 0))
    try:
        pocket_tool = pocket_tool.edges().fillet(5.0)
    except Exception as exc:
        print('POCKET_TOOL_FILLET_FALLBACK', str(exc)[:160])
    solid = solid.cut(pocket_tool.val()).clean()

    # Apply R5 to the circular socket-mouth edge without changing the bore away
    # from the blend. If local topology prevents it, retain the exact bore rather
    # than corrupting the functional cavity.
    mouth_edges = []
    for edge in solid.Edges():
        try:
            gt = edge.geomType()
        except Exception:
            continue
        c = edge.Center()
        if gt in ('CIRCLE', 'ELLIPSE') and abs(c.x - x1) < 0.05:
            eb = edge.BoundingBox()
            if eb.ylen > 35.0 and eb.zlen > 35.0:
                mouth_edges.append(edge)
    if mouth_edges:
        try:
            trial = cq.Workplane(obj=solid).newObject(mouth_edges).fillet(5.0).val()
            if trial.isValid():
                solid = trial
                print('SOCKET_MOUTH_R5', True)
        except Exception as exc:
            print('SOCKET_MOUTH_R5_CONFLICT', str(exc)[:160])

    solid = solid.clean()
    result = cq.Workplane(obj=solid)
    out_bb = solid.BoundingBox()
    print('RESULT_VALID', solid.isValid())
    print('RESULT_VOLUME', round(solid.Volume(), 3))
    print('RESULT_BBOX', round(out_bb.xmin, 3), round(out_bb.xmax, 3),
          round(out_bb.ymin, 3), round(out_bb.ymax, 3),
          round(out_bb.zmin, 3), round(out_bb.zmax, 3))
    print('RESULT_COUNTS', len(solid.Faces()), len(solid.Edges()), len(solid.Vertices()))
    return result