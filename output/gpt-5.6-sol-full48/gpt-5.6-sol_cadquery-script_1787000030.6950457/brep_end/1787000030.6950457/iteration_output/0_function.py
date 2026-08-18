def my_cad_function(args):
    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    shape = model.val()

    bbox = shape.BoundingBox()
    c = bbox.center
    print("MODEL VALID:", shape.isValid())
    print("VOLUME: %.6f" % shape.Volume())
    print("FACES:", len(shape.Faces()))
    print("BBOX: x=(%.5f, %.5f) y=(%.5f, %.5f) z=(%.5f, %.5f)" % (
        bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))
    print("BBOX SIZE: %.5f x %.5f x %.5f" % (bbox.xlen, bbox.ylen, bbox.zlen))
    print("BBOX CENTER: (%.5f, %.5f, %.5f)" % (c.x, c.y, c.z))

    records = []
    for i, face in enumerate(shape.Faces()):
        try:
            area = face.Area()
            fc = face.Center()
            fb = face.BoundingBox()
            geom = face.geomType()
            normal = None
            if geom == "PLANE":
                try:
                    normal = face.normalAt(fc)
                except Exception:
                    try:
                        normal = face.normalAt()
                    except Exception:
                        normal = None
            records.append((area, i, geom, fc, fb, normal))
        except Exception as exc:
            print("FACE %d inspection failed: %s" % (i, exc))

    print("LARGEST 45 FACES:")
    for area, i, geom, fc, fb, normal in sorted(records, reverse=True)[:45]:
        ntext = ""
        if normal is not None:
            ntext = " n=(%.3f,%.3f,%.3f)" % (normal.x, normal.y, normal.z)
        print("F%03d %-10s A=%8.4f C=(%7.3f,%7.3f,%7.3f) ext=(%6.3f,%6.3f,%6.3f)%s" % (
            i, geom, area, fc.x, fc.y, fc.z, fb.xlen, fb.ylen, fb.zlen, ntext))

    print("PLANAR FACES NEAR LONGITUDINAL MIDPOINT:")
    midpoint_records = []
    xmid = c.x
    for rec in records:
        area, i, geom, fc, fb, normal = rec
        if geom == "PLANE" and fb.xmin - 1.0e-5 <= xmid <= fb.xmax + 1.0e-5:
            midpoint_records.append(rec)
    for area, i, geom, fc, fb, normal in sorted(midpoint_records, reverse=True)[:50]:
        ntext = ""
        if normal is not None:
            ntext = " n=(%.3f,%.3f,%.3f)" % (normal.x, normal.y, normal.z)
        print("F%03d A=%8.4f C=(%7.3f,%7.3f,%7.3f) bounds=[x %.3f..%.3f y %.3f..%.3f z %.3f..%.3f]%s" % (
            i, area, fc.x, fc.y, fc.z, fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax, ntext))

    # Probe occupancy along the transverse and vertical directions at the
    # longitudinal center. These intersections help localize the underside
    # cavity and establish safe rib attachment limits for the next iteration.
    print("CENTER-PLANE OCCUPANCY PROBES:")
    probe_thickness = 0.02
    xprobe = cq.Workplane("XY").box(probe_thickness, bbox.ylen + 2.0, bbox.zlen + 2.0)
    xprobe = xprobe.translate((xmid, c.y, c.z))
    try:
        section = shape.intersect(xprobe.val())
        sb = section.BoundingBox()
        print("center slab volume=%.6f bounds y=(%.4f,%.4f) z=(%.4f,%.4f) solids=%d" % (
            section.Volume(), sb.ymin, sb.ymax, sb.zmin, sb.zmax, len(section.Solids())))
    except Exception as exc:
        print("center slab probe failed:", exc)

    for zfrac in (0.05, 0.15, 0.25, 0.35, 0.45, 0.55):
        z = bbox.zmin + zfrac * bbox.zlen
        probe = cq.Workplane("XY").box(probe_thickness, bbox.ylen + 2.0, 0.02)
        probe = probe.translate((xmid, c.y, z))
        try:
            hit = shape.intersect(probe.val())
            print("z=%.4f (%.0f%%) intersection volume=%.7f solids=%d" % (
                z, zfrac * 100.0, hit.Volume(), len(hit.Solids())))
        except Exception as exc:
            print("z probe failed at %.4f: %s" % (z, exc))

    return model