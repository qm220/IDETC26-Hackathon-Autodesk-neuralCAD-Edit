def my_cad_function(args):
    import cadquery as cq
    return cq.importers.importStep(args["input_file"])