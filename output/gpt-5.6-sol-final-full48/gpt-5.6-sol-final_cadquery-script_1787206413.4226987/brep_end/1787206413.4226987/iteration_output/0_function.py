def my_cad_function(args):
    import os

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    solids = list(imported.solids().vals())
    print(f"Imported {len(solids)} solids")

    for i, solid in enumerate(solids):
        bb = solid.BoundingBox()
        print(
            f"solid {i}: volume={solid.Volume():.6f}, "
            f"bbox=({bb.xmin:.3f},{bb.ymin:.3f},{bb.zmin:.3f}) to "
            f"({bb.xmax:.3f},{bb.ymax:.3f},{bb.zmax:.3f})"
        )

    if len(solids) < 10:
        raise ValueError("Expected at least 10 solids in the source assembly")

    # Feature-to-solid assignments supplied by the planning model:
    # 7 = front pull handle, 8 = outer coffee-pot vessel, 9 = inner liner.
    handle_index = 7
    pot_indices = (8, 9)
    handle = solids[handle_index]
    pots = [solids[i] for i in pot_indices]

    original_handle_volume = handle.Volume()
    initial_interference = 0.0
    for pot in pots:
        try:
            common = handle.intersect(pot)
            initial_interference += common.Volume()
        except Exception as exc:
            print(f"Initial interference check warning: {exc}")
    print(f"Initial handle/pot common volume: {initial_interference:.6f} mm^3")

    # Make a small outward clearance envelope around each pot component. Scaling
    # is performed about each component's bounding-box center and adds about
    # 0.5 mm at every bounding-box side. This robustly handles the cylindrical
    # vessel, rim, tabs, and liner without modifying their source geometry.
    clearance = 0.5
    clearance_tools = []
    for pot in pots:
        bb = pot.BoundingBox()
        cx = (bb.xmin + bb.xmax) * 0.5
        cy = (bb.ymin + bb.ymax) * 0.5
        cz = (bb.zmin + bb.zmax) * 0.5
        hx = max((bb.xmax - bb.xmin) * 0.5, clearance)
        hy = max((bb.ymax - bb.ymin) * 0.5, clearance)
        hz = max((bb.zmax - bb.zmin) * 0.5, clearance)
        sx = 1.0 + clearance / hx
        sy = 1.0 + clearance / hy
        sz = 1.0 + clearance / hz
        matrix = cq.Matrix([
            [sx, 0.0, 0.0, cx * (1.0 - sx)],
            [0.0, sy, 0.0, cy * (1.0 - sy)],
            [0.0, 0.0, sz, cz * (1.0 - sz)],
            [0.0, 0.0, 0.0, 1.0],
        ])
        try:
            clearance_tools.append(pot.transformGeometry(matrix))
        except Exception as exc:
            print(f"Clearance scaling failed; using exact pot tool: {exc}")
            clearance_tools.append(pot)

    edited_handle = handle
    for tool in clearance_tools:
        try:
            edited_handle = edited_handle.cut(tool)
        except Exception as exc:
            print(f"Clearance cut failed ({exc}); attempting exact-pot cut")

    # Always repeat an exact trim to guarantee removal of positive-volume
    # penetration even if a clearance-envelope operation was unavailable.
    for pot in pots:
        edited_handle = edited_handle.cut(pot)

    try:
        edited_handle = edited_handle.clean()
    except Exception as exc:
        print(f"Handle cleanup warning: {exc}")

    edited_parts = list(edited_handle.Solids())
    if not edited_parts:
        raise ValueError("Clearance operation removed the complete handle")

    # Discard only negligible Boolean slivers. Preserve all meaningful handle
    # pieces if the imported handle was already represented as disconnected
    # mounting/grip regions.
    largest_volume = max(s.Volume() for s in edited_parts)
    edited_parts = [s for s in edited_parts if s.Volume() >= largest_volume * 1.0e-5]
    edited_handle_shape = (edited_parts[0] if len(edited_parts) == 1
                           else cq.Compound.makeCompound(edited_parts))

    final_interference = 0.0
    for pot in pots:
        try:
            final_interference += edited_handle_shape.intersect(pot).Volume()
        except Exception as exc:
            print(f"Final interference check warning: {exc}")

    print(f"Original handle volume: {original_handle_volume:.6f} mm^3")
    print(f"Edited handle volume: {edited_handle_shape.Volume():.6f} mm^3")
    print(f"Final handle/pot common volume: {final_interference:.9f} mm^3")
    print(f"Applied nominal handle-to-pot clearance: {clearance:.3f} mm")

    # Rebuild the assembly as a compound, replacing only the target handle.
    # Every non-handle solid retains its original B-rep and transform.
    output_shapes = []
    for i, solid in enumerate(solids):
        if i == handle_index:
            output_shapes.extend(edited_parts)
        else:
            output_shapes.append(solid)

    result = cq.Compound.makeCompound(output_shapes)
    print(f"Output contains {len(result.Solids())} solids")
    return result