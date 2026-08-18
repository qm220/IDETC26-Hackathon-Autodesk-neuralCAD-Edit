def my_cad_function(args):
    import os
    import cadquery as cq

    input_file = os.path.expanduser(args['input_file'])
    model = cq.importers.importStep(input_file)
    shape = model.val()
    solids = list(shape.Solids())

    print('Loaded model: valid=', shape.isValid(),
          'solids=', len(solids),
          'faces=', len(shape.Faces()))

    # Locate the existing S09 horizontal button. In this model it is the
    # shallow rounded control approximately 43 x 10 x 4.8 mm, centered near
    # (-237, 340, 318.5). Scoring rather than relying solely on the solid index
    # keeps the selection robust to STEP import ordering changes.
    expected_center = cq.Vector(-237.0, 340.0, 318.5)
    expected_dims = (42.9583, 10.0, 4.7917)
    expected_volume = 1623.5385

    candidates = []
    for index, solid in enumerate(solids):
        bb = solid.BoundingBox()
        c = bb.center
        dim_error = (
            abs(bb.xlen - expected_dims[0]) / expected_dims[0] +
            abs(bb.ylen - expected_dims[1]) / expected_dims[1] +
            abs(bb.zlen - expected_dims[2]) / expected_dims[2]
        )
        center_error = (
            abs(c.x - expected_center.x) / 50.0 +
            abs(c.y - expected_center.y) / 50.0 +
            abs(c.z - expected_center.z) / 50.0
        )
        volume_error = abs(solid.Volume() - expected_volume) / expected_volume
        score = 5.0 * dim_error + center_error + volume_error
        candidates.append((score, index, solid, bb, c))

    score, source_index, source_button, source_bb, source_center = min(
        candidates, key=lambda item: item[0]
    )

    print('Selected source button solid:', source_index)
    print('  score=', score,
          'center=', (source_center.x, source_center.y, source_center.z),
          'size=', (source_bb.xlen, source_bb.ylen, source_bb.zlen),
          'volume=', source_button.Volume())

    if score > 0.25:
        raise ValueError('Unable to identify the existing horizontal button reliably')

    # The control deck is locally parallel to XY and the source button's long
    # direction is X. Therefore its above/below arrangement on the deck is
    # produced along Y. A common 20 mm center pitch gives equal 10 mm clear
    # gaps between the three identical 10 mm-wide controls.
    pitch = 20.0
    upper_button = source_button.translate(cq.Vector(0.0, pitch, 0.0))
    lower_button = source_button.translate(cq.Vector(0.0, -pitch, 0.0))

    print('Added exact button copies at centers:')
    for label, button in [('upper', upper_button), ('lower', lower_button)]:
        bb = button.BoundingBox()
        c = bb.center
        print(' ', label,
              (c.x, c.y, c.z),
              'size=', (bb.xlen, bb.ylen, bb.zlen),
              'volume=', button.Volume())

    # Preserve the imported assembly and its 56 original disconnected solids,
    # adding the two copied buttons as separate control solids.
    result = cq.Compound.makeCompound([shape, upper_button, lower_button])
    print('Result: valid=', result.isValid(),
          'solids=', len(result.Solids()),
          'faces=', len(result.Faces()))

    return cq.Workplane('XY').newObject([result])