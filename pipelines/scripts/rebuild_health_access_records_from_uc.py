from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import Column, DataFrame, SparkSession
else:
    Column = object
    DataFrame = object
    SparkSession = object

try:
    from pyspark.sql import SparkSession as _SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import ArrayType, MapType, StructType

    SparkSession = _SparkSession
except ModuleNotFoundError:
    F = None
    ArrayType = MapType = StructType = type("_MissingSparkType", (), {})


SOURCE_CATALOG = "databricks_virtue_foundation_dataset_dais_2026"
SOURCE_SCHEMA = "virtue_foundation_dataset"

OUTPUT_FIELDS = [
    "record_id",
    "record_type",
    "entity_name",
    "state",
    "district",
    "city",
    "pincode",
    "latitude",
    "longitude",
    "facility_type",
    "operator_type",
    "phone",
    "website",
    "description",
    "office_type",
    "delivery",
    "households_surveyed",
    "institutional_birth_pct",
    "stunting_pct",
    "anaemia_pct",
    "improved_water_pct",
    "improved_sanitation_pct",
    "health_insurance_pct",
]


@dataclass(frozen=True)
class SourceTables:
    facility: str
    pincode: str
    district: str


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild health_access_records from the three DAIS 2026 Unity Catalog source tables."
    )
    parser.add_argument("--catalog", default=SOURCE_CATALOG)
    parser.add_argument("--schema", default=SOURCE_SCHEMA)
    parser.add_argument("--facility-table", help="Facility source table name. Auto-discovered when omitted.")
    parser.add_argument("--pincode-table", help="Pincode/post-office source table name. Auto-discovered when omitted.")
    parser.add_argument("--district-table", help="District indicator source table name. Auto-discovered when omitted.")
    parser.add_argument("--output-table", help="Optional Unity Catalog table for the rebuilt records.")
    parser.add_argument("--output-path", help="Optional CSV output path, for example /Volumes/.../health_access_records_csv.")
    parser.add_argument("--coalesce", type=int, default=1, help="Number of CSV part files when --output-path is used.")
    args, _unknown = parser.parse_known_args()

    if F is None:
        raise SystemExit("PySpark is required. Run this script in Databricks or with spark-submit.")

    spark = SparkSession.builder.getOrCreate()
    tables = _resolve_source_tables(
        spark,
        args.catalog,
        args.schema,
        facility_table=args.facility_table,
        pincode_table=args.pincode_table,
        district_table=args.district_table,
    )

    print("Using source tables")
    print(f"- facility: {tables.facility}")
    print(f"- pincode: {tables.pincode}")
    print(f"- district: {tables.district}")

    facility_records = _build_facility_records(spark.table(tables.facility))
    pincode_records = _build_pincode_records(spark.table(tables.pincode))
    district_records = _build_district_records(spark.table(tables.district))
    records = facility_records.unionByName(pincode_records).unionByName(district_records)
    valid_records, quarantine_records = _split_invalid_facility_rows(records)

    total = records.count()
    valid = valid_records.count()
    quarantine = quarantine_records.count()
    print("Rebuild counts")
    print(f"- total built rows: {total:,}")
    print(f"- valid rows: {valid:,}")
    print(f"- quarantined rows: {quarantine:,}")
    if valid + quarantine != total:
        raise RuntimeError("Valid and quarantine counts do not add up to total built rows.")

    if quarantine:
        print("Quarantined rows are malformed after rebuild. Inspect the quarantine output before loading Lakebase.")

    if args.output_table:
        valid_records.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(args.output_table)
        print(f"Wrote rebuilt records to table {args.output_table}")

    if args.output_path:
        valid_records.coalesce(args.coalesce).write.mode("overwrite").option("header", "true").csv(args.output_path)
        print(f"Wrote rebuilt records CSV to {args.output_path}")


def _resolve_source_tables(
    spark: SparkSession,
    catalog: str,
    schema: str,
    *,
    facility_table: str | None,
    pincode_table: str | None,
    district_table: str | None,
) -> SourceTables:
    table_names = [row.tableName for row in spark.sql(f"SHOW TABLES IN {_qualified(catalog, schema)}").collect()]
    full_names = {name: _qualified(catalog, schema, name) for name in table_names}
    schemas = {name: set(_normalized_columns(spark.table(full_names[name]))) for name in table_names}

    return SourceTables(
        facility=_qualified(catalog, schema, facility_table) if facility_table else full_names[_best_table(schemas, _facility_score)],
        pincode=_qualified(catalog, schema, pincode_table) if pincode_table else full_names[_best_table(schemas, _pincode_score)],
        district=_qualified(catalog, schema, district_table) if district_table else full_names[_best_table(schemas, _district_score)],
    )


