def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    imported = cq.importers.importStep(input_file)
    root = imported.val() if hasattr(imported, 'val') else imported
    solids = list(root.Solids())
    print('Imported solids:', len(solids))

    # Identify SEC-01 from its documented bounding box and center.
    def target_score(s):
        b = s.BoundingBox()
        c = b.center
        return abs(c.x + 40.0) + abs(c.y + 10.5) + abs(c.z - 12.5)

    target_index = min(range(len(solids)), key=lambda i: target_score(solids[i]))
    target = solids[target_index]
    tb = target.BoundingBox()
    print('Target solid index:', target_index)
    print('Target bbox:', tb.xmin, tb.xmax, tb.ymin, tb.ymax, tb.zmin, tb.zmax)
    print('Original target valid:', target.isValid(), 'volume:', target.Volume())

    # Rear datum is y = 0. The original three-point arrangement consists of two
    # upper mounting points and one lower central point. Replace the lower central
    # point with two symmetric lower points, producing a 2 x 2 rectangular pattern.
    upper_left = (-44.5, 15.5)
    upper_right = (-35.5, 15.5)
    obsolete_lower_center = (-40.0, 5.0)
    lower_left = (-44.5, 5.5)
    lower_right = (-35.5, 5.5)
    four_centers = [upper_left, upper_right, lower_left, lower_right]

    print('Four-point centers:', four_centers)
    print('Obsolete mounting center:', obsolete_lower_center)

    edited = target

    # Close only the rear entrance of the obsolete blind mounting hole. A shallow
    # overlapping cap avoids the invalid long fusion produced previously and does
    # not approach the internal manifold passages. The residual enclosed blind
    # cavity is nonfunctional and does not appear on the rear mounting datum.
    cap_radius = 1.82
    cap_depth = 1.25
    cap = cq.Solid.makeCylinder(
        cap_radius,
        cap_depth + 0.08,
        cq.Vector(obsolete_lower_center[0], tb.ymax + 0.04, obsolete_lower_center[1]),
        cq.Vector(0, -1, 0)
    )
    edited = edited.fuse(cap).clean()
    print('After obsolete-hole closure valid:', edited.isValid())

    # Recut all four equivalent blind pilot holes. Recutting the existing upper
    # pair makes all mounting points geometrically identical. Dimensions follow
    # the existing SEC-01 mounting geometry identified in the previous iteration.
    pilot_radius = 1.2645
    entry_radius = 1.543
    bore_depth = 8.20
    lead_depth = 0.435

    for x, z in four_centers:
        pilot = cq.Solid.makeCylinder(
            pilot_radius,
            bore_depth + 0.08,
            cq.Vector(x, tb.ymax + 0.04, z),
            cq.Vector(0, -1, 0)
        )
        edited = edited.cut(pilot).clean()

        lead_in = cq.Solid.makeCone(
            entry_radius,
            pilot_radius,
            lead_depth + 0.04,
            cq.Vector(x, tb.ymax + 0.02, z),
            cq.Vector(0, -1, 0)
        )
        edited = edited.cut(lead_in).clean()

    print('Edited target valid:', edited.isValid())
    print('Edited target volume:', edited.Volume())
    print('Edited target solids:', len(edited.Solids()))

    # Verify four Y-axis pilot cylinders at the requested rectangular centers.
    detected = set()
    obsolete_open = False
    for face in edited.Faces():
        try:
            if face.geomType() != 'CYLINDER':
                continue
            cyl = face._geomAdaptor().Cylinder()
            axis = cyl.Axis()
            direction = axis.Direction()
            if abs(direction.Y()) < 0.95:
                continue
            loc = axis.Location()
            radius = float(cyl.Radius())

            for x, z in four_centers:
                if (abs(loc.X() - x) < 0.06 and
                        abs(loc.Z() - z) < 0.06 and
                        abs(radius - pilot_radius) < 0.06):
                    detected.add((round(x, 3), round(z, 3)))

            if (abs(loc.X() - obsolete_lower_center[0]) < 0.06 and
                    abs(loc.Z() - obsolete_lower_center[1]) < 0.06):
                # A cylindrical remnant is acceptable only if it no longer reaches
                # the rear datum. Determine this from the face bounding box.
                fb = face.BoundingBox()
                if fb.ymax > tb.ymax - 0.05:
                    obsolete_open = True
        except Exception:
            pass

    detected = sorted(detected)
    print('Verified four-point pilot centers:', detected)
    print('Verified mounting-point count:', len(detected))
    print('Obsolete lower-central opening present at rear datum:', obsolete_open)

    output_solids = list(solids)
    output_solids[target_index] = edited
    result = cq.Compound.makeCompound(output_solids)
    print('Output solids:', len(result.Solids()))
    print('Output valid:', result.isValid())
    return result
