"""A fixed skill vocabulary, and the per-role flags the résumé matcher scores on.

`search.keywords` cannot carry this. It prunes any token more than 4% of the
corpus holds, which is exactly the wrong end of the distribution for matching a
résumé: `python` and `aws` are in 0% of the exported vocabulary because they are
in far more than 4% of the ads, and in 7 and 6 of 8,852 *titles* respectively.
The terms a data hunter actually has on their CV are the ones `kw` is built to
throw away.

So this is a second, deliberately small column: a closed list of skills, matched
against the full description before it is dropped, stored as one flag string per
role. Closed rather than open because both ends have to agree — the browser
extracts skills from a résumé with this same vocabulary, and a term only it or
only the ad knows about cannot be matched either way.

Matching is over word-ish boundaries rather than substrings: "r" must not fire on
"our", "go" must not fire on "going", and `ai` must not fire on "said". Every
pattern here is anchored accordingly, and the ambiguous one-and-two-letter names
(R, Go, C) are matched only in the shapes a job ad actually writes them in.
"""

from __future__ import annotations

import re

# slug -> the surface forms that count as a mention.
#
# Ordered, and the order is load-bearing: the export ships flags positionally
# and the page decodes them against the vocabulary in the manifest, so appending
# is safe and reordering silently relabels every row already published.
SKILLS: dict[str, tuple[str, ...]] = {
    # languages and query
    "python": ("python",),
    "sql": ("sql", "t-sql", "pl/sql", "ansi sql"),
    "r": ("r programming", "rstudio", "tidyverse", "ggplot", "ggplot2", "dplyr",
          "shiny"),
    "scala": ("scala",),
    "java": ("java",),
    "julia": ("julia",),
    "sas": ("sas",),
    "spss": ("spss",),
    "stata": ("stata",),
    "matlab": ("matlab",),
    "vba": ("vba", "visual basic"),
    "javascript": ("javascript", "typescript", "node.js", "nodejs"),
    # python data stack
    "pandas": ("pandas",),
    "numpy": ("numpy",),
    "scikit-learn": ("scikit-learn", "scikit learn", "sklearn"),
    "pytorch": ("pytorch", "torch"),
    "tensorflow": ("tensorflow", "keras"),
    "xgboost": ("xgboost", "lightgbm", "catboost", "gradient boosting"),
    "jupyter": ("jupyter", "notebooks"),
    # platforms and stores
    "spark": ("spark", "pyspark"),
    "hadoop": ("hadoop", "hdfs", "mapreduce"),
    "hive": ("hive", "presto", "trino"),
    "kafka": ("kafka", "kinesis", "pubsub", "pub/sub"),
    "snowflake": ("snowflake",),
    "databricks": ("databricks", "delta lake"),
    "bigquery": ("bigquery", "big query"),
    "redshift": ("redshift",),
    "synapse": ("synapse", "azure sql", "data factory", "adf"),
    "teradata": ("teradata",),
    "postgres": ("postgres", "postgresql"),
    "mysql": ("mysql", "mariadb"),
    "mongodb": ("mongodb", "mongo", "dynamodb", "cassandra"),
    "elasticsearch": ("elasticsearch", "opensearch", "elastic"),
    # movement and transformation
    "airflow": ("airflow",),
    "dbt": ("dbt",),
    "dagster": ("dagster", "prefect", "luigi"),
    "informatica": ("informatica", "talend", "ssis", "datastage", "matillion"),
    "fivetran": ("fivetran", "stitch", "airbyte"),
    "etl": ("etl", "elt", "data pipeline", "data pipelines", "ingestion"),
    # bi and visualisation
    "tableau": ("tableau",),
    "powerbi": ("power bi", "powerbi", "power-bi", "dax"),
    "looker": ("looker", "lookml"),
    "qlik": ("qlik", "qlikview", "qliksense"),
    "superset": ("superset", "metabase", "redash"),
    "excel": ("excel", "spreadsheet", "spreadsheets"),
    # cloud and platform
    "aws": ("aws", "amazon web services", "sagemaker", "ec2", "s3", "lambda"),
    "azure": ("azure",),
    "gcp": ("gcp", "google cloud", "vertex ai", "bigtable"),
    "docker": ("docker", "containers", "containerised", "containerized"),
    "kubernetes": ("kubernetes", "k8s"),
    "terraform": ("terraform", "infrastructure as code", "cloudformation"),
    "git": ("git", "github", "gitlab", "bitbucket", "version control"),
    "cicd": ("ci/cd", "cicd", "continuous integration", "continuous delivery"),
    "linux": ("linux", "unix", "bash", "shell scripting"),
    # modelling and method
    "machine-learning": ("machine learning", "ml models", "predictive model",
                         "predictive models", "predictive modelling",
                         "predictive modeling"),
    "deep-learning": ("deep learning", "neural network", "neural networks"),
    "nlp": ("nlp", "natural language processing", "text mining"),
    "computer-vision": ("computer vision", "image recognition", "opencv"),
    "llm": ("llm", "llms", "large language model", "large language models",
            "generative ai", "genai", "prompt engineering"),
    "mlops": ("mlops", "mlflow", "model deployment", "model monitoring",
              "feature store"),
    # The noun forms too: matching is whole-word, so "a/b testing" never saw
    # a résumé that says it "ran A/B tests" or "A/B tested" a change.
    "experimentation": ("a/b testing", "ab testing", "experimentation",
                        "a/b test", "a/b tests", "a/b tested", "ab test",
                        "ab tests", "randomised control", "hypothesis testing"),
    "causal-inference": ("causal inference", "causal", "econometric",
                         "econometrics"),
    "time-series": ("time series", "forecasting", "arima"),
    "recommender": ("recommender", "recommendation system",
                    "recommendation systems", "personalisation",
                    "personalization"),
    "statistics": ("statistics", "statistical", "regression", "bayesian"),
    "optimisation": ("optimisation", "optimization", "operations research",
                     "linear programming"),
    # data practice
    "data-modelling": ("data modelling", "data modeling", "dimensional",
                       "star schema", "data vault", "normalisation"),
    "data-warehouse": ("data warehouse", "data warehousing", "data lake",
                       "lakehouse", "data mart"),
    "governance": ("data governance", "data quality", "data lineage",
                   "master data", "metadata management", "data steward"),
    "privacy": ("gdpr", "privacy act", "pii", "data privacy",
                "responsible ai", "ai ethics"),
    "api": ("rest api", "restful", "api development", "graphql", "microservice",
            "microservices"),
    "agile": ("agile", "scrum", "kanban", "jira"),
    # Appended, and appended for a reason. `rag` was a surface form of `llm`
    # until 2026-09-18, which meant a résumé and an ad that both named the one
    # technique they had in common scored it at `llm`'s weight — 272 ads carry
    # that flag, so it is the generic half of the vocabulary and worth an idf of
    # 3.51. On its own the term is in 73 ads and worth 4.82, which is the rarity
    # the matcher exists to reward and could not see while the two were one slug.
    #
    # The cost is 9 ads that say RAG and never say LLM or GenAI: they keep a
    # `rag` flag and lose their `llm` one, so a résumé naming only LLMs no longer
    # reaches them. Listing "rag" under both slugs would avoid that and score a
    # shared mention twice; one concept per slug is the rule the rest of this
    # file follows, and 0.25% of the index is the price of keeping it.
    "rag": ("rag", "retrieval augmented", "retrieval-augmented",
            "retrieval augmented generation"),
}

VOCAB: tuple[str, ...] = tuple(SKILLS)
INDEX: dict[str, int] = {s: i for i, s in enumerate(VOCAB)}

# The short, ambiguous names, matched only in the shapes an ad writes them in.
# `\bR\b` over prose fires on every sentence that starts with "R" and on "R&D";
# these require a neighbouring language or an explicit label.
_SHARP = {
    "r": re.compile(
        r"(?:python|sql|sas|excel)\s*(?:,|/|&|and|or)\s*r\b"
        r"|\br\s*(?:,|/|&)\s*(?:python|sql|sas|excel)\b"
        r"|\br\b\s+(?:and|or)\s+(?:python|sql|sas)\b"
        r"|\(r\)|\br\s+language\b",
        re.I),
}

# Word-ish boundaries. `+`, `#`, `.`, `/` and `-` are part of a skill name
# ("ci/cd", "scikit-learn", "node.js"), so the boundary is "not one of those and
# not alphanumeric" rather than `\b`, which would split "ci/cd" into two hits.
_EDGE = r"(?:^|[^a-z0-9+#./-])"
_TAIL = r"(?:$|[^a-z0-9+#/-])"


def _pattern(forms: tuple[str, ...]) -> re.Pattern[str]:
    alts = "|".join(sorted((re.escape(f) for f in forms), key=len, reverse=True))
    return re.compile(f"{_EDGE}(?:{alts}){_TAIL}", re.I)


