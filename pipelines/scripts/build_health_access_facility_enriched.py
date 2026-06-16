from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import Column, DataFrame, SparkSession
else:
    Column = object
    DataFrame = object
    SparkSession = object

try:
    from pyspark.sql import SparkSession as _SparkSession
    from pyspark.sql import Window
    from pyspark.sql import functions as F
    from pyspark.sql.types import ArrayType, MapType, StructType

    SparkSession = _SparkSession
except ModuleNotFoundError:
    F = None
    Window = None
    ArrayType = MapType = StructType = type("_MissingSparkType", (), {})


SOURCE_CATALOG = "databricks_virtue_foundation_dataset_dais_2026"
SOURCE_SCHEMA = "virtue_foundation_dataset"
FACILITY_TABLE = "facilities"
PINCODE_TABLE = "india_post_pincode_directory"
DISTRICT_TABLE = "nfhs_5_district_health_indicators"
OUTPUT_TABLE = "health_access_facility_enriched"
OUTPUT_CATALOG = "workspace"
OUTPUT_SCHEMA = "default"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a facility-grain enriched table from DAIS 2026 Unity Catalog source tables."
    )
    parser.add_argument("--catalog", default=SOURCE_CATALOG)
    parser.add_argument("--schema", default=SOURCE_SCHEMA)
    parser.add_argument("--facility-table", default=FACILITY_TABLE)
    parser.add_argument("--pincode-table", default=PINCODE_TABLE)
    parser.add_argument("--district-table", default=DISTRICT_TABLE)
    parser.add_argument("--output-table", default=_source_name(OUTPUT_CATALOG, OUTPUT_SCHEMA, OUTPUT_TABLE))
    parser.add_argument("--output-path", help="Optional CSV output path, for example /Volumes/.../facility_enriched_csv.")
    parser.add_argument("--coalesce", type=int, default=1, help="Number of CSV part files when --output-path is used.")
    parser.add_argument("--validate-only", action="store_true", help="Build and validate counts without writing outputs.")
    args, _unknown = parser.parse_known_args()

    if F is None:
        raise SystemExit("PySpark is required. Run this script in Databricks or with spark-submit.")

    spark = SparkSession.builder.getOrCreate()
    facility_table = _source_name(args.catalog, args.schema, args.facility_table)
    pincode_table = _source_name(args.catalog, args.schema, args.pincode_table)
    district_table = _source_name(args.catalog, args.schema, args.district_table)
    output_table = args.output_table or _source_name(args.catalog, args.schema, OUTPUT_TABLE)

    print("Using source tables")
    print(f"- facility: {facility_table}")
    print(f"- pincode: {pincode_table}")
    print(f"- district: {district_table}")

    facilities = _build_facility_clean(spark.table(facility_table))
    pincode_rollup = _build_pincode_rollup(spark.table(pincode_table))
    district_clean = _build_district_clean(spark.table(district_table))
    enriched = _build_enriched(facilities, pincode_rollup, district_clean)

    _validate_enriched(facilities, enriched)

    if args.validate_only:
        print("Validate only. No outputs were written.")
        return

    if output_table:
        enriched.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(output_table)
        print(f"Wrote enriched facility table to {output_table}")

    if args.output_path:
        _csv_safe(enriched).coalesce(args.coalesce).write.mode("overwrite").option("header", "true").csv(args.output_path)
        print(f"Wrote enriched facility CSV to {args.output_path}")