def _build_facility_records(df: DataFrame) -> DataFrame:
    name = _clean(_first(df, ["entity_name", "facility_name", "hospital_name", "clinic_name", "name", "title"]))
    state = _clean(_first(df, ["state", "state_name", "statename"]))
    district = _clean(_first(df, ["district", "district_name", "districtname"]))
    city = _clean(_first(df, ["city", "town", "village", "locality", "subdistrict"]))
    pincode = _clean(_first(df, ["pincode", "pin_code", "postal_code", "postcode", "pin"]))
    latitude = _double(_first(df, ["latitude", "lat"]))
    longitude = _double(_first(df, ["longitude", "lon", "lng"]))
    facility_type = _normalize_facility_type(_first(df, ["facility_type", "type", "category", "amenity"]))
    operator_type = _normalize_operator_type(_first(df, ["operator_type", "ownership", "owner_type", "operator"]))
    phone = _clean(_first(df, ["phone", "telephone", "mobile", "contact", "contact_number"]))
    website = _clean(_first_scalar(df, ["website", "url", "web_url", "site"]))
    description = _clean(
        _first(
            df,
            [
                "description",
                "descriptions",
                "about",
                "overview",
                "summary",
                "services",
                "service",
                "specialities",
                "specialties",
                "capabilities",
                "claimed_capabilities",
            ],
        )
    )
    source_id = _first_scalar(df, ["record_id", "facility_id", "id", "uuid", "place_id", "source_id"])
    facility_uuid = _stable_uuid(source_id, name, state, city, pincode, latitude.cast("string"), longitude.cast("string"))

    return df.select(
        F.concat(F.lit("facility:"), facility_uuid).alias("record_id"),
        F.lit("facility").alias("record_type"),
        name.alias("entity_name"),
        state.alias("state"),
        district.alias("district"),
        city.alias("city"),
        pincode.alias("pincode"),
        latitude.alias("latitude"),
        longitude.alias("longitude"),
        facility_type.alias("facility_type"),
        operator_type.alias("operator_type"),
        phone.alias("phone"),
        website.alias("website"),
        description.alias("description"),
        F.lit(None).cast("string").alias("office_type"),
        F.lit(None).cast("string").alias("delivery"),
        F.lit(None).cast("double").alias("households_surveyed"),
        F.lit(None).cast("double").alias("institutional_birth_pct"),
        F.lit(None).cast("double").alias("stunting_pct"),
        F.lit(None).cast("double").alias("anaemia_pct"),
        F.lit(None).cast("double").alias("improved_water_pct"),
        F.lit(None).cast("double").alias("improved_sanitation_pct"),
        F.lit(None).cast("double").alias("health_insurance_pct"),
    )


def _build_pincode_records(df: DataFrame) -> DataFrame:
    name = _clean(_first(df, ["entity_name", "office_name", "officename", "post_office", "name"]))
    state = _clean(_first(df, ["state", "state_name", "statename"]))
    district = _clean(_first(df, ["district", "district_name", "districtname"]))
    pincode = _clean(_first(df, ["pincode", "pin_code", "postal_code", "postcode", "pin"]))
    latitude = _double(_first(df, ["latitude", "lat"]))
    longitude = _double(_first(df, ["longitude", "lon", "lng"]))
    office_type = _clean(_first(df, ["office_type", "officetype", "officeType"]))
    delivery = _clean(_first(df, ["delivery", "delivery_status", "deliverystatus"]))
    description = _clean(
        _join_existing(
            " / ",
            _first(df, ["circle", "circle_name", "circlename"]),
            _first(df, ["region", "region_name", "regionname"]),
            _first(df, ["division", "division_name", "divisionname"]),
        )
    )
    record_key = _join_existing("||", name, state, district, pincode)

    return df.select(
        F.concat(F.lit("pincode:"), F.sha2(record_key, 256)).alias("record_id"),
        F.lit("pincode").alias("record_type"),
        name.alias("entity_name"),
        state.alias("state"),
        district.alias("district"),
        F.lit(None).cast("string").alias("city"),
        pincode.alias("pincode"),
        latitude.alias("latitude"),
        longitude.alias("longitude"),
        F.lit(None).cast("string").alias("facility_type"),
        F.lit(None).cast("string").alias("operator_type"),
        F.lit(None).cast("string").alias("phone"),
        F.lit(None).cast("string").alias("website"),
        description.alias("description"),
        office_type.alias("office_type"),
        delivery.alias("delivery"),
        F.lit(None).cast("double").alias("households_surveyed"),
        F.lit(None).cast("double").alias("institutional_birth_pct"),
        F.lit(None).cast("double").alias("stunting_pct"),
        F.lit(None).cast("double").alias("anaemia_pct"),
        F.lit(None).cast("double").alias("improved_water_pct"),
        F.lit(None).cast("double").alias("improved_sanitation_pct"),
        F.lit(None).cast("double").alias("health_insurance_pct"),
    )


def _build_district_records(df: DataFrame) -> DataFrame:
    district = _clean(_first(df, ["district", "district_name", "districtname", "entity_name"]))
    state = _clean(_first(df, ["state", "state_name", "statename"]))
    record_key = _join_existing("||", state, district)

    return df.select(
        F.concat(F.lit("district:"), F.sha2(record_key, 256)).alias("record_id"),
        F.lit("district").alias("record_type"),
        district.alias("entity_name"),
        state.alias("state"),
        district.alias("district"),
        F.lit(None).cast("string").alias("city"),
        F.lit(None).cast("string").alias("pincode"),
        F.lit(None).cast("double").alias("latitude"),
        F.lit(None).cast("double").alias("longitude"),
        F.lit(None).cast("string").alias("facility_type"),
        F.lit(None).cast("string").alias("operator_type"),
        F.lit(None).cast("string").alias("phone"),
        F.lit(None).cast("string").alias("website"),
        F.concat(F.lit("NFHS district indicators for "), district, F.lit(", "), state).alias("description"),
        F.lit(None).cast("string").alias("office_type"),
        F.lit(None).cast("string").alias("delivery"),
        _double(_first(df, ["households_surveyed", "sample_households", "households"])).alias("households_surveyed"),
        _double(_first(df, ["institutional_birth_pct", "institutional_births_pct", "institutional_delivery_pct"])).alias(
            "institutional_birth_pct"
        ),
        _double(_first(df, ["stunting_pct", "children_stunted_pct"])).alias("stunting_pct"),
        _double(_first(df, ["anaemia_pct", "anemia_pct", "women_anaemia_pct"])).alias("anaemia_pct"),
        _double(_first(df, ["improved_water_pct", "improved_drinking_water_pct"])).alias("improved_water_pct"),
        _double(_first(df, ["improved_sanitation_pct", "sanitation_pct"])).alias("improved_sanitation_pct"),
        _double(_first(df, ["health_insurance_pct", "covered_by_health_insurance_pct"])).alias("health_insurance_pct"),
    )


