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
    "PDT": "America/Los_Angeles",
    "PST": "America/Los_Angeles",
    "EST": "America/New_York",
    # Add more mappings as needed
}

# Load user data from disk
def load_user_data():
    global user_data
    try:
        with open(PERSISTENT_FILE, 'r') as f:
            user_data = json.load(f)
            logger.info("User data loaded from disk.")
    except FileNotFoundError:
        logger.info("No existing user data file found. Starting fresh.")

def get_leetcode_problem_url(slug) :
    logger.info("leetcode url generator called")
    return f"https://leetcode.com/problems/{slug}"

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
            'titleSlug': submission['titleSlug'],
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

def format_user_stats_embed(handle, summary):
    embed = discord.Embed(title=f"🚀 {handle}'s LeetCode Stats", color=0x00ff00)

    # Define color representations for difficulty levels
    difficulty_colors = {
        "Easy": "🟩 **Easy**",    # Green square for Easy
        "Medium": "🟧 **Medium**",  # Orange square for Medium
        "Hard": "🟥 **Hard**"     # Red square for Hard
    }

    for day, entries in summary.items():
        if entries:
            value = ""
            for entry in entries:
                problem_url = get_leetcode_problem_url(entry['titleSlug'])
                difficulty_text = difficulty_colors.get(entry['difficulty'], f"**{entry['difficulty']}**")
                value += f"{difficulty_text} - [{entry['title']}]({problem_url}) | Date: `{entry['date']}`\n"
            embed.add_field(name=f"📅 {day.capitalize()}:", value=value, inline=False)
        else:
            embed.add_field(name=f"📅 {day.capitalize()}:", value="No problems solved.", inline=False)

    summary_text = ""
    for day, entries in summary.items():
        summary_text += f"{day.capitalize()} -> Total: `{len(entries)}` problems solved.\n"

    embed.add_field(name="📝 Summary:", value=summary_text, inline=False)
    return embed


async def get_all_user_stats():
    all_stats = {}
    for username, data in user_data.items():
        handle = data['handle']
        timezone = data['timezone']
        logger.info("starting for user {timezone} {handle}")
        summary = get_user_stats(handle, timezone)
        if summary:
            all_stats[username] = summary
    logger.info("all stats %s", all_stats)
    return all_stats

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

#@tree.command(name="user_stats", description="Get your LeetCode stats")
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

    embed = format_user_stats_embed(interaction.user.name, summary)
    await interaction.followup.send(embed=embed)

@tree.command(name="all_user_stats", description="Get LeetCode stats for all users")
async def all_user_stats(interaction: discord.Interaction):
    if not user_data:
        await interaction.response.send_message("No handles have been added.")
        return

    await interaction.response.send_message("Fetching LeetCode stats for all users, this may take a moment...")

    # Await the coroutine to get the actual result
    all_stats = await get_all_user_stats()

    if not all_stats:
        await interaction.followup.send("Failed to retrieve stats for all users. Please try again later.")
        return

    for username, summary in all_stats.items():
        embed = format_user_stats_embed(username, summary)
        await interaction.followup.send(embed=embed)

# Run the bot
bot.run('your_discord_bot_token')

