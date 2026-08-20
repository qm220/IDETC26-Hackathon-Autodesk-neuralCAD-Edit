def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val() if hasattr(imported, "val") else imported

    # Inspect the imported STEP topology and bind FACE references to geometry.
    bbox = original.BoundingBox()
    print("Loaded STEP:", input_file)
    print("Original valid:", original.isValid())
    print("Original solids:", len(original.Solids()))
    print("Original faces:", len(original.Faces()))
    print("Original bbox: x=[%.6f, %.6f], y=[%.6f, %.6f], z=[%.6f, %.6f]" %
          (bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax))

    distal_candidates = []
    for index, face in enumerate(original.Faces()):
        fb = face.BoundingBox()
        center = face.Center()
        geom_type = face.geomType()
        try:
            normal = face.normalAt(center)
            normal_text = "(%.6f, %.6f, %.6f)" % (normal.x, normal.y, normal.z)
        except Exception:
            normal = None
            normal_text = "unavailable"

        print("FACE %d: type=%s area=%.6f center=(%.6f, %.6f, %.6f) "
              "bbox=x[%.6f,%.6f] y[%.6f,%.6f] z[%.6f,%.6f] normal=%s" %
              (index, geom_type, face.Area(), center.x, center.y, center.z,
               fb.xmin, fb.xmax, fb.ymin, fb.ymax, fb.zmin, fb.zmax,
               normal_text))

        # FACE 7 is specified as the planar distal end at maximum X. Resolve it
        # geometrically rather than relying solely on imported face ordering.
        if (geom_type == "PLANE" and
                abs(fb.xmax - fb.xmin) < 1.0e-5 and
                abs(center.x - bbox.xmax) < 1.0e-4):
            score = abs(face.Area() - 48.0)
            if normal is not None:
                score += 1000.0 * abs(abs(normal.x) - 1.0)
            distal_candidates.append((score, index, face, center.x))

    if not distal_candidates:
        raise ValueError("Could not resolve the planar non-rounded distal end face")

    distal_candidates.sort(key=lambda item: item[0])
    _, distal_index, distal_face, mirror_x = distal_candidates[0]
    print("Resolved mirror reference as FACE %d at x=%.6f, area=%.6f" %
          (distal_index, mirror_x, distal_face.Area()))

    # Mirror the complete connected solid across the plane coincident with the
    # distal end face. A YZ plane based at x=mirror_x implements x'=2*mirror_x-x.
    mirrored = original.mirror("YZ", (mirror_x, 0.0, 0.0))
    mb = mirrored.BoundingBox()
    print("Mirrored valid:", mirrored.isValid())
    print("Mirrored bbox: x=[%.6f, %.6f], y=[%.6f, %.6f], z=[%.6f, %.6f]" %
          (mb.xmin, mb.xmax, mb.ymin, mb.ymax, mb.zmin, mb.zmax))

    # Fuse over the complete coincident distal interface and refine away the
    # internal partition/seam while preserving both bosses and blind bores.
    fused = original.fuse(mirrored)
    try:
        fused = fused.clean()
    except Exception as exc:
        print("Shape cleanup was not available; using raw fused result:", exc)

    print("Final valid:", fused.isValid())
    print("Final solids:", len(fused.Solids()))
    print("Final faces:", len(fused.Faces()))
    print("Final volume: %.6f mm^3" % fused.Volume())
    final_bbox = fused.BoundingBox()
    print("Final bbox: x=[%.6f, %.6f], y=[%.6f, %.6f], z=[%.6f, %.6f]" %
          (final_bbox.xmin, final_bbox.xmax,
           final_bbox.ymin, final_bbox.ymax,
           final_bbox.zmin, final_bbox.zmax))

    if not fused.isValid():
        raise ValueError("The fused mirrored result is not a valid B-rep")
    if len(fused.Solids()) != 1:
        raise ValueError("Expected exactly one unified solid, got %d" % len(fused.Solids()))

    return cq.Workplane(obj=fused)
