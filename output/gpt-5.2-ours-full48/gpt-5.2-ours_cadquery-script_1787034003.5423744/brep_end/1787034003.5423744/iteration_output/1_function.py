def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = args.get("input_file", None)
    if not input_file or not os.path.exists(os.path.expanduser(input_file)):
        raise ValueError(f"Missing or invalid args['input_file']: {input_file}")

    input_file = os.path.expanduser(input_file)
    model = cq.importers.importStep(input_file)

    # Extract basic info to choose a sensible unit interpretation for the 0.2 mm fillet
    shp = model.val() if hasattr(model, "val") else model
    bbox = shp.BoundingBox()
    max_dim = max(bbox.xlen, bbox.ylen, bbox.zlen)
    edge_count = len(shp.Edges())
    face_count = len(shp.Faces())

    # Heuristic: if part is only a few units across (~2 x 6 x 1.5), it is likely inches.
    # Convert 0.2 mm -> inches in that case.
    r_mm = 0.2
    if max_dim < 20:  # likely inches
        r = r_mm / 25.4
        unit_guess = "inch-model; converted 0.2mm to inches"
    else:  # likely mm
        r = r_mm
        unit_guess = "mm-model; used 0.2mm directly"

    print(f"Loaded STEP: {input_file}")
    print(f"BBOX lens: x={bbox.xlen:.6f}, y={bbox.ylen:.6f}, z={bbox.zlen:.6f}, max={max_dim:.6f}")
    print(f"Faces: {face_count}, Edges: {edge_count}")
    print(f"Fillet radius r={r:.8f} ({unit_guess})")

    # Primary attempt: fillet all edges at once
    try:
        result = model.edges().fillet(r)
        print("Global all-edges fillet: SUCCESS")
        return result
    except Exception as e:
        print(f"Global all-edges fillet: FAILED -> {e}")

    # Fallback strategy: try multiple fillet passes on edge subsets
    result = model

    # 1) Linear edges first
    try:
        result = result.edges(cq.selectors.TypeSelector("LINE")).fillet(r)
        print("Subset fillet (LINE edges): SUCCESS")
    except Exception as e:
        print(f"Subset fillet (LINE edges): FAILED -> {e}")

    # 2) Circular edges next
    try:
        result = result.edges(cq.selectors.TypeSelector("CIRCLE")).fillet(r)
        print("Subset fillet (CIRCLE edges): SUCCESS")
    except Exception as e:
        print(f"Subset fillet (CIRCLE edges): FAILED -> {e}")

    # 3) Final attempt on whatever remains (may already be filleted)
    try:
        result = result.edges().fillet(r)
        print("Final all-edges fillet pass: SUCCESS")
    except Exception as e:
        print(f"Final all-edges fillet pass: FAILED -> {e}")

    return result
