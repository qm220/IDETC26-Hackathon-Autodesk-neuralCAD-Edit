def my_cad_function(args):
    import os
    import cadquery as cq

    if "input_file" not in args:
        print("No input_file provided.")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    base = model.val() if hasattr(model, "val") else model

    # Debug info
    try:
        print(f"Loaded STEP: {input_file}")
        print(f"Is Valid: {base.isValid()}")
        print(f"Faces: {len(base.Faces())}, Edges: {len(base.Edges())}, Solids: {len(base.Solids())}")
        cyl_faces = base.Faces("%CYLINDER")
        circ_edges = base.Edges("%CIRCLE")
        print(f"Cylindrical faces: {len(cyl_faces)}")
        print(f"Circular edges: {len(circ_edges)}")
        if len(circ_edges) > 0:
            # Print a few radii for sanity
            for i, e in enumerate(circ_edges[:10]):
                try:
                    c = e.Center()
                    r = e.radius()
                    print(f"  circ_edge[{i}] center=({c.x:.3f},{c.y:.3f},{c.z:.3f}) r={r:.3f}")
                except Exception:
                    pass
    except Exception as e:
        print(f"Debug inspection failed: {e}")

    wp = cq.Workplane(obj=base)

    # Apply 0.2 mm chamfer to circular edges (typically hole edges)
    circ = wp.edges("%CIRCLE")
    circ_list = []
    try:
        circ_list = circ.vals()
    except Exception:
        pass

    if not circ_list:
        print("No circular edges found to chamfer.")
        return wp

    try:
        result = circ.chamfer(0.2)
        print(f"Applied 0.2 mm chamfer to {len(circ_list)} circular edges.")
        return result
    except Exception as e:
        print(f"Chamfer operation failed: {e}")
        # Return unmodified model for inspection
        return wp