def _build_facility_clean(df: DataFrame) -> DataFrame:
    source_unique_id = _clean(_first_scalar(df, ["unique_id", "facility_id", "id", "uuid", "place_id", "source_id"]))
    raw_name = _first(df, ["entity_name", "facility_name", "hospital_name", "clinic_name", "name", "title"])
    facility_name = _clean(F.coalesce(F.get_json_object(raw_name, "$.name"), raw_name))
    source_state = _clean(_first(df, ["state", "state_name", "statename", "address_stateOrRegion"]))
    source_district = _clean(_first(df, ["district", "district_name", "districtname"]))
    source_city = _clean(_first(df, ["city", "town", "village", "locality", "subdistrict", "address_city"]))
    source_pincode = _clean(_first(df, ["pincode", "pin_code", "postal_code", "postcode", "pin", "address_zipOrPostcode"]))
    latitude = _double(_first(df, ["latitude", "lat"]))
    longitude = _double(_first(df, ["longitude", "lon", "lng"]))
    raw_facility_type = _clean(_first(df, ["facility_type", "facilityTypeId", "type", "category", "amenity"]))
    raw_operator_type = _clean(_first(df, ["operator_type", "operatorTypeId", "ownership", "owner_type", "operator"]))
    facility_type = _normalize_facility_type(raw_facility_type)
    operator_type = _normalize_operator_type(raw_operator_type)
    phone = _clean(_first_scalar(df, ["phone", "officialPhone", "phone_numbers", "telephone", "mobile", "contact", "contact_number"]))
    website = _clean(_first_scalar(df, ["website", "officialWebsite", "websites", "url", "web_url", "site"]))
    source_description = _clean(
        _join_existing(
            " ",
            _first(df, ["description", "about", "overview", "summary"]),
            _first(df, ["services", "specialities", "specialties", "departments"]),
        )
    )
    description = F.coalesce(
        source_description,
        _facility_description(facility_name, facility_type, operator_type, source_city, source_state, source_pincode),
    )
    source_quality_flags = F.concat_ws(
        "|",
        F.when(~source_unique_id.rlike(_uuid_pattern()), F.lit("invalid_facility_id")),
        F.when(facility_name.isNull(), F.lit("blank_facility_name")),
        F.when(source_pincode.isNull(), F.lit("missing_pincode")),
        F.when(latitude.isNull() | longitude.isNull(), F.lit("missing_coordinates")),
        F.when(
            raw_facility_type.isNotNull()
            & ~F.lower(raw_facility_type).isin(
                "hospital",
                "clinic",
                "dentist",
                "doctor",
                "pharmacy",
                "farmacy",
                "nursing_home",
                "medical college",
            ),
            F.lit("unexpected_facility_type"),
        ),
        F.when(
            raw_operator_type.isNotNull()
            & ~F.lower(raw_operator_type).isin("private", "public", "government", "trust", "charitable", "ngo"),
            F.lit("unexpected_operator_type"),
        ),
    )

    base = (
        df.select(
            source_unique_id.alias("source_unique_id"),
            facility_name.alias("facility_name"),
            raw_facility_type.alias("raw_facility_type"),
            facility_type.alias("facility_type"),
            raw_operator_type.alias("raw_operator_type"),
            operator_type.alias("operator_type"),
            phone.alias("phone"),
            website.alias("website"),
            description.alias("description"),
            source_state.alias("source_state"),
            source_district.alias("source_district"),
            source_city.alias("source_city"),
            source_pincode.alias("source_pincode"),
            _pincode_key(source_pincode).alias("pincode_key"),
            latitude.alias("latitude"),
            longitude.alias("longitude"),
            source_quality_flags.alias("source_quality_flags"),
        )
        .where(source_unique_id.rlike(_uuid_pattern()))
        .where(F.col("facility_name").isNotNull())
    )
    row_signature = F.sha2(
        F.concat_ws(
            "||",
            *[F.coalesce(F.col(column).cast("string"), F.lit("")) for column in base.columns],
        ),
        256,
    )
    deduped = base.withColumn("source_row_signature", row_signature).dropDuplicates(["source_unique_id", "source_row_signature"])
    duplicate_window = Window.partitionBy("source_unique_id")
    rank_window = Window.partitionBy("source_unique_id").orderBy("source_row_signature")

    return (
        deduped.withColumn("source_duplicate_count", F.count(F.lit(1)).over(duplicate_window))
        .withColumn("source_duplicate_rank", F.row_number().over(rank_window))
        .withColumn(
            "facility_id",
            F.when(
                F.col("source_duplicate_count") == 1,
                F.concat(F.lit("facility:"), F.col("source_unique_id")),
            ).otherwise(
                F.concat(
                    F.lit("facility:"),
                    F.col("source_unique_id"),
                    F.lit(":dup-"),
                    F.lpad(F.col("source_duplicate_rank").cast("string"), 3, "0"),
                )
            ),
        )
        .withColumn(
            "source_quality_flags",
            F.concat_ws(
                "|",
                F.col("source_quality_flags"),
                F.when(F.col("source_duplicate_count") > 1, F.lit("duplicate_source_unique_id")),
            ),
        )
        .select(
            "facility_id",
            "source_unique_id",
            "source_duplicate_count",
            "source_duplicate_rank",
            "source_row_signature",
            "facility_name",
            "raw_facility_type",
            "facility_type",
            "raw_operator_type",
            "operator_type",
            "phone",
            "website",
            "description",
            "source_state",
            "source_district",
            "source_city",
            "source_pincode",
            "pincode_key",
            "latitude",
            "longitude",
            "source_quality_flags",
        )
    )


