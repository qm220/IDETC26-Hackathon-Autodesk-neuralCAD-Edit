def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args["input_file"])
    imported = cq.importers.importStep(input_file)
    original = imported.val()
    source_edges = list(original.Edges())

    for radius in (0.2, 0.19999, 0.1999, 0.1995, 0.199, 0.195, 0.19):
        try:
            result = original.fillet(radius, source_edges)
            if result.isValid() and len(result.Solids()) == 1:
                return cq.Workplane("XY").newObject([result])
        except Exception:
            pass

    indexed = list(enumerate(source_edges))
    orders = [
        sorted(indexed, key=lambda item: item[1].Length()),
        sorted(indexed, key=lambda item: item[1].Length(), reverse=True),
    ]

    best_shape = original
    best_count = 0
    for order in orders:
        accepted = []
        current = original
        for _, edge in order:
            try:
                trial = original.fillet(0.1999, accepted + [edge])
                if trial.isValid() and len(trial.Solids()) == 1:
                    accepted.append(edge)
                    current = trial
            except Exception:
                pass
        if len(accepted) > best_count:
            best_count = len(accepted)
            best_shape = current

    return cq.Workplane("XY").newObject([best_shape])