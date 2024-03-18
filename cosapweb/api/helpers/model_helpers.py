def get_updated_model_fields(model, instance, fields):
    """
    Returns updated fields of a model instance.
    """
    updated_fields = {}
    for field in fields:
        if getattr(instance, field) != getattr(model, field):
            updated_fields[field] = getattr(instance, field)
    return updated_fields
