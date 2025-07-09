import logging
from typing import List, Optional, Union
from elasticsearch.helpers import scan
from elasticsearch_dsl.connections import get_connection

from .documents import *
from .models import VariantAnnotation

logger = logging.getLogger(__name__)

# Move filter fields to module level for better configuration management
VARIANT_FILTER_FIELDS = {
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
    "gnomad_af": {
        "query_field": "gnomadg_af",
        "query_type": "range",
    },
}


def filter_variants_by_annotation(
    filters: List[str], subset_ids: Optional[List[Union[str, int]]] = None
):
    """
    Filter variants by annotation field and value using Elasticsearch.

    Args:
        filters: List of filter strings in format "field__value"
        subset_ids: Optional list of variant annotation IDs to filter within

    Returns:
        QuerySet of filtered VariantAnnotation objects

    Example:
        >>> filters = ["acmg__pathogenic", "consequence__missense_variant"]
        >>> variants = filter_variants_by_annotation(filters)
    """
    logger.debug(
        f"Filtering variants with filters: {filters}, subset_ids count: {len(subset_ids) if subset_ids else 0}"
    )

    # Input validation
    if not filters:
        logger.debug("No filters provided, returning empty queryset")
        return VariantAnnotation.objects.none()

    if not isinstance(filters, (list, tuple)):
        raise ValueError("Filters must be a list or tuple")

    try:
        search = VariantAnnotationDocument.search()

        if subset_ids:
            search = search.filter("terms", _id=subset_ids)

        for filter_item in filters:
            # Validate filter format
            if "__" not in filter_item:
                logger.warning(f"Skipping malformed filter: {filter_item}")
                continue  # Skip malformed filters

            parts = filter_item.split("__", 1)  # Split only on first occurrence
            if len(parts) != 2:
                logger.warning(f"Skipping invalid filter format: {filter_item}")
                continue

            query_field, query_value = parts
            query_field = query_field.lower().strip()
            query_value = query_value.strip()

            if not query_field or not query_value:
                logger.warning(
                    f"Skipping filter with empty field or value: {filter_item}"
                )
                continue

            field_info = VARIANT_FILTER_FIELDS.get(
                query_field, {"query_field": query_field, "query_type": "term"}
            )
            query_field = field_info["query_field"]
            query_type = field_info["query_type"]
            print(f"Processing filter: {query_field} with type {query_type} and value {query_value}")

            # Handle range queries for gnomad_af
            if query_type == "range":
                try:
                    # Use filter with bool query for range and null values
                    search = search.filter(
                        "bool",
                        should=[
                            {"range": {query_field: {"lte": float(query_value)}}},
                            {"bool": {"must_not": {"exists": {"field": query_field}}}},
                        ],
                        minimum_should_match=1
                    )
                except ValueError:
                    logger.warning(f"Invalid numeric value for range query: {query_value}")
                    continue
            else:
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

        if not objectids:
            logger.debug("No matching variants found in Elasticsearch")
            return VariantAnnotation.objects.none()

        # Return Django QuerySet for further processing (pagination handled elsewhere)
        filtered_variants = VariantAnnotation.objects.filter(id__in=objectids)
        logger.debug(f"Found {len(objectids)} matching variants")
        return filtered_variants

    except Exception as e:
        # Log the error and return empty queryset
        logger.error(f"Error filtering variants by annotation: {str(e)}")
        return VariantAnnotation.objects.none()
