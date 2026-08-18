def my_cad_function(args):
    import os
    import math
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    root = imported.val()
    solids = list(root.Solids())
    if not solids:
        raise RuntimeError('No solids were imported from the STEP file')

    solids.sort(key=lambda s: s.Volume(), reverse=True)
    wheel = solids[0]
    wb = wheel.BoundingBox()
    axis_x = 0.5 * (wb.xmin + wb.xmax)
    axis_z = 0.5 * (wb.zmin + wb.zmax)
    faces = list(wheel.Faces())

    # The planning B-rep numbering includes the 234 insert faces before the
    # wheel-body faces. Thus global FACE 432 and FACE 667 correspond closely
    # to wheel-local indices 198 and 433, respectively.
    target_indices = [198, 433]

    def radius_of_point(p):
        return math.hypot(p.x - axis_x, p.z - axis_z)

    def describe_edge(edge):
        bb = edge.BoundingBox()
        c = edge.Center()
        verts = list(edge.Vertices())
        vertex_text = []
        for v in verts:
            p = v.Center()
            vertex_text.append('(x=%.6f,y=%.6f,z=%.6f,r=%.6f)' % (
                p.x, p.y, p.z, radius_of_point(p)))
        return ('type=%s length=%.6f center=(%.6f,%.6f,%.6f) centerR=%.6f '
                'bboxY=(%.6f,%.6f) bboxRmax=%.6f vertices=[%s]') % (
            edge.geomType(), edge.Length(), c.x, c.y, c.z,
            radius_of_point(c), bb.ymin, bb.ymax,
            max(abs(bb.xmin-axis_x), abs(bb.xmax-axis_x),
                abs(bb.zmin-axis_z), abs(bb.zmax-axis_z)),
            ', '.join(vertex_text))

    def adjacent_face_indices(face_index):
        result = set()
        target_edges = list(faces[face_index].Edges())
        for j, other in enumerate(faces):
            if j == face_index:
                continue
            found = False
            for e1 in target_edges:
                for e2 in other.Edges():
                    try:
                        if e1.isSame(e2):
                            result.add(j)
                            found = True
                            break
                    except Exception:
                        pass
                if found:
                    break
        return sorted(result)

    print('=== TARGET HUB TOPOLOGY DIAGNOSTIC ===')
    print('Wheel face count:', len(faces))
    print('Axis X=%.6f Z=%.6f' % (axis_x, axis_z))

    for idx in target_indices:
        if idx >= len(faces):
            print('Target local face %d is out of range' % idx)
            continue
        face = faces[idx]
        c = face.Center()
        bb = face.BoundingBox()
        print('\nTARGET FACE local=%d inferredGlobal=%d type=%s area=%.6f' % (
            idx, idx + 234, face.geomType(), face.Area()))
        print(' center=(%.6f,%.6f,%.6f) centerR=%.6f bbox=(%.6f,%.6f) (%.6f,%.6f) (%.6f,%.6f)' % (
            c.x, c.y, c.z, radius_of_point(c), bb.xmin, bb.xmax,
            bb.ymin, bb.ymax, bb.zmin, bb.zmax))
        print(' edges:')
        for k, edge in enumerate(face.Edges()):
            print('  edge %d: %s' % (k, describe_edge(edge)))

        adjacent = adjacent_face_indices(idx)
        print(' adjacent faces:', adjacent)
        for j in adjacent:
            af = faces[j]
            ac = af.Center()
            abb = af.BoundingBox()
            print('  ADJ local=%d inferredGlobal=%d type=%s area=%.6f center=(%.6f,%.6f,%.6f) centerR=%.6f bboxY=(%.6f,%.6f)' % (
                j, j + 234, af.geomType(), af.Area(), ac.x, ac.y, ac.z,
                radius_of_point(ac), abb.ymin, abb.ymax))

    # Find any face that is adjacent to both planned parent faces. Such a face
    # is the strongest topological candidate for the fillet to be replaced.
    if all(i < len(faces) for i in target_indices):
        a0 = set(adjacent_face_indices(target_indices[0]))
        a1 = set(adjacent_face_indices(target_indices[1]))
        common = sorted(a0.intersection(a1))
        print('\nFaces adjacent to BOTH planned parent faces:', common)
        for j in common:
            f = faces[j]
            c = f.Center()
            bb = f.BoundingBox()
            print('  COMMON local=%d inferredGlobal=%d type=%s area=%.6f center=(%.6f,%.6f,%.6f) centerR=%.6f bboxY=(%.6f,%.6f)' % (
                j, j + 234, f.geomType(), f.Area(), c.x, c.y, c.z,
                radius_of_point(c), bb.ymin, bb.ymax))
            for k, edge in enumerate(f.Edges()):
                print('    edge %d: %s' % (k, describe_edge(edge)))

    # Preserve the source during this topology-localization pass.
    result = cq.Compound.makeCompound(solids) if len(solids) > 1 else solids[0]
    return cq.Workplane('XY').newObject([result])