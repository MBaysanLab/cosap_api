from django_elasticsearch_dsl import Document, fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer, char_filter, tokenizer

from .models import VariantAnnotation

space_to_underscore = char_filter(
    "space_to_underscore", type="pattern_replace", pattern="\\s", replacement="_"
)

lowercase_and_fix_space_analyzer = analyzer(
    "lowercase_analyzer",
    tokenizer="keyword",
    filter=["lowercase"],
    char_filter=[space_to_underscore],
)

ngram_tokenizer = tokenizer(
    "ngram_tokenizer",
    type="ngram",
    min_gram=4,
    max_gram=5,
    token_chars=["letter", "digit"],
)

ngram_analyzer = analyzer(
    "ngram_analyzer",
    tokenizer=ngram_tokenizer,
    filter=["lowercase"],
)


@registry.register_document
class VariantAnnotationDocument(Document):
    variant = fields.ObjectField(
        properties={
            "chrom": fields.TextField(analyzer=lowercase_and_fix_space_analyzer),
            "pos": fields.IntegerField(),
            "ref": fields.TextField(analyzer=lowercase_and_fix_space_analyzer),
            "alt": fields.TextField(analyzer=lowercase_and_fix_space_analyzer),
        }
    )

    gene_id = fields.TextField(analyzer=lowercase_and_fix_space_analyzer)
    gene_symbol = fields.TextField(analyzer=lowercase_and_fix_space_analyzer)
    consequence = fields.TextField(analyzer=ngram_analyzer)
    rs_id = fields.TextField(analyzer=lowercase_and_fix_space_analyzer)
    hgvsg = fields.TextField(analyzer=lowercase_and_fix_space_analyzer)
    hgvsc = fields.TextField(analyzer=lowercase_and_fix_space_analyzer)
    hgvsp = fields.TextField(analyzer=lowercase_and_fix_space_analyzer)
    mane = fields.TextField(analyzer=lowercase_and_fix_space_analyzer)
    canonical = fields.BooleanField()
    vep_pick = fields.BooleanField()
    clinvar_classification = fields.TextField(analyzer=lowercase_and_fix_space_analyzer)
    intervar_classification = fields.TextField(
        analyzer=lowercase_and_fix_space_analyzer
    )
    cancervar_classification = fields.TextField(
        analyzer=lowercase_and_fix_space_analyzer
    )

    class Index:
        name = "variant_annotation"
        settings = {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        }

    class Django:
        model = VariantAnnotation
        fields = [
            "id",
        ]