def _build_pincode_rollup(df: DataFrame) -> DataFrame:
    pincode = _clean(_first(df, ["pincode", "pin_code", "postal_code", "postcode", "pin"]))
    normalized = df.select(
        _pincode_key(pincode).alias("pincode_key"),
        _clean(_first(df, ["state", "state_name", "statename"])).alias("pincode_state"),
        _clean(_first(df, ["district", "district_name", "districtname"])).alias("pincode_district"),
        _clean(_first(df, ["entity_name", "office_name", "officename", "post_office", "name"])).alias("office_name"),
        _clean(_first(df, ["office_type", "officetype", "officeType"])).alias("office_type"),
        _clean(_first(df, ["delivery", "delivery_status", "deliverystatus"])).alias("delivery"),
        _clean(_first(df, ["circle", "circle_name", "circlename"])).alias("circle_name"),
        _clean(_first(df, ["region", "region_name", "regionname"])).alias("region_name"),
        _clean(_first(df, ["division", "division_name", "divisionname"])).alias("division_name"),
        _double(_first(df, ["latitude", "lat"])).alias("pincode_latitude_source"),
        _double(_first(df, ["longitude", "lon", "lng"])).alias("pincode_longitude_source"),
    ).where(F.col("pincode_key").isNotNull())

    location_counts = (
        normalized.where(F.col("pincode_state").isNotNull() & F.col("pincode_district").isNotNull())
        .groupBy("pincode_key", "pincode_state", "pincode_district")
        .count()
    )
    window = Window.partitionBy("pincode_key").orderBy(
        F.desc("count"),
        F.asc("pincode_state"),
        F.asc("pincode_district"),
    )
    canonical_location = (
        location_counts.withColumn("location_rank", F.row_number().over(window))
        .where(F.col("location_rank") == 1)
        .select("pincode_key", "pincode_state", "pincode_district")
    )

    rollup = normalized.groupBy("pincode_key").agg(
        F.count(F.lit(1)).alias("pincode_office_count"),
        F.sort_array(F.collect_set("office_name")).alias("pincode_office_names"),
        F.sort_array(F.collect_set("office_type")).alias("pincode_office_types"),
        F.sort_array(F.collect_set("delivery")).alias("pincode_delivery_values"),
        F.sort_array(F.collect_set("circle_name")).alias("pincode_circle_names"),
        F.sort_array(F.collect_set("region_name")).alias("pincode_region_names"),
        F.sort_array(F.collect_set("division_name")).alias("pincode_division_names"),
        F.avg("pincode_latitude_source").alias("pincode_latitude"),
        F.avg("pincode_longitude_source").alias("pincode_longitude"),
    )

    return rollup.join(canonical_location, on="pincode_key", how="left").withColumn(
        "pincode_match_status",
        F.when(F.col("pincode_state").isNotNull() & F.col("pincode_district").isNotNull(), "matched").otherwise("missing_location"),
    )


def _build_district_clean(df: DataFrame) -> DataFrame:
    district_name = _clean(_first(df, ["district", "district_name", "districtname", "entity_name"]))
    state = _clean(_first(df, ["state", "state_name", "statename", "state_ut"]))
    return df.select(
        state.alias("district_state"),
        district_name.alias("district_name"),
        _name_key(state).alias("district_state_key"),
        _name_key(district_name).alias("district_name_key"),
        _double(_first(df, ["households_surveyed", "sample_households", "households"])).alias("households_surveyed"),
        _double(_first(df, ["institutional_birth_pct", "institutional_births_pct", "institutional_delivery_pct", "institutional_birth_5y_pct"])).alias(
            "institutional_birth_pct"
        ),
        _double(_first(df, ["stunting_pct", "children_stunted_pct", "child_u5_who_are_stunted_height_for_age_18_pct"])).alias("stunting_pct"),
        _double(_first(df, ["anaemia_pct", "anemia_pct", "women_anaemia_pct", "all_w15_49_who_are_anaemic_pct"])).alias("anaemia_pct"),
        _double(_first(df, ["improved_water_pct", "improved_drinking_water_pct", "hh_improved_water_pct"])).alias("improved_water_pct"),
        _double(_first(df, ["improved_sanitation_pct", "sanitation_pct", "hh_use_improved_sanitation_pct"])).alias("improved_sanitation_pct"),
        _double(_first(df, ["health_insurance_pct", "covered_by_health_insurance_pct", "hh_member_covered_health_insurance_pct"])).alias(
            "health_insurance_pct"
        ),
    ).where(F.col("district_state_key").isNotNull() & F.col("district_name_key").isNotNull())


