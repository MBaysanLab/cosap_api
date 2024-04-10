from enum import Enum


class CosapDnaTaskInputs(Enum):
    ANALYSIS_TYPE = "analysis_type"
    WORKDIR = "workdir"
    NORMAL_SAMPLE = "normal_sample"
    TUMOR_SAMPLES = "tumor_samples"
    BED_FILE = "bed_file"
    MAPPERS = "mappers"
    VARIANT_CALLERS = "variant_callers"
    ANNOTATION = "annotation"
    BAM_QC = "bam_qc"
    TUMOR_SAMPLE_NAME = "tumor_sample_name"
    NORMAL_SAMPLE_NAME = "normal_sample_name"


class Sampletypes(Enum):
    NORMAL = "NORMAL"
    TUMOR = "TUMOR"


class FileExtensions(Enum):
    FQ = ("fastq", "fq")
    FA = ("fa", "fasta")
    SAM = "sam"
    BAM = "bam"
    CRAM = "cram"
    BED = ("bed", "bed6")
    VCF = "vcf"
    TXT = ("txt", "tsv", "csv")
    JSON = "json"
    GFF = ("gff", "gff3")
    GTF = "gtf"
    WIG = ("wig", "bigwig")
    BPK = "bpk"
    PDB = "pdb"
    CIF = "cif"
    BIB = "bib"
    SRA = "sra"
    MAF = "maf"
    OTHER = "other"
    UNKNOWN = "unknown"


class COSAPTasks(Enum):
    DNA_PIPELINE_TASK = "dna_pipeline_task"
    PARSE_PROJECT_RESULTS = "parse_project_results"
    ANNOTATION_TASK = "annotation_task"


class ProjectAlgorithmKeys(Enum):

    # JS naming convention is used since the keys are used in the frontend
    ALIGNER = "aligner"
    VARIANT_CALLER = "variantCaller"
    VARIANT_ANNOTATOR = "variantAnnotator"
    BAM_QC = "bamQC"


class ProjectTypes(Enum):
    SOMATIC = "SOMATIC"
    GERMLINE = "GERMLINE"
    COMPARATIVE = "COMPARATIVE"
    UNKNOWN = "UNKNOWN"


class ProjectStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    PARSING = "PARSING"
    ANNOTATING = "ANNOTATING"


class DnaPipelineResultKeys(Enum):
    pass


class ParseProjectResultsKeys(Enum):
    VARIANTS = "variants"
    QC_RESULTS = "qc_results"
    MSI_SCORE = "msi_score"


class VCFHeaders(Enum):
    CHROM = "CHROM"
    POS = "POS"
    ID = "ID"
    REF = "REF"
    ALT = "ALT"
    QUAL = "QUAL"
    FILTER = "FILTER"
    INFO = "INFO"
    FORMAT = "FORMAT"
    SAMPLE = "SAMPLE"

class ProjectTypeAlgorithms(Enum):
    ProjectTypes.SOMATIC.value = {
         ProjectAlgorithmKeys.ALIGNER: [
            "BWA2"
        ],
        ProjectAlgorithmKeys.VARIANT_CALLER: [
            "Mutect2"
        ],
        ProjectAlgorithmKeys.VARIANT_ANNOTATOR: []
    }
    ProjectTypes.GERMLINE.value = {
        ProjectAlgorithmKeys.ALIGNER: [
            "BWA2"
        ],
        ProjectAlgorithmKeys.VARIANT_CALLER: [
            "HaplotypeCaller"
        ],
        ProjectAlgorithmKeys.VARIANT_ANNOTATOR: []
    }
class AdminConstants(Enum):
    WORKDIR = "admin_workdir"