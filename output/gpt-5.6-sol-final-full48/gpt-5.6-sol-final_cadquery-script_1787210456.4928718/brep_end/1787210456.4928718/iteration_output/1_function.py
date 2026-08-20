def my_cad_function(args):
    import os
    input_file = os.path.expanduser(args['input_file'])
    return cq.importers.importStep(input_file)