def _build_enriched(facilities: DataFrame, pincode_rollup: DataFrame, district_clean: DataFrame) -> DataFrame:
    joined_location = (
        facilities.alias("f")
        .join(pincode_rollup.alias("p"), on="pincode_key", how="left")
        .withColumn("analysis_state", F.coalesce(F.col("source_state"), F.col("pincode_state")))
        .withColumn("analysis_district", F.coalesce(F.col("source_district"), F.col("pincode_district"), F.col("source_city")))
        .withColumn("analysis_state_key", _name_key(F.col("analysis_state")))
        .withColumn("analysis_district_key", _name_key(F.col("analysis_district")))
        .withColumn(
            "district_source",
            F.when(F.col("source_district").isNotNull(), "source_district")
            .when(F.col("pincode_district").isNotNull(), "pincode_inferred")
            .when(F.col("source_city").isNotNull(), "city_fallback")
            .otherwise("missing_location"),
        )
        .withColumn(
            "location_confidence",
            F.when(F.col("district_source") == "source_district", F.lit(1.0))
            .when(F.col("district_source") == "pincode_inferred", F.lit(0.85))
            .when(F.col("district_source") == "city_fallback", F.lit(0.45))
            .otherwise(F.lit(0.0)),
        )
        .withColumn(
            "pincode_match_status",
            F.when(F.col("pincode_key").isNotNull() & F.col("pincode_state").isNotNull(), "matched").otherwise("missing"),
        )
    )

    enriched = (
        joined_location.alias("j")
        .join(
            district_clean.alias("d"),
            (F.col("j.analysis_state_key") == F.col("d.district_state_key"))
            & (F.col("j.analysis_district_key") == F.col("d.district_name_key")),
            how="left",
        )
        .withColumn(
            "district_match_status",
            F.when(F.col("district_name").isNotNull(), "matched")
            .when(F.col("analysis_district").isNotNull(), "missing_nfhs")
            .otherwise("missing_location"),
        )
        .withColumn(
            "analysis_location_key",
            F.concat_ws("|", F.col("analysis_state_key"), F.col("analysis_district_key")),
        )
        .withColumn("facility_profile_text", _facility_profile_text())
        .withColumn("created_at", F.current_timestamp())
    )

    return enriched.select(
        "facility_id",
        "source_unique_id",
        "source_duplicate_count",
        "source_duplicate_rank",
        "source_row_signature",
        "facility_name",
        "raw_facility_type",
        "facility_type",
        "raw_operator_type",
        "operator_type",
        "phone",
        "website",
        "description",
        "source_state",
        "source_district",
        "source_city",
        "source_pincode",
        "latitude",
        "longitude",
        "pincode_key",
        "pincode_match_status",
        "pincode_state",
        "pincode_district",
        "pincode_office_count",
        "pincode_office_names",
        "pincode_office_types",
        "pincode_delivery_values",
        "pincode_circle_names",
        "pincode_region_names",
        "pincode_division_names",
        "pincode_latitude",
        "pincode_longitude",
        "analysis_state",
        "analysis_district",
        "analysis_location_key",
        "district_source",
        "location_confidence",
        "district_match_status",
        "district_state",
        "district_name",
        "households_surveyed",
        "institutional_birth_pct",
        "stunting_pct",
        "anaemia_pct",
        "improved_water_pct",
        "improved_sanitation_pct",
        "health_insurance_pct",
        "facility_profile_text",
        "source_quality_flags",
        "created_at",
    )


def _facility_profile_text() -> Column:
    return F.concat_ws(
        " ",
        F.col("description"),
        F.when(
            F.col("district_name").isNotNull(),
            F.concat(F.lit("District health indicators for "), F.col("district_name"), F.lit(", "), F.col("district_state"), F.lit(".")),
        ),
        F.when(
            F.col("institutional_birth_pct").isNotNull(),
            F.concat(F.lit("Institutional birth rate: "), F.col("institutional_birth_pct").cast("string"), F.lit("%.")),
        ),
        F.when(F.col("stunting_pct").isNotNull(), F.concat(F.lit("Child stunting: "), F.col("stunting_pct").cast("string"), F.lit("%."))),
        F.when(F.col("anaemia_pct").isNotNull(), F.concat(F.lit("Anaemia: "), F.col("anaemia_pct").cast("string"), F.lit("%."))),
        F.when(
            F.col("health_insurance_pct").isNotNull(),
            F.concat(F.lit("Health insurance coverage: "), F.col("health_insurance_pct").cast("string"), F.lit("%.")),
        ),
    )


