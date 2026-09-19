import os
import json
import pandas as pd
import boto3
from pymongo import MongoClient
from dotenv import load_dotenv
from io import StringIO
from datetime import datetime

load_dotenv()

# ---------- ENV ----------
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION")

# ---------- MASTER TABLES ----------
FOOD_DB = {
    "Egg": {"calories": 70, "protein": 6},
    "Milk": {"calories": 150, "protein": 8},
    "Paneer": {"calories": 265, "protein": 18},
    "Rice": {"calories": 130, "protein": 2.5},
    "Roti": {"calories": 110, "protein": 3},
    "Oats": {"calories": 150, "protein": 5},
    "Banana": {"calories": 90, "protein": 1},
    "Soya Chunks": {"calories": 170, "protein": 25},
    "Dal": {"calories": 120, "protein": 9},
}

MET = {
    "Bench Press": 6,
    "Pushups": 6,
    "Squats": 6.5,
    "Deadlift": 7,
    "Running": 10,
    "Cycling": 8,
}

# ---------- CONNECT MONGO ----------
client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
collection = db[MONGO_COLLECTION]

# ---------- EXTRACT ----------
data = list(collection.find())

print(f"Extracted {len(data)} records from MongoDB")

# ---------- RAW LOAD ----------
raw_json = json.dumps(data, default=str)

s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)

raw_file_name = (
    f"raw/progress_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
)

s3.put_object(
    Bucket=S3_BUCKET_NAME,
    Key=raw_file_name,
    Body=raw_json,
)

print("Raw data uploaded to S3")

# ---------- TRANSFORM ----------
df = pd.DataFrame(data)

def calc_calories_consumed(foods):
    if not isinstance(foods, list):
        return 0

    total = 0
    for item in foods:
        base = FOOD_DB.get(item.get("foodItem"), {})
        quantity = item.get("quantity", 0)

        total += base.get("calories", 0) * quantity

    return total


def calc_protein_consumed(foods):
    if not isinstance(foods, list):
        return 0

    total = 0
    for item in foods:
        base = FOOD_DB.get(item.get("foodItem"), {})
        quantity = item.get("quantity", 0)

        total += base.get("protein", 0) * quantity

    return total


def calc_calories_burned(row):
    workouts = row.get("workouts", [])
    checkin = row.get("checkIn", {})

    if not isinstance(workouts, list):
        return 0

    current_weight = 70
    if isinstance(checkin, dict):
        current_weight = checkin.get("weightKg", 70)

    total = 0

    for workout in workouts:
        met = MET.get(
            workout.get("exerciseName"), 5
        )

        duration_hours = (
            workout.get("durationMinutes", 0) / 60
        )

        total += (
            met
            * current_weight
            * duration_hours
        )

    return round(total, 2)


def calc_workout_volume(workouts):
    if not isinstance(workouts, list):
        return 0

    return sum(
        workout.get("sets", 0)
        * workout.get("reps", 0)
        * workout.get("weightUsedKg", 0)
        for workout in workouts
    )


df["caloriesConsumed"] = df["foods"].apply(
    calc_calories_consumed
)

df["proteinConsumed"] = df["foods"].apply(
    calc_protein_consumed
)

df["caloriesBurned"] = df.apply(
    calc_calories_burned,
    axis=1,
)

df["netCalories"] = (
    df["caloriesConsumed"]
    - df["caloriesBurned"]
)

df["workoutVolume"] = df["workouts"].apply(
    calc_workout_volume
)

# ---------- PROCESSED LOAD ----------
analytics_df = df[
    [
        "date",
        "_id",
        "userId",
        "caloriesConsumed",
        "proteinConsumed",
        "caloriesBurned",
        "netCalories",
        "workoutVolume",
    ]
].copy()

analytics_df["date"] = pd.to_datetime(
    analytics_df["date"],
    errors="coerce",
    utc=True
)

analytics_df["date"] = analytics_df[
    "date"
].dt.strftime("%Y-%m-%d")

analytics_df.rename(
    columns={"_id": "id"},
    inplace=True,
)

csv_buffer = StringIO()
analytics_df.to_csv(csv_buffer, index=False)

processed_file_name = "processed/progress_metrics_latest.csv"

s3.put_object(
    Bucket=S3_BUCKET_NAME,
    Key=processed_file_name,
    Body=csv_buffer.getvalue(),
)

print("Processed data uploaded to S3")
print("ETL completed successfully")