_PATTERNS: dict[str, re.Pattern[str]] = {
    slug: _pattern(forms) for slug, forms in SKILLS.items()
}


def detect(text: str) -> set[str]:
    """The vocabulary slugs `text` mentions.

    Runs over the ad's whole description, not over `kw` — the pruned vocabulary
    has already dropped the common half of this list by the time it is exported.
    """
    if not text:
        return set()
    low = text.lower()
    found = {slug for slug, pat in _PATTERNS.items() if pat.search(low)}
    found |= {slug for slug, pat in _SHARP.items() if pat.search(low)}
    return found


def pack(found: set[str]) -> str:
    """Skills as a space-joined slug list, ordered by the vocabulary.

    A hex bitmask over the same vocabulary is smaller — measured over the 8,852
    exported roles, 8.0KB gzipped against 10.0KB for slugs. That 2KB is 0.1% of
    a 2.0MB payload, and it buys a column that can be read: a wrong flag shows
    up as `powerbi` sitting in a row that never mentions Power BI, where the
    bitmask version shows up as `a4f01c` and gets debugged by hand-decoding
    bits. The export is thrifty about `kw` because `kw` is 56% of the file;
    this column is 0.5% of it, and legibility is the better buy at that price.
    """
    return " ".join(s for s in VOCAB if s in found)


def unpack(blob: str) -> set[str]:
    return set((blob or "").split())


def document_frequency(per_row: list[set[str]]) -> dict[str, int]:
    """How many roles mention each skill.

    Ships with the export because the browser needs it to weight a match and
    cannot derive it from a filtered view. Without it `python` and `sql` — which
    a data résumé and three thousand ads all carry — dominate every score, and
    the ranking reads as arbitrary.
    """
    df = dict.fromkeys(VOCAB, 0)
    for found in per_row:
        for slug in found:
            df[slug] += 1
    return df


# The boundary the page has to reproduce exactly. Shipped rather than retyped in
# JS for the same reason `DATA_TERMS` is: two copies of a matching rule drift,
# and a form the ad recognises but the resume does not is a match that silently
# never happens. Both fragments are valid in JS regex syntax as well as Python.
EDGE = _EDGE
TAIL = _TAIL


def wire() -> dict:
    """Everything the browser needs to run `detect` over a resume itself.

    The ad side of the match happens here at export time, where the description
    still exists; the resume side happens in the page, over text that must never
    leave it. Those are two runs of the same function, so they ship from one
    definition.
    """
    return {
        "skills": list(VOCAB),
        "skill_forms": {slug: list(forms) for slug, forms in SKILLS.items()},
        "skill_sharp": {slug: pat.pattern for slug, pat in _SHARP.items()},
        "skill_edge": EDGE,
        "skill_tail": TAIL,
    }