def _validate_enriched(facilities: DataFrame, enriched: DataFrame) -> None:
    facility_count = facilities.count()
    enriched_count = enriched.count()
    duplicate_count = enriched.groupBy("facility_id").count().where(F.col("count") > 1).count()
    pincode_counts = enriched.groupBy("pincode_match_status").count().orderBy("pincode_match_status").collect()
    district_counts = enriched.groupBy("district_match_status").count().orderBy("district_match_status").collect()
    source_counts = enriched.groupBy("district_source").count().orderBy("district_source").collect()

    print("Enriched table validation")
    print(f"- input valid facility rows: {facility_count:,}")
    print(f"- enriched facility rows: {enriched_count:,}")
    print(f"- duplicate facility_id rows: {duplicate_count:,}")
    print("- pincode_match_status:")
    for row in pincode_counts:
        print(f"  - {row['pincode_match_status']}: {row['count']:,}")
    print("- district_match_status:")
    for row in district_counts:
        print(f"  - {row['district_match_status']}: {row['count']:,}")
    print("- district_source:")
    for row in source_counts:
        print(f"  - {row['district_source']}: {row['count']:,}")

    if enriched_count != facility_count:
        raise RuntimeError("Enriched row count changed. Pincode or district joins are duplicating/dropping facilities.")
    if duplicate_count:
        raise RuntimeError("Enriched table contains duplicate facility_id rows.")


def _csv_safe(df: DataFrame) -> DataFrame:
    safe = df
    for field in safe.schema.fields:
        if isinstance(field.dataType, ArrayType):
            safe = safe.withColumn(field.name, F.to_json(F.col(field.name)))
    return safe


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
    wanted_norm = _norm_column(wanted)
    for column in df.columns:
        if _norm_column(column) == wanted_norm:
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
    return F.when((text == "") | (F.lower(text).isin("nan", "null")), F.lit(None).cast("string")).otherwise(text)


def _double(value: Column) -> Column:
    number = F.regexp_extract(F.regexp_replace(value.cast("string"), ",", ""), r"-?\d+(?:\.\d+)?", 0)
    return F.when(number == "", F.lit(None).cast("double")).otherwise(number.cast("double"))


def _pincode_key(value: Column) -> Column:
    key = F.regexp_replace(_clean(value), r"[^0-9]", "")
    return F.when(key == "", F.lit(None).cast("string")).otherwise(key)


def _name_key(value: Column) -> Column:
    key = F.lower(F.trim(F.regexp_replace(_clean(value), r"[^A-Za-z0-9]+", " ")))
    return F.when(key == "", F.lit(None).cast("string")).otherwise(key)


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


def _facility_description(
    name: Column,
    facility_type: Column,
    operator_type: Column,
    city: Column,
    state: Column,
    pincode: Column,
) -> Column:
    kind = (
        F.when(
            facility_type.isNotNull() & operator_type.isNotNull(),
            F.concat(F.lit("a "), operator_type, F.lit(" "), F.regexp_replace(facility_type, "_", " ")),
        )
        .when(facility_type.isNotNull(), F.concat(F.lit("a "), F.regexp_replace(facility_type, "_", " ")))
        .when(operator_type.isNotNull(), F.concat(F.lit("a "), operator_type, F.lit(" health facility")))
        .otherwise(F.lit("a health facility"))
    )
    location = _clean(F.concat_ws(", ", city, state, pincode))
    return F.concat(
        name,
        F.lit(" is listed as "),
        kind,
        F.when(location.isNotNull(), F.concat(F.lit(" in "), location)).otherwise(F.lit("")),
        F.lit("."),
    )


def _join_existing(separator: str, *values: Column) -> Column:
    cleaned = [_clean(value) for value in values]
    return F.concat_ws(separator, *[F.coalesce(value, F.lit("")) for value in cleaned])


def _source_name(catalog: str, schema: str, table: str) -> str:
    return ".".join(_quote(part) for part in (catalog, schema, table) if part)


def _quote(part: str) -> str:
    return f"`{part.replace('`', '``')}`"


def _uuid_pattern() -> str:
    return r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def _norm_column(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


if __name__ == "__main__":
    main()
