# Databricks notebook source
# CareGap exploratory notebook.
#
# Keep durable extraction and scoring logic in `pipelines/caregap/`.
# Use this file for quick Databricks exploration and copy stable findings back
# into package code or scripts.

# COMMAND ----------

# Example:
# df = spark.table("public.health_access_records")
# display(df.where("record_type = 'facility'").select("entity_name", "state", "description").limit(20))