def _split_invalid_facility_rows(records: DataFrame) -> tuple[DataFrame, DataFrame]:
    invalid = (
        (F.col("record_type") == "facility")
        & (
            ~F.col("record_id").rlike(r"^facility:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
            | F.col("entity_name").isNull()
            | (F.length(F.trim(F.col("entity_name"))) == 0)
            | F.col("entity_name").rlike(r"^\s*[\[\{]")
            | F.col("entity_name").rlike(r"^\s*(\*|__|\*\*|>|#)")
            | F.col("description").rlike(r"^\s*(-?\d+(\.\d+)?|true|false|null|\[|\{)\s*$")
        )
    )
    quarantine = records.where(invalid).select(*OUTPUT_FIELDS)
    valid = records.where(~invalid).select(*OUTPUT_FIELDS)
    return valid, quarantine


def _best_table(schemas: dict[str, set[str]], score_fn) -> str:
    scored = sorted(((score_fn(cols), name) for name, cols in schemas.items()), reverse=True)
    if not scored or scored[0][0] <= 0:
        raise ValueError("Could not discover required source table. Pass the table name explicitly.")
    return scored[0][1]


def _facility_score(columns: set[str]) -> int:
    return _score(columns, ["name", "facilityname", "hospitalname"], 6) + _score(
        columns, ["description", "about", "services", "specialities", "specialties"], 3
    ) + _score(columns, ["latitude", "lat", "longitude", "lon", "lng", "website", "phone"], 1)


def _pincode_score(columns: set[str]) -> int:
    return _score(columns, ["pincode", "pin", "postalcode"], 5) + _score(
        columns, ["officename", "officetype", "delivery", "circle", "region", "division"], 3
    )


def _district_score(columns: set[str]) -> int:
    return _score(columns, ["district", "districtname", "state", "statename"], 3) + _score(
        columns, ["stuntingpct", "anaemiapct", "anemiapct", "institutionalbirthpct", "improvedwaterpct"], 5
    )


def _score(columns: set[str], names: list[str], weight: int) -> int:
    return sum(weight for name in names if _norm(name) in columns)


def _normalized_columns(df: DataFrame) -> list[str]:
    return [_norm(column) for column in df.columns]


def _first(df: DataFrame, names: list[str]) -> Column:
    for name in names:
        column = _find_column(df, name)
        if column:
            return _as_string(df, column)
    return F.lit(None).cast("string")


def _first_scalar(df: DataFrame, names: list[str]) -> Column:
    for name in names:
        column = _find_column(df, name)
        if column:
            return _as_scalar_string(df, column)
    return F.lit(None).cast("string")


def _find_column(df: DataFrame, wanted: str) -> str | None:
    wanted_norm = _norm(wanted)
    for column in df.columns:
        if _norm(column) == wanted_norm:
            return column
    return None


def _as_string(df: DataFrame, column: str) -> Column:
    dtype = df.schema[column].dataType
    if isinstance(dtype, ArrayType):
        return F.concat_ws("; ", F.col(column).cast("array<string>"))
    if isinstance(dtype, (MapType, StructType)):
        return F.to_json(F.col(column))
    return F.col(column).cast("string")


def _as_scalar_string(df: DataFrame, column: str) -> Column:
    dtype = df.schema[column].dataType
    if isinstance(dtype, ArrayType):
        return F.element_at(F.col(column).cast("array<string>"), 1).cast("string")
    if isinstance(dtype, (MapType, StructType)):
        return F.to_json(F.col(column))
    return F.col(column).cast("string")


def _clean(value: Column) -> Column:
    text = F.trim(F.regexp_replace(value.cast("string"), r"\s+", " "))
    return F.when((text == "") | (F.lower(text) == "nan"), F.lit(None).cast("string")).otherwise(text)


def _double(value: Column) -> Column:
    return F.regexp_replace(value.cast("string"), ",", "").cast("double")


def _normalize_facility_type(value: Column) -> Column:
    text = F.lower(_clean(value))
    return (
        F.when(text.rlike("hospital|medical college|nursing home"), "hospital")
        .when(text.rlike("dental|dentist"), "dentist")
        .when(text.rlike("doctor|physician"), "doctor")
        .when(text.rlike("pharmacy|farmacy"), "pharmacy")
        .when(text.rlike("clinic|centre|center|lab|diagnostic"), "clinic")
        .otherwise(text)
    )


def _normalize_operator_type(value: Column) -> Column:
    text = F.lower(_clean(value))
    return (
        F.when(text.rlike("government|govt|public"), "public")
        .when(text.rlike("private|trust|charitable|ngo"), "private")
        .otherwise(text)
    )


def _stable_uuid(*values: Column) -> Column:
    key = _join_existing("||", *values)
    digest = F.md5(key)
    return F.concat(
        F.substring(digest, 1, 8),
        F.lit("-"),
        F.substring(digest, 9, 4),
        F.lit("-"),
        F.substring(digest, 13, 4),
        F.lit("-"),
        F.substring(digest, 17, 4),
        F.lit("-"),
        F.substring(digest, 21, 12),
    )


def _join_existing(separator: str, *values: Column) -> Column:
    cleaned = [_clean(value) for value in values]
    return F.concat_ws(separator, *[F.coalesce(value, F.lit("")) for value in cleaned])


def _qualified(*parts: str) -> str:
    return ".".join(f"`{part.replace('`', '``')}`" for part in parts if part)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


if __name__ == "__main__":
    main()
