def my_cad_function(args):
    import cadquery as cq
    import os

    source = cq.importers.importStep(os.path.expanduser(args['input_file']))
    src = source.val()
    bb = src.BoundingBox()
    print('SOURCE_VALID', src.isValid())
    print('SOURCE_BBOX', bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)

    x0, x1 = bb.xmin, bb.xmax
    y0, y1 = bb.ymin, bb.ymax
    z0, z1 = bb.zmin, bb.zmax

    junction_x = 100.0
    spine_y0 = 230.0
    spine_y1 = 295.0
    spine_z0 = -445.0
    spine_mid_y = 0.5 * (spine_y0 + spine_y1)

    # Rebuild the sharp parent solid. This removes all legacy chamfers and
    # rounds and eliminates the localized offset flank by using one continuous,
    # planar side boundary from the shoulder to the terminal face.
    housing = (
        cq.Workplane('XY', origin=(x0, y0, z0))
        .box(junction_x - x0, y1 - y0, z1 - z0,
             centered=(False, False, False))
    )
    spine = (
        cq.Workplane('XY', origin=(junction_x, spine_y0, spine_z0))
        .box(x1 - junction_x, spine_y1 - spine_y0, z1 - spine_z0,
             centered=(False, False, False))
    )
    sharp = housing.union(spine).combine().clean().val()
    print('SHARP_PARENT_VALID', sharp.isValid(), 'FACES', len(sharp.Faces()))

    def is_line(edge):
        try:
            return edge.geomType() == 'LINE'
        except Exception:
            return False

    # The two transverse top shoulder edges are the constructible horizontal
    # edges at the large-housing/narrow-spine meeting region. Applying them in
    # one operation avoids the asymmetric sliver faces produced previously.
    r20_edges = []
    for edge in sharp.Edges():
        if not is_line(edge):
            continue
        c = edge.Center()
        eb = edge.BoundingBox()
        transverse = eb.ylen > 1.0 and eb.xlen < 1e-5 and eb.zlen < 1e-5
        if (transverse and abs(c.x - junction_x) < 1e-4 and
                abs(c.z - z1) < 1e-4):
            r20_edges.append(edge)

    print('R20_CANDIDATES', len(r20_edges))
    if len(r20_edges) != 2:
        print('R20_SELECTION_WARNING', len(r20_edges))

    solid = sharp
    if r20_edges:
        try:
            trial = cq.Workplane(obj=solid).newObject(r20_edges).fillet(20.0).val()
            if not trial.isValid():
                raise RuntimeError('R20 result is invalid')
            solid = trial
            print('R20_SUCCEEDED', len(r20_edges))
        except Exception as exc:
            print('R20_FAILED', str(exc)[:200])

    # Apply R5 to all remaining external sharp edges as a common edge set.
    # A single rolling-ball operation gives consistent mixed-radius junctions
    # and avoids the wedge/sliver artifacts caused by sequential per-edge edits.
    remaining = [edge for edge in solid.Edges() if is_line(edge)]
    print('EXTERNAL_R5_CANDIDATES', len(remaining))
    external_r5_done = False
    if remaining:
        try:
            trial = cq.Workplane(obj=solid).newObject(remaining).fillet(5.0).val()
            if not trial.isValid():
                raise RuntimeError('combined R5 result is invalid')
            solid = trial
            external_r5_done = True
            print('EXTERNAL_R5_COMBINED_SUCCEEDED', len(remaining))
        except Exception as exc:
            print('EXTERNAL_R5_COMBINED_FAILED', str(exc)[:200])

    # Conservative grouped fallback if OCC cannot solve the complete mixed set.
    # Groups are processed together rather than edge-by-edge to preserve clean
    # and symmetric corner intersections.
    if not external_r5_done:
        groups = {'front': [], 'rear': [], 'longitudinal': [], 'junction': []}
        for edge in solid.Edges():
            if not is_line(edge):
                continue
            c = edge.Center()
            if c.x > x1 - 1.0:
                groups['front'].append(edge)
            elif c.x < x0 + 1.0:
                groups['rear'].append(edge)
            elif abs(c.x - junction_x) < 22.0:
                groups['junction'].append(edge)
            else:
                groups['longitudinal'].append(edge)

        for name in ('front', 'rear', 'longitudinal', 'junction'):
            targets = groups[name]
            if not targets:
                continue
            # Relocate group edges after each topology-changing operation.
            keys = []
            for edge in targets:
                c = edge.Center()
                keys.append((c.x, c.y, c.z, edge.Length()))
            current_targets = []
            used = set()
            for key in keys:
                best_i = None
                best_score = 1e100
                for i, edge in enumerate(solid.Edges()):
                    if i in used or not is_line(edge):
                        continue
                    c = edge.Center()
                    score = ((c.x-key[0])**2 + (c.y-key[1])**2 +
                             (c.z-key[2])**2 + 0.01*(edge.Length()-key[3])**2)
                    if score < best_score:
                        best_score = score
                        best_i = i
                if best_i is not None and best_score < 1.0:
                    used.add(best_i)
                    current_targets.append(solid.Edges()[best_i])
            if not current_targets:
                continue
            try:
                trial = cq.Workplane(obj=solid).newObject(current_targets).fillet(5.0).val()
                if trial.isValid():
                    solid = trial
                    print('EXTERNAL_R5_GROUP_SUCCEEDED', name, len(current_targets))
                else:
                    print('EXTERNAL_R5_GROUP_INVALID', name)
            except Exception as exc:
                print('EXTERNAL_R5_GROUP_FAILED', name, str(exc)[:160])

    # Blind socket centered in the symmetric spine. Centering it removes the
    # previous 5 mm wall pinch that prevented the required mouth radius.
    socket_z = -400.0
    socket_radius = 20.0
    socket_closed_x = junction_x
    socket_tool = cq.Solid.makeCylinder(
        socket_radius,
        x1 - socket_closed_x,
        cq.Vector(x1, spine_mid_y, socket_z),
        cq.Vector(-1, 0, 0)
    )
    solid = solid.cut(socket_tool).clean()

    # Radius the socket entrance and blind-end circular edges with R5.
    socket_edges = []
    for edge in solid.Edges():
        try:
            gt = edge.geomType()
        except Exception:
            continue
        if gt not in ('CIRCLE', 'ELLIPSE'):
            continue
        c = edge.Center()
        eb = edge.BoundingBox()
        correct_axis = (abs(c.y - spine_mid_y) < 0.1 and
                        abs(c.z - socket_z) < 0.1)
        correct_size = eb.ylen > 39.0 and eb.zlen > 39.0
        at_socket_end = (abs(c.x - x1) < 0.1 or
                         abs(c.x - socket_closed_x) < 0.1)
        if correct_axis and correct_size and at_socket_end:
            socket_edges.append(edge)

    print('SOCKET_R5_CANDIDATES', len(socket_edges))
    if socket_edges:
        try:
            trial = cq.Workplane(obj=solid).newObject(socket_edges).fillet(5.0).val()
            if not trial.isValid():
                raise RuntimeError('socket R5 result invalid')
            solid = trial
            print('SOCKET_R5_SUCCEEDED', len(socket_edges))
        except Exception as exc:
            print('SOCKET_R5_FAILED', str(exc)[:200])

    # Restore the one-sided functional latch pocket. Filleting the complete
    # cutting tool by R5 gives the pocket opening, floor, end, and side corners
    # the replacement radius while preserving the specified asymmetric function.
    pocket_tool = (
        cq.Workplane('XY', origin=(125.0, 220.0, -407.5))
        .box(45.0, 62.0, 35.0, centered=(False, False, False))
    )
    try:
        pocket_tool = pocket_tool.edges().fillet(5.0)
        print('POCKET_R5_TOOL_SUCCEEDED')
    except Exception as exc:
        print('POCKET_R5_TOOL_FAILED', str(exc)[:200])
    solid = solid.cut(pocket_tool.val()).clean()

    out_bb = solid.BoundingBox()
    print('RESULT_VALID', solid.isValid())
    print('RESULT_VOLUME', round(solid.Volume(), 3))
    print('RESULT_BBOX', round(out_bb.xmin, 3), round(out_bb.xmax, 3),
          round(out_bb.ymin, 3), round(out_bb.ymax, 3),
          round(out_bb.zmin, 3), round(out_bb.zmax, 3))
    print('RESULT_COUNTS', len(solid.Faces()), len(solid.Edges()),
          len(solid.Vertices()))
    return cq.Workplane(obj=solid)
