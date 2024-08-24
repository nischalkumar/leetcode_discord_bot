import discord
from discord import app_commands
from discord.ext import commands
import requests
import json
import logging
import asyncio
from datetime import datetime, timedelta
import pytz

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Persistent storage file
PERSISTENT_FILE = "user_data.json"

# In-memory store for user data
user_data = {}

LEETCODE_USER_URL = "https://leetcode.com/graphql"

# Timezone mapping
TIMEZONE_MAPPING = {
    "IST": "Asia/Kolkata",
    "CDT": "America/Chicago",
    # Add more mappings as needed
}

# Function to get formatted LeetCode profile URL
def get_leetcode_profile_url(id):
    return f"https://leetcode.com/problems/{id}"

# Load user data from disk
def load_user_data():
    global user_data
    try:
        with open(PERSISTENT_FILE, 'r') as f:
            user_data = json.load(f)
            logger.info("User data loaded from disk.")
    except FileNotFoundError:
        logger.info("No existing user data file found. Starting fresh.")

# Save user data to disk
def save_user_data():
    with open(PERSISTENT_FILE, 'w') as f:
        json.dump(user_data, f)
        logger.info("User data saved to disk.")

# Function to fetch problem difficulty
def get_problem_difficulty(title_slug):
    query = '''
    query selectProblem($titleSlug: String!) {
        question(titleSlug: $titleSlug) {
            difficulty
        }
    }
    '''
    variables = {
        "titleSlug": title_slug
    }

    logger.info(f"Fetching difficulty for problem {title_slug}")
    response = requests.post(LEETCODE_USER_URL, json={'query': query, 'variables': variables})
    data = response.json()

    if "errors" in data:
        logger.error(f"Error fetching difficulty for {title_slug}: {data['errors']}")
        return None

    return data['data']['question']['difficulty']

def get_user_stats(handle, user_timezone):
    query = '''
    query recentAcSubmissions($username: String!, $limit: Int!) {
        recentAcSubmissionList(username: $username, limit: $limit) {
            title
            titleSlug
            status
            timestamp
        }
    }
    '''
    variables = {
        "username": handle,
        "limit": 100
    }

    logger.info(f"Fetching stats for {handle}")
    response = requests.post(LEETCODE_USER_URL, json={'query': query, 'variables': variables})
    try:
        data = response.json()
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON response for {handle}")
        return None

    if "errors" in data:
        logger.error(f"Error fetching data for {handle}: {data['errors']}")
        return None

    submissions = data['data']['recentAcSubmissionList']
    logger.info(f"Submissions received for {handle}: {submissions}")

    summary = {
        'today': [],
        'yesterday': [],
        'two_days_ago': []
    }

    tz = pytz.timezone(user_timezone)
    now = datetime.now(tz)
    today = now.date()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    for submission in submissions:
        submission_time = datetime.fromtimestamp(int(submission['timestamp']), tz=pytz.UTC).astimezone(tz)
        submission_date = submission_time.date()

        if submission_date < two_days_ago:
            continue

        difficulty = get_problem_difficulty(submission['titleSlug'])
        if not difficulty:
            continue

        entry = {
            'slug':submission['titleSlug'],
            'title': submission['title'],
            'difficulty': difficulty,
            'date': submission_date.isoformat()
        }

        if submission_date == today:
            summary['today'].append(entry)
        elif submission_date == yesterday:
            summary['yesterday'].append(entry)
        elif submission_date == two_days_ago:
            summary['two_days_ago'].append(entry)

    logger.info(f"Processed stats for {handle}: {summary}")
    return summary


def format_user_stats(handle, summary):
    message = f"Stats for {handle}:\n"

    for day, entries in summary.items():
        if entries:
            message += f"\n{day.capitalize()}:\n"
            for entry in entries:
                problem_url = get_leetcode_profile_url(entry.get('slug', None))
                message += f" - Title: [{entry['title']}]({problem_url}), Difficulty: {entry['difficulty']}, Date: {entry['date']}\n"
        else:
            message += f"\n{day.capitalize()}: No problems solved.\n"

    message += "\nSummary:\n"
    for day, entries in summary.items():
        message += f"{day.capitalize()} -> Total: {len(entries)} problems solved.\n"

    return message

@bot.event
async def on_ready():
    logger.info(f'Bot is ready! Logged in as {bot.user}')
    load_user_data()
    await tree.sync()

@tree.command(name="add_handle", description="Add your LeetCode handle and timezone")
async def add_handle(interaction: discord.Interaction, handle: str, timezone: str):
    timezone = timezone.upper()
    if timezone not in TIMEZONE_MAPPING:
        await interaction.response.send_message(f"Invalid timezone. Please use one of: {', '.join(TIMEZONE_MAPPING.keys())}")
        return

    pytz_timezone = TIMEZONE_MAPPING[timezone]
    user_data[interaction.user.name] = {"handle": handle, "timezone": pytz_timezone}
    save_user_data()
    await interaction.response.send_message(f"Added LeetCode handle for {interaction.user.name}: {handle} (Timezone: {timezone})")

@tree.command(name="list_handles", description="List all LeetCode handles")
async def list_handles(interaction: discord.Interaction):
    if not user_data:
        await interaction.response.send_message("No handles have been added.")
    else:
        handles = "\n".join([f"{user}: {data['handle']} (Timezone: {data['timezone']})" for user, data in user_data.items()])
        await interaction.response.send_message(f"Added handles:\n{handles}")

@tree.command(name="user_stats", description="Get your LeetCode stats")
async def user_stats(interaction: discord.Interaction):
    user_info = user_data.get(interaction.user.name)
    if not user_info:
        await interaction.response.send_message("You haven't added your LeetCode handle yet. Use /add_handle <handle> <timezone> to add it.")
        return

    handle = user_info['handle']
    timezone = user_info['timezone']

    initial_response = await interaction.response.send_message("Fetching your LeetCode stats, this may take a moment...")
    
    # Process stats in the background
    loop = asyncio.get_event_loop()
    summary = await loop.run_in_executor(None, get_user_stats, handle, timezone)
    
    if not summary:
        await interaction.followup.send("Failed to retrieve user stats. Please check your handle or try again later.")
        return

    message = format_user_stats(interaction.user.name, summary)
    await interaction.followup.send(message)

# Run the bot
bot.run('your bot id here')

