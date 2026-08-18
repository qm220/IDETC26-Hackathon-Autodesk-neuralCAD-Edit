def my_cad_function(args):
    import cadquery as cq
    import os
    import math

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
    spine_mid_y = 0.5 * (spine_y0 + spine_y1)

    # Rebuild the sharp parent body. This removes the asymmetric exterior step
    # and suppresses all legacy chamfers and external rounds in one operation.
    housing = (
        cq.Workplane('XY', origin=(x0, y0, z0))
        .box(junction_x-x0, y1-y0, z1-z0, centered=(False, False, False))
    )
    spine = (
        cq.Workplane('XY', origin=(junction_x, spine_y0, z0))
        .box(x1-junction_x, spine_y1-spine_y0, z1-z0,
             centered=(False, False, False))
    )
    solid = housing.union(spine).combine().clean().val()
    print('SHARP_PARENT_VALID', solid.isValid(), 'FACES', len(solid.Faces()))

    def is_line(edge):
        try:
            return edge.geomType() == 'LINE'
        except Exception:
            return False

    def edge_axis(edge):
        eb = edge.BoundingBox()
        dims = (eb.xlen, eb.ylen, eb.zlen)
        return max(range(3), key=lambda i: dims[i])

    def adjacent_faces(shape, edge):
        result = []
        for face in shape.Faces():
            for candidate in face.Edges():
                try:
                    same = edge.isSame(candidate)
                except Exception:
                    same = edge.hashCode() == candidate.hashCode()
                if same:
                    result.append(face)
                    break
        return result

    def is_sharp(shape, edge):
        faces = adjacent_faces(shape, edge)
        if len(faces) != 2:
            return False
        c = edge.Center()
        try:
            n1 = faces[0].normalAt(c)
            n2 = faces[1].normalAt(c)
            l1 = math.sqrt(n1.x*n1.x+n1.y*n1.y+n1.z*n1.z)
            l2 = math.sqrt(n2.x*n2.x+n2.y*n2.y+n2.z*n2.z)
            if l1 < 1e-9 or l2 < 1e-9:
                return True
            dot = abs((n1.x*n2.x+n1.y*n2.y+n1.z*n2.z)/(l1*l2))
            return dot < 0.985
        except Exception:
            return True

    def sharp_edges(shape):
        return [e for e in shape.Edges() if is_sharp(shape, e)]

    def sharp_lines(shape):
        return [e for e in shape.Edges() if is_line(e) and is_sharp(shape, e)]

    # R20 is reserved for the four straight transverse shoulder edges at the
    # junction between the enlarged housing and the narrow spine.
    r20_edges = []
    for edge in solid.Edges():
        if not is_line(edge) or edge_axis(edge) != 1:
            continue
        c = edge.Center()
        eb = edge.BoundingBox()
        at_junction = abs(c.x-junction_x) < 1e-4
        on_horizontal_skin = min(abs(c.z-z0), abs(c.z-z1)) < 1e-4
        outside_spine = c.y < spine_y0-1e-4 or c.y > spine_y1+1e-4
        if (at_junction and on_horizontal_skin and outside_spine and
                eb.ylen > 1.0 and eb.xlen < 1e-5 and eb.zlen < 1e-5):
            r20_edges.append(edge)

    print('R20_CANDIDATES', len(r20_edges))
    if len(r20_edges) != 4:
        raise RuntimeError('Expected four horizontal shoulder edges for R20')
    solid = cq.Workplane(obj=solid).newObject(r20_edges).fillet(20.0).val().clean()
    if not solid.isValid():
        raise RuntimeError('R20 shoulder operation produced an invalid body')
    print('R20_SUCCEEDED', len(r20_edges))

    def apply_r5_group(name, predicate):
        nonlocal solid
        targets = [e for e in sharp_lines(solid) if predicate(e)]
        print('R5_GROUP_CANDIDATES', name, len(targets))
        if not targets:
            return
        try:
            trial = cq.Workplane(obj=solid).newObject(targets).fillet(5.0).val()
            if trial.isValid():
                solid = trial.clean()
                print('R5_GROUP_SUCCEEDED', name, len(targets))
                return
        except Exception as exc:
            print('R5_GROUP_BATCH_RETRY', name, str(exc)[:150])

        keys = []
        for edge in targets:
            c = edge.Center()
            keys.append((c.x, c.y, c.z, edge.Length(), edge_axis(edge)))

        succeeded = 0
        conflicts = 0
        for key in keys:
            candidates = [e for e in sharp_lines(solid)
                          if predicate(e) and edge_axis(e) == key[4]]
            if not candidates:
                continue
            edge = min(candidates, key=lambda e:
                (e.Center().x-key[0])**2+
                (e.Center().y-key[1])**2+
                (e.Center().z-key[2])**2+
                0.0025*(e.Length()-key[3])**2)
            try:
                trial = cq.Workplane(obj=solid).newObject([edge]).fillet(5.0).val()
                if trial.isValid():
                    solid = trial.clean()
                    succeeded += 1
                else:
                    conflicts += 1
            except Exception:
                conflicts += 1
        print('R5_GROUP_FALLBACK', name, 'SUCCEEDED', succeeded,
              'CONFLICTS', conflicts)

    # Apply R5 to the sharp exterior complement after the R20 operation.
    apply_r5_group('longitudinal', lambda e: edge_axis(e) == 0)
    apply_r5_group('front_end', lambda e: abs(e.Center().x-x1) < 0.2)
    apply_r5_group('rear_end', lambda e: abs(e.Center().x-x0) < 0.2)
    apply_r5_group(
        'vertical_shoulder',
        lambda e: edge_axis(e) == 2 and abs(e.Center().x-junction_x) < 0.2
    )
    apply_r5_group('remaining_external', lambda e: True)

    # Restore the functional blind axial socket on its original datum.
    socket_z = -400.0
    socket_radius = 20.0
    socket_closed_x = junction_x
    socket_tool = cq.Solid.makeCylinder(
        socket_radius,
        x1-socket_closed_x,
        cq.Vector(x1, spine_mid_y, socket_z),
        cq.Vector(-1, 0, 0)
    )
    solid = solid.cut(socket_tool).clean()

    socket_edges = []
    for edge in solid.Edges():
        try:
            circular = edge.geomType() in ('CIRCLE', 'ELLIPSE')
        except Exception:
            circular = False
        if not circular:
            continue
        c = edge.Center()
        eb = edge.BoundingBox()
        if (abs(c.y-spine_mid_y) < 0.15 and
                abs(c.z-socket_z) < 0.15 and
                eb.ylen > 39.0 and eb.zlen > 39.0 and
                (abs(c.x-x1) < 0.15 or abs(c.x-socket_closed_x) < 0.15)):
            socket_edges.append(edge)

    print('SOCKET_R5_CANDIDATES', len(socket_edges))
    if len(socket_edges) != 2:
        raise RuntimeError('Could not identify both blind-socket edges')
    solid = cq.Workplane(obj=solid).newObject(socket_edges).fillet(5.0).val().clean()
    if not solid.isValid():
        raise RuntimeError('Socket R5 operation produced an invalid body')
    print('SOCKET_R5_SUCCEEDED', len(socket_edges))

    # Restore the one-sided functional latch pocket using a fully R5-rounded
    # cutting tool. The functional recess is retained despite exterior symmetry.
    pocket_x0, pocket_x1 = 125.0, 170.0
    pocket_y0, pocket_y1 = 225.0, 282.0
    pocket_z0, pocket_z1 = -407.5, -372.5
    pocket_raw = (
        cq.Workplane('XY', origin=(pocket_x0, pocket_y0, pocket_z0))
        .box(pocket_x1-pocket_x0, pocket_y1-pocket_y0,
             pocket_z1-pocket_z0, centered=(False, False, False))
    )
    pocket_tool = pocket_raw.edges().fillet(5.0).val()
    print('ROUNDED_POCKET_TOOL_SUCCEEDED')
    solid = solid.cut(pocket_tool).clean()

    # Round all sharp edges at the pocket opening.
    mouth_edges = []
    for edge in sharp_edges(solid):
        c = edge.Center()
        eb = edge.BoundingBox()
        if (abs(c.y-spine_y0) < 0.25 and
                pocket_x0-0.2 <= c.x <= pocket_x1+0.2 and
                pocket_z0-0.2 <= c.z <= pocket_z1+0.2 and
                max(eb.xlen, eb.ylen, eb.zlen) <= 50.0):
            mouth_edges.append(edge)

    print('POCKET_MOUTH_R5_CANDIDATES', len(mouth_edges))
    if mouth_edges:
        trial = cq.Workplane(obj=solid).newObject(mouth_edges).fillet(5.0).val()
        if not trial.isValid():
            raise RuntimeError('Pocket-mouth R5 operation produced invalid body')
        solid = trial.clean()
        print('POCKET_MOUTH_R5_SUCCEEDED', len(mouth_edges))

    # The previous result retained two sharp internal pocket lines generated by
    # the cutter/mouth intersection. Explicitly finish every residual sharp line.
    residual = sharp_lines(solid)
    print('RESIDUAL_R5_CANDIDATES', len(residual))
    if residual:
        try:
            trial = cq.Workplane(obj=solid).newObject(residual).fillet(5.0).val()
            if not trial.isValid():
                raise RuntimeError('invalid batch result')
            solid = trial.clean()
            print('RESIDUAL_R5_BATCH_SUCCEEDED', len(residual))
        except Exception as exc:
            print('RESIDUAL_R5_BATCH_RETRY', str(exc)[:160])
            keys = []
            for edge in residual:
                c = edge.Center()
                keys.append((c.x, c.y, c.z, edge.Length(), edge_axis(edge)))
            succeeded = 0
            for key in keys:
                candidates = [e for e in sharp_lines(solid)
                              if edge_axis(e) == key[4]]
                if not candidates:
                    continue
                edge = min(candidates, key=lambda e:
                    (e.Center().x-key[0])**2+
                    (e.Center().y-key[1])**2+
                    (e.Center().z-key[2])**2+
                    0.0025*(e.Length()-key[3])**2)
                trial = cq.Workplane(obj=solid).newObject([edge]).fillet(5.0).val()
                if trial.isValid():
                    solid = trial.clean()
                    succeeded += 1
            print('RESIDUAL_R5_FALLBACK_SUCCEEDED', succeeded)

    final_sharp = sharp_lines(solid)
    print('FINAL_SHARP_LINE_COUNT', len(final_sharp))
    for i, edge in enumerate(final_sharp):
        c = edge.Center()
        print('FINAL_SHARP_EDGE', i, round(c.x, 3), round(c.y, 3),
              round(c.z, 3), round(edge.Length(), 3), edge_axis(edge))

    if final_sharp:
        raise RuntimeError('Some eligible edges remain sharp after R5 finishing')

    out_bb = solid.BoundingBox()
    print('RESULT_VALID', solid.isValid())
    print('RESULT_VOLUME', round(solid.Volume(), 3))
    print('RESULT_BBOX', round(out_bb.xmin, 3), round(out_bb.xmax, 3),
          round(out_bb.ymin, 3), round(out_bb.ymax, 3),
          round(out_bb.zmin, 3), round(out_bb.zmax, 3))
    print('RESULT_COUNTS', len(solid.Faces()), len(solid.Edges()),
          len(solid.Vertices()))

    if not solid.isValid():
        raise RuntimeError('Final edited body is invalid')
    return cq.Workplane(obj=solid)
