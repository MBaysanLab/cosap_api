from elasticsearch.helpers import scan
from elasticsearch_dsl.connections import get_connection

from .documents import *
from .models import VariantAnnotation


def filter_variants_by_annotation(filters, subset_ids: list = None):
    """
    Filter variants by annotation field and value
    """

    FILTER_FIELDS = {
        "acmg": {
            "query_field": "intervar_classification",
            "query_type": "match",
        },
        "clinvar": {
            "query_field": "clinvar_classification",
            "query_type": "match",
        },
        "amp": {
            "query_field": "cancervar_classification",
            "query_type": "match",
        },
        "consequence": {
            "query_field": "consequence",
            "query_type": "match",
        },
        "rsid": {
            "query_field": "rs_id",
            "query_type": "term",
        },
    }

    search = VariantAnnotationDocument.search()

    if subset_ids:
        search = search.filter("terms", _id=subset_ids)

    for filter in filters:
        query_field, query_value = filter.split("__")
        query_field = query_field.lower()
        field_info = FILTER_FIELDS.get(
            query_field, {"query_field": query_field, "query_type": "term"}
        )
        query_field = field_info["query_field"]
        query_type = field_info["query_type"]

        search = search.filter(query_type, **{query_field: query_value})

    # Get the connection and index name properly
    client = get_connection()
    index = VariantAnnotationDocument._index._name

    # Use scan helper with a proper query structure
    query_dict = search.to_dict()

    results = scan(
        client=client,
        index=index,
        query=query_dict,
        scroll="5m",
        size=1000,
    )
    objectids = [hit["_id"] for hit in results]
    filtered_variants = VariantAnnotation.objects.filter(id__in=objectids)
    return filtered_variants